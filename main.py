import argparse
import logging
import os
import sys
from typing import Any, Dict, List

import numpy as np
import pandas as pd
from config.config_loader import load_yaml_config
from dotenv import load_dotenv
from extraction.extract import extract_from_csv
from loading.load import create_dwca_archive, handle_output
from transformation.transform import apply_transformations, merge_dataframes
from utils.logging_utils import configure_logging

# Configure logging for the application
configure_logging()

# Load environment variables from the .env file
load_dotenv(dotenv_path=".env")


def get_db_config():
    """
    Loads database credentials securely from environment variables.
    """
    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD")

    if not db_user or not db_password:
        raise ValueError(
            "DB_USER and DB_PASSWORD must be set in the environment or a .env file."
        )

    return {
        "database_user": db_user,
        "database_password": db_password,
    }


def requires_db_config(config: Dict[str, Any]) -> bool:
    """
    Returns True when any configured source is set to write to the database.
    """
    reserved_keys = {"dataset", "merges", "database"}

    for key, value in config.items():
        if key in reserved_keys or not isinstance(value, dict):
            continue

        load_config = value.get("load", {})
        if load_config.get("write_to_db"):
            return True

    return False


def process_source(source_config: Dict[str, Any]) -> pd.DataFrame:
    """
    Extracts data from a CSV and applies transformations for a single source.

    Args:
        source_config: Configuration dictionary for the data source.

    Returns:
        A transformed pandas DataFrame.
    """
    extract_config = source_config.get("extract", {})
    file_path = extract_config.get("srcFilePath", "N/A")
    logging.info(f"Processing source from: {file_path}")

    df = extract_from_csv(extract_config)
    df = apply_transformations(df, source_config)
    return df


def get_merge_specifications(
    config: Dict[str, Any], dataframes: Dict[str, pd.DataFrame]
) -> List[Dict[str, Any]]:
    """
    Generates the list of merge specifications from the configuration.

    Args:
        config: The full configuration dictionary.
        dataframes: A dictionary of all processed dataframes.

    Returns:
        A list of dictionaries, each defining a merge operation.
    """
    merge_specs = []
    merges_config = config.get("merges", [])

    for merge_cfg in merges_config:
        source_name = merge_cfg.get("source")
        if source_name not in dataframes:
            logging.warning(
                f"Merge source '{source_name}' not found in processed dataframes. Skipping."
            )
            continue

        merge_specs.append(
            {
                "df": dataframes[source_name],
                "left_on": merge_cfg["left_on"],
                "right_on": merge_cfg["right_on"],
                "how": merge_cfg.get("how", "left"),
            }
        )
    return merge_specs


def extract_and_transform_sources(config: Dict[str, Any]) -> Dict[str, pd.DataFrame]:
    """
    Identifies source keys dynamically and processes them into DataFrames.
    """
    reserved_keys = ["dataset", "merges", "database"]

    if "occurrence" not in config:
        logging.warning("'occurrence' source missing in config. This is likely an error.")

    source_keys = [
        k
        for k, v in config.items()
        if k not in reserved_keys
        and isinstance(v, dict)
        and ("extract" in v or "mapping" in v)
    ]

    dataframes = {}
    for key in source_keys:
        logging.info(f"Processing source: {key}")
        try:
            dataframes[key] = process_source(config[key])
        except Exception as e:
            logging.warning(
                f"Failed to process source '{key}': {e}. Skipping this source."
            )
            dataframes[key] = pd.DataFrame()

    # Initialize missing expected keys as empty DFs to prevent downstream errors
    for key in ["occurrence", "multimedia"]:
        if key not in dataframes:
            logging.info(f"'{key}' source not found. Initializing empty DataFrame.")
            dataframes[key] = pd.DataFrame()

    return dataframes


def prepare_multimedia_dataframe(
    config: Dict[str, Any], dataframes: Dict[str, pd.DataFrame]
) -> pd.DataFrame:
    """
    Ensures the 'multimedia' DataFrame has the expected structure even if empty.
    """
    df_multimedia = dataframes.get("multimedia", pd.DataFrame())

    if df_multimedia.empty:
        logging.info(
            "Multimedia DataFrame is empty. Ensuring it has expected columns."
        )
        multimedia_config = config.get("multimedia", {})
        multimedia_mapping = multimedia_config.get("mapping", {})
        expected_multimedia_cols = list(multimedia_mapping.values())

        if "occurrenceID" not in expected_multimedia_cols:
            expected_multimedia_cols.append("occurrenceID")

        df_multimedia = pd.DataFrame(columns=expected_multimedia_cols)

    return df_multimedia


def main(config_path: str):
    """
    Orchestrates the ETL process from configuration to final output.
    """
    try:
        config = load_yaml_config(config_path)
        db_config = get_db_config() if requires_db_config(config) else {}

        # --- EXTRACT & TRANSFORM ---
        dataframes = extract_and_transform_sources(config)
        dataframes["multimedia"] = prepare_multimedia_dataframe(config, dataframes)

        # --- MERGE ---
        merge_specs = get_merge_specifications(config, dataframes)
        df_occurrence = merge_dataframes(dataframes["occurrence"], merge_specs)

        null_values = [None, np.nan, "None", "none", "NaN", "nan", "null", "NULL", "Null"]
        df_occurrence = df_occurrence.replace(null_values, "")

        # --- FILTER ---
        occurrence_ids = df_occurrence["occurrenceID"].unique()
        df_multimedia_filtered = dataframes["multimedia"][
            dataframes["multimedia"]["occurrenceID"].isin(occurrence_ids)
        ].replace(null_values, "")

        # --- LOAD ---
        load_config_occurrence = config.get("occurrence", {}).get("load", {})
        df_occurrence_final = handle_output(
            df_occurrence, load_config_occurrence, db_config, source_name="occurrence"
        )

        load_config_multimedia = config.get("multimedia", {}).get("load", {})
        df_multimedia_final = handle_output(
            df_multimedia_filtered,
            load_config_multimedia,
            db_config,
            source_name="multimedia",
        )

        # --- CREATE DwC-A ---
        create_dwca_archive(
            df_occurrence_final,
            df_multimedia_final,
            load_config_occurrence,
            config.get("dwca_metadata", {}),
        )
        logging.info("ETL process completed successfully.")

    except Exception as e:
        logging.error(f"ETL process failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="ETL Process from CSV using configuration."
    )
    parser.add_argument(
        "config_path", type=str, help="Path to the main configuration file."
    )
    args = parser.parse_args()
    try:
        main(args.config_path)
    except Exception:
        sys.exit(1)
