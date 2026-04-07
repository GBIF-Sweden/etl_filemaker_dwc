import json
import logging
import re
from typing import Any, Dict, List

import numpy as np
import pandas as pd
from fuzzywuzzy import fuzz


def clean_whitespace(df: pd.DataFrame) -> pd.DataFrame:
    """Cleans whitespace from all string columns in the DataFrame."""
    df = df.copy()
    try:
        string_columns = df.select_dtypes(include=["object"]).columns
        df[string_columns] = df[string_columns].apply(
            lambda x: x.str.strip().str.replace(r"\s+", " ", regex=True)
        )
        logging.info(f"Whitespace cleaning applied to columns: {list(string_columns)}")
        return df
    except Exception as e:
        logging.exception(f"An error occurred during clean_whitespace: {e}")
        raise


def addprefix(df: pd.DataFrame, target_column: str, prefix: str) -> pd.DataFrame:
    """Prepends a prefix to non-empty values in a target column."""
    df = df.copy()
    try:
        if target_column not in df.columns:
            logging.warning(
                f"Column '{target_column}' not found in addprefix. Skipping."
            )
            return df

        mask = df[target_column].notna() & (df[target_column] != "")
        df.loc[mask, target_column] = prefix + df.loc[mask, target_column].astype(str)

        logging.info(f"addprefix transformation on column '{target_column}' completed.")
        return df
    except Exception as e:
        logging.exception(
            f"An error occurred in addprefix for column '{target_column}': {e}"
        )
        raise


def generate_occ_id_triplet(df: pd.DataFrame) -> pd.DataFrame:
    """Generates occurrenceID from institutionCode, collectionCode, and catalogNumber."""
    df = df.copy()
    try:
        required_cols = ["institutionCode", "collectionCode", "catalogNumber"]
        if not all(col in df.columns for col in required_cols):
            missing = [col for col in required_cols if col not in df.columns]
            raise KeyError(
                f"Missing required columns for occurrenceID generation: {missing}"
            )

        df["occurrenceID"] = (
            df["institutionCode"]
            .astype(str)
            .str.cat(
                [df["collectionCode"].astype(str), df["catalogNumber"].astype(str)],
                sep=":",
            )
        )

        cols = ["occurrenceID"] + [col for col in df.columns if col != "occurrenceID"]
        df = df[cols]
        logging.info("Successfully generated 'occurrenceID' column.")
        return df
    except Exception as e:
        logging.exception(f"An error occurred in generate_occ_id_triplet: {e}")
        raise


def drop_duplicate_rows(df: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    """Removes duplicate rows based on the primary key column from the config."""
    try:
        load_config = config.get("load", {})
        pk_column = load_config.get("database_table_pk_column")
        if not pk_column:
            raise ValueError("Primary key column not specified in load config.")
        if pk_column not in df.columns:
            raise ValueError(
                f"Primary key column '{pk_column}' not found in DataFrame."
            )

        initial_rows = len(df)
        df = df.drop_duplicates(subset=pk_column, keep="first")
        rows_dropped = initial_rows - len(df)

        logging.info(
            f"Dropped {rows_dropped} duplicate rows based on primary key '{pk_column}'."
        )
        return df
    except (ValueError, KeyError) as e:
        logging.error(f"Error in drop_duplicate_rows: {e}")
        raise


def filter_by_string_match(
    df: pd.DataFrame, column: str, string: str, keep_matches: bool = True
) -> pd.DataFrame:
    """Filters rows based on string match in a column."""
    df = df.copy()
    if column not in df.columns:
        logging.warning(f"Column '{column}' not found. Skipping filter.")
        return df

    initial_rows = len(df)
    mask = df[column].str.contains(string, na=False)

    if keep_matches:
        filtered_df = df[mask]
        action = "Selected"
        count = len(filtered_df)
    else:
        filtered_df = df[~mask]
        action = "Dropped"
        count = initial_rows - len(filtered_df)

    logging.info(f"{action} {count} rows where '{column}' contains '{string}'.")
    return filtered_df


def drop_matched_string(
    df: pd.DataFrame, column_to_check: str, string_to_match: str
) -> pd.DataFrame:
    """Drops rows where the specified column contains the given string."""
    return filter_by_string_match(
        df, column_to_check, string_to_match, keep_matches=False
    )


def select_matched_string(
    df: pd.DataFrame, column_to_check: str, string_to_match: str
) -> pd.DataFrame:
    """Filters a DataFrame to include only rows where a column contains a string."""
    return filter_by_string_match(
        df, column_to_check, string_to_match, keep_matches=True
    )


def create_dynamicproperties(
    df: pd.DataFrame, list_of_columns: List[str]
) -> pd.DataFrame:
    """Adds a 'dynamicProperties' column with JSON payloads from selected columns."""

    def build_row_properties(row: pd.Series) -> str:
        properties = {}
        for col in list_of_columns:
            value = row.get(col, None)
            if pd.notnull(value) and value != "":
                properties[col] = value
        return json.dumps(properties, ensure_ascii=False, separators=(",", ":"))

    df = df.copy()
    df["dynamicProperties"] = df.apply(build_row_properties, axis=1)
    return df


def drop_empty_rows(df: pd.DataFrame, column_to_check: str) -> pd.DataFrame:
    """Drops rows where the specified column is empty or null."""
    df = df.copy()
    if column_to_check not in df.columns:
        logging.warning(
            f"Column '{column_to_check}' not found for drop_empty_rows. Skipping."
        )
        return df

    initial_rows = len(df)
    mask_to_drop = df[column_to_check].isna() | (df[column_to_check] == "")
    df_cleaned = df[~mask_to_drop]
    rows_dropped = initial_rows - len(df_cleaned)

    logging.info(
        f"Dropped {rows_dropped} rows where '{column_to_check}' is null or empty."
    )

    return df_cleaned


def split_and_explode(df: pd.DataFrame, column: str, delimiter: str) -> pd.DataFrame:
    """Splits a column by delimiter and explodes the resulting list values."""
    df = df.copy()
    if column not in df.columns:
        raise ValueError(f"Column '{column}' not found in the DataFrame.")

    df[column] = df[column].astype("string").str.split(delimiter)
    exploded_df = df.explode(column)
    exploded_df[column] = exploded_df[column].str.strip()
    final_df = exploded_df.reset_index(drop=True)

    logging.info(f"Exploded column '{column}' using delimiter '{delimiter}'.")
    return final_df
