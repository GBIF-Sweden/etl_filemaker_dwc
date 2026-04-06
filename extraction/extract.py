import logging
from pathlib import Path
from typing import Any, Dict, List, Union

import pandas as pd


class ExtractionError(Exception):
    """Custom exception for extraction failures."""


def extract_from_csv(extract_config: Dict[str, Any]) -> pd.DataFrame:
    """
    Extracts data from one or more CSV files based on the provided configuration.

    This function validates the configuration, ensures the source file(s) exist,
    and reads the CSV(s) using pandas. It supports optional parameters such as
    ``skiprows`` and ``nrows`` to allow partial extraction. If multiple files
    are specified, they are concatenated into a single DataFrame.

    Args:
        extract_config: Dictionary containing extraction configuration. Must
            include ``srcFilePath`` (string or list of strings) and may include
            ``delimiter``, ``encoding``, ``dtype``, ``skiprows``, ``nrows``.

    Returns:
        pandas.DataFrame containing the extracted data. May be empty if the
        source file(s) have no data rows.

    Raises:
        ExtractionError: If required configuration is missing, a file does
            not exist, or pandas fails to read a CSV.
    """
    logging.debug("extract_from_csv called with config: %s", extract_config)

    src_paths_raw: Union[str, List[str], None] = extract_config.get("srcFilePath")

    if not src_paths_raw:
        raise ExtractionError(
            "Missing 'srcFilePath' in the extract configuration. "
            "It must be a string or a list of strings."
        )

    file_paths: List[Path]
    if isinstance(src_paths_raw, str):
        file_paths = [Path(src_paths_raw)]
    elif isinstance(src_paths_raw, list):
        file_paths = [Path(p) for p in src_paths_raw]
    else:
        raise ExtractionError(
            f"Invalid type for 'srcFilePath': {type(src_paths_raw)}. "
            "Expected string or list of strings."
        )

    all_dfs = []
    for file_path in file_paths:
        if not file_path.is_file():
            raise ExtractionError(f"Source file not found: {file_path}")

        logging.info(f"Attempting to extract data from: {file_path}")

        try:
            df = _read_csv(file_path, extract_config)
            if df.empty:
                logging.warning(
                    f"Source file is empty or contains only headers: {file_path}"
                )
            else:
                logging.info(
                    f"Successfully extracted {df.shape[0]} rows from {file_path}."
                )
            all_dfs.append(df)
        except Exception as e:
            logging.error(f"Failed to read CSV from {file_path}: {e}")
            raise ExtractionError(str(e)) from e

    if not all_dfs:
        logging.warning("No dataframes were extracted from the provided source paths.")
        return pd.DataFrame()

    combined_df = pd.concat(all_dfs, ignore_index=True)
    logging.info(
        f"Combined data from {len(file_paths)} file(s) into a single DataFrame "
        f"with {combined_df.shape[0]} rows."
    )
    return combined_df


def _read_csv(file_path: Path, config: Dict[str, Any]) -> pd.DataFrame:
    """Read a CSV file using pandas with options from config."""
    return pd.read_csv(
        file_path,
        delimiter=config.get("delimiter", ","),
        encoding=config.get("encoding", "utf-8"),
        dtype=config.get("dtype"),
        skiprows=config.get("skiprows"),
        nrows=config.get("nrows"),
        low_memory=False,
    )
