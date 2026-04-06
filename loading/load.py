import logging
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd
from sqlalchemy import MetaData, Table, create_engine
from sqlalchemy import text
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from dwcahandler import DwcaHandler, Eml, MetaElementTypes
from dwcahandler.dwca import ContentData


def upsert_dataframe_in_batches(
    df: pd.DataFrame,
    load_config: Dict[str, Any],
    db_config: Dict[str, Any],
    batch_size: int = 1000,
):
    """
    Inserts or updates a DataFrame into a MySQL table in batches, committing
    after each batch/chunk.

    Note: This is NOT fully atomic across the entire DataFrame. Each batch is
    atomic on its own: it will either succeed and commit, or fail and roll back.
    """
    logging.info("Database insert/update process starting...")

    connection_url = URL.create(
        drivername="mysql+pymysql",
        username=db_config["database_user"],
        password=db_config["database_password"],
        host=load_config["database_hostname"],
        port=load_config["database_port"],
        database=load_config["database_name"],
        query={"charset": "utf8mb4"},
    )

    engine = create_engine(connection_url)
    Session = sessionmaker(bind=engine)

    try:
        with Session() as session:
            metadata = MetaData()
            table = Table(load_config["database_table"], metadata, autoload_with=engine)

            table_columns = {c.name for c in table.c}
            df_filtered = df[[col for col in df.columns if col in table_columns]].copy()
            df_filtered = df_filtered.replace({np.nan: None})
            total_rows = df_filtered.shape[0]
            pk = load_config["database_table_pk_column"]
            # ✅ count unique keys
            unique_pk = df_filtered[pk].nunique(dropna=True)

            # ✅ get the unique rows (keep first occurrence of each PK)
            df_unique = df_filtered.drop_duplicates(subset=[pk], keep="first")

            logging.info(f"Total rows in df_filtered: {total_rows}")
            logging.info(f"Unique {pk} values: {unique_pk}")
            logging.info(f"Rows after drop_duplicates on {pk}: {len(df_unique)}")

            # Optional: show how many duplicate rows you had
            logging.info(
                f"Duplicate {pk} rows in df_filtered: {total_rows - unique_pk}")

            for start in range(0, len(df_filtered), batch_size):
                end = min(start + batch_size, len(df_filtered))
                batch_df = df_filtered.iloc[start:end]
                records = batch_df.to_dict(orient="records")

                if not records:
                    continue

                try:
                    stmt = insert(table).values(records)

                    stmt = insert(table).values(records).prefix_with("IGNORE")
                    result = session.execute(stmt)
                    session.commit()
                    logging.info(f"Batch {start}:{end} rowcount={result.rowcount}")
                    warns = session.execute(text("SHOW WARNINGS")).fetchall()
                    if warns:
                        logging.warning(f"Batch {start}:{end} warnings: {warns[:10]}")

                except SQLAlchemyError as e:
                    logging.error(
                        f"Error in batch rows {start}:{end}, rolling back batch: {e}"
                    )
                    session.rollback()
                    raise  # re-raise so caller knows it failed

            logging.info("Database insert/update completed successfully.")

    except SQLAlchemyError as e:
        logging.error(f"Database connection or setup error: {e}")
        raise
    except KeyError as e:
        logging.error(f"Configuration key error: Missing key {e}")
        raise
    finally:
        engine.dispose()


def handle_output(
    df: pd.DataFrame,
    load_config: Dict[str, Any],
    db_config: Dict[str, Any],
    source_name: str,
) -> pd.DataFrame:
    """
    Handles filtering, saving to file, and loading to a database for a DataFrame.

    Args:
        df: The DataFrame to process.
        load_config: The configuration for the loading step.
        db_config: The database connection configuration.
        source_name: The name of the data source (e.g., 'occurrence')
                    to generate default filenames.

    Returns:
        The potentially column-filtered DataFrame.
    """
    # 1. Filter columns based on dwc_fields
    dwc_fields = load_config.get("dwc_fields", [])
    if dwc_fields:
        # Ensure only existing columns are selected to prevent KeyErrors
        existing_dwc_fields = [field for field in dwc_fields if field in df.columns]
        df = df[existing_dwc_fields]

    # 2. Write to a CSV file if configured
    if load_config.get("write_to_file"):
        # Use the source_name to create a unique default filename
        default_filename = f"{source_name}_output.csv"
        file_path = load_config.get("targetFilePath", default_filename)
        df.to_csv(
            file_path,
            sep=load_config.get("delimiter", ","),
            encoding=load_config.get("encoding", "utf-8"),
            index=False,
        )
        logging.info(f"Written {df.shape[0]} rows to {file_path}.")

    # 3. Write to the database if configured
    if load_config.get("write_to_db"):
        # Use configured batch size or default to 1000
        batch_size = load_config.get("batch_size", 1000)
        upsert_dataframe_in_batches(df, load_config, db_config, batch_size=batch_size)

    return df


