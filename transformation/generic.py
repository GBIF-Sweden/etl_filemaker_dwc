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


def drop_columns(df: pd.DataFrame, columns_to_drop: List[str]) -> pd.DataFrame:
    """Drops specified columns from the DataFrame if they exist."""
    df = df.copy()
    existing_columns_to_drop = [col for col in columns_to_drop if col in df.columns]

    if not existing_columns_to_drop:
        logging.info("No columns to drop or none of the specified columns exist.")
        return df

    try:
        df = df.drop(columns=existing_columns_to_drop)
        logging.info(f"Dropped columns: {existing_columns_to_drop}")
        return df
    except Exception as e:
        logging.exception(f"An unexpected error occurred in drop_columns: {e}")
        raise


def drop_unmapped_columns(df: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    """Drops columns specified in the 'unmapped' key of the configuration."""
    unmapped_columns = config.get("unmapped", [])
    if not unmapped_columns:
        logging.info("No 'unmapped' columns specified in config to drop.")
        return df

    logging.info("Applying drop_unmapped_columns transformation.")
    return drop_columns(df, unmapped_columns)


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


def trim_value(df: pd.DataFrame, column: str, value: str) -> pd.DataFrame:
    """Trims occurrences of a specific value from the start and end of each string."""
    df = df.copy()
    if not isinstance(df, pd.DataFrame):
        raise TypeError("The first argument must be a pandas DataFrame.")
    if column not in df.columns:
        raise ValueError(
            f"The specified column '{column}' does not exist in the DataFrame."
        )

    df[column] = df[column].astype("string")
    escaped_value = re.escape(value)
    pattern = rf"^\s*{escaped_value}+\s*|\s*{escaped_value}+\s*$"
    df[column] = df[column].replace(pattern, "", regex=True)

    logging.info(
        f"Cleaning column '{column}' of extra '{value}' completed successfully."
    )
    return df


def clean_column_sex(df: pd.DataFrame) -> pd.DataFrame:
    """Cleans the 'sex' column and adds a standardized 'sex_p' column."""
    df = df.copy()

    sex_mapping = {
        "Female": "Female",
        "female": "Female",
        "Female?": "Female",
        "female?": "Female",
        "Male": "Male",
        "male": "Male",
        "Male?": "Male",
        "male?": "Male",
        "0": "Unknown",
        "0?": "Unknown",
        "Male M": "Male",
        "male M": "Male",
        "Hermafrodit": "Hermaphrodite",
        "Hermaphrodite": "Hermaphrodite",
        "Hona": "Female",
        "Okänt": "Unknown",
        "Unknown": "Unknown",
        "Castrated": "Castrated",
        "-": "Unknown",
        "Indeterminate": "Unknown",
    }

    df["sex"] = df["sex"].fillna("").astype(str).str.strip()
    df["sex_p"] = df["sex"].map(sex_mapping)
    mask_unmapped = df["sex_p"].isna() & (df["sex"] != "")

    if mask_unmapped.any():
        unique_unmapped = df.loc[mask_unmapped, "sex"].unique()
        fuzzy_map = {}

        for sex_value in unique_unmapped:
            best_match = max(
                sex_mapping.keys(), key=lambda x: fuzz.ratio(sex_value.lower(), x.lower())
            )
            if fuzz.ratio(sex_value.lower(), best_match.lower()) > 60:
                fuzzy_map[sex_value] = sex_mapping[best_match]
            else:
                fuzzy_map[sex_value] = "Unknown"

        df.loc[mask_unmapped, "sex_p"] = df.loc[mask_unmapped, "sex"].map(fuzzy_map)

    df.loc[df["sex"] == "", "sex_p"] = ""
    df["sex_p"] = df["sex_p"].fillna("Unknown")

    logging.info("Cleaning column sex completed successfully.")
    return df


def clean_column_lifestage(df: pd.DataFrame) -> pd.DataFrame:
    """Cleans the 'lifeStage' column and standardizes values in place."""
    df = df.copy()

    lifestage_mapping = {
        "Adult": "adult",
        "adult": "adult",
        "Adult?": "adult",
        "Adut": "adult",
        "Embryo": "embryo",
        "Featus": "fetus",
        "Fetus": "fetus",
        "Immature": "immature",
        "Juvenil": "juvenile",
        "juvenil": "juvenile",
        "Juvenile": "juvenile",
        "Juvenile?": "juvenile",
        "Juvenlie": "juvenile",
        "Okänd": "",
        "Subadult": "subadult",
        "Subadult?": "subadult",
        "Unknown": "Unknown",
    }

    lifestage_mapping_lower = {k.lower(): v for k, v in lifestage_mapping.items()}
    df["lifeStage"] = df["lifeStage"].fillna("").astype(str).str.strip().str.lower()
    df["lifeStage_p"] = df["lifeStage"].map(lifestage_mapping_lower)
    mask_unmapped = df["lifeStage_p"].isna() & (df["lifeStage"] != "")

    if mask_unmapped.any():
        unique_unmapped = df.loc[mask_unmapped, "lifeStage"].unique()
        fuzzy_map = {}

        for lifestage_value in unique_unmapped:
            best_match = max(
                lifestage_mapping_lower.keys(), key=lambda x: fuzz.ratio(lifestage_value, x)
            )
            if fuzz.ratio(lifestage_value, best_match) > 80:
                fuzzy_map[lifestage_value] = lifestage_mapping_lower[best_match]
            else:
                fuzzy_map[lifestage_value] = ""

        df.loc[mask_unmapped, "lifeStage_p"] = df.loc[mask_unmapped, "lifeStage"].map(
            fuzzy_map
        )

    df["lifeStage_p"] = df["lifeStage_p"].fillna("")
    df["lifeStage"] = df["lifeStage_p"]
    df = df.drop(columns=["lifeStage_p"])

    logging.info("Cleaning column lifeStage completed successfully.")
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


def replace_values(
    df: pd.DataFrame, columns_to_replace: Any, to_replace: str, value: str = ""
) -> pd.DataFrame:
    """
    Replace occurrences of a specified string in one or more columns of a DataFrame.
    """
    df = df.copy()
    try:
        if isinstance(columns_to_replace, str):
            columns_to_replace = [columns_to_replace]

        for column in columns_to_replace:
            if column in df.columns:
                df[column] = df[column].replace(to_replace, value)
                df[column] = df[column].replace({np.nan: value})
            else:
                raise ValueError(f"Column '{column}' does not exist in the DataFrame.")

        logging.info(
            f"Cleaning string '{to_replace}' from columns '{columns_to_replace}' transformation completed successfully."
        )
        return df
    except Exception as e:
        logging.exception(f"An error occurred in replace_values: {e}")
        raise


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