def create_dwca_archive(
    core_df: pd.DataFrame,
    multimedia_df: pd.DataFrame,
    load_config: Dict[str, Any],
    metadata_config: Dict[str, Any],
):
    """
    Creates and saves a Darwin Core Archive (DwC-A), ensuring data quality.

    Args:
        core_df: The DataFrame for the DwC-A core file (occurrences).
        multimedia_df: The DataFrame for the DwC-A extension file (multimedia).
        load_config: The configuration for the DwC-A creation.
        metadata_config: Archive-level metadata used to build the EML document.
    """
    if not load_config.get("write_to_dwca"):
        return

    logging.info("Creating Darwin Core Archive...")

    # --- Improvement: Filter out invalid multimedia records ---
    # The DwC multimedia extension requires a valid identifier (URL).
    # Filter out rows where the identifier is null or empty to prevent errors.
    media_identifier_col = "identifier"  # Standard DwC term for the media URL/URI
    multimedia_df_cleaned = multimedia_df.copy()

    if media_identifier_col not in multimedia_df_cleaned.columns:
        logging.error(
            f"Cannot create DwC-A multimedia extension: "
            f"Missing required column '{media_identifier_col}'. Skipping extension."
        )
        # Create an empty list for the extension frame
        ext_frame = []
    else:
        initial_rows = len(multimedia_df_cleaned)
        # Drop rows where the identifier is NaN, None, or an empty string
        multimedia_df_cleaned = multimedia_df_cleaned.dropna(subset=[media_identifier_col])
        multimedia_df_cleaned = multimedia_df_cleaned[
            multimedia_df_cleaned[media_identifier_col] != ""
        ]
        rows_dropped = initial_rows - len(multimedia_df_cleaned)
        if rows_dropped > 0:
            logging.warning(
                f"Dropped {rows_dropped} multimedia records with missing identifiers."
            )
        # Only add the extension if there's valid data for it
        ext_frame = []
        if not multimedia_df_cleaned.empty:
            ext_frame.append(
                ContentData(
                    data=multimedia_df_cleaned, type=MetaElementTypes.MULTIMEDIA
                )
            )

    core_frame = ContentData(
        data=core_df, type=MetaElementTypes.OCCURRENCE, keys=["occurrenceID"]
    )

    dwca_path_str = load_config.get("dwcaPath")
    if not dwca_path_str:
        logging.error(
            "Cannot create DwC-A: 'dwcaPath' is not specified in the configuration."
        )
        return

    # Convert to a Path object for robust handling
    dwca_path = Path(dwca_path_str)

    # Ensure the parent directory exists before attempting to write the file.
    # This prevents file-not-found errors if subdirectories are not pre-created.
    try:
        dwca_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logging.error(
            f"Failed to create directory for DwC-A at {dwca_path.parent}: {e}"
        )
        return

    required_metadata_fields = [
        "dataset_name",
        "description",
        "citation",
        "rights",
        "license",
    ]
    missing_fields = [
        field for field in required_metadata_fields if not metadata_config.get(field)
    ]
    if missing_fields:
        raise ValueError(
            "Cannot create DwC-A: missing required dwca_metadata fields: "
            + ", ".join(missing_fields)
        )

    eml = Eml(
        dataset_name=metadata_config["dataset_name"],
        description=metadata_config["description"],
        license=metadata_config["license"],
        citation=metadata_config["citation"],
        rights=metadata_config["rights"],
    )
    DwcaHandler.create_dwca(
        core_csv=core_frame,
        ext_csv_list=ext_frame,
        eml_content=eml,
        output_dwca=str(dwca_path),
    )
    logging.info(f"Darwin Core Archive created at {dwca_path}")
