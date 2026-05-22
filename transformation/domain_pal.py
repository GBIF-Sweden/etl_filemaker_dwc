import logging
from typing import Any, Dict, List, Union

import pandas as pd


def move_entities_to_column(
    df: pd.DataFrame, source_col: str, target_col: str, entities: List[str]
) -> pd.DataFrame:
    """
    Moves specified entities from a source column to a target column.
    """
    df = df.copy()
    try:
        if source_col not in df.columns:
            raise KeyError(f"Column '{source_col}' is missing in the DataFrame")

        mask = df[source_col].isin(entities)
        df.loc[mask, target_col] = df.loc[mask, source_col]
        df.loc[mask, source_col] = ""
        logging.info(f"Moved entities from '{source_col}' to '{target_col}'.")
        return df
    except Exception as e:
        logging.exception(f"Error in move_entities_to_column: {e}")
        raise


def pal_move_continents(df: pd.DataFrame) -> pd.DataFrame:
    """Move countries that are actually continents into a separate column."""
    continents = [
        "Africa",
        "Antarctica",
        "Asia",
        "Europe",
        "North America",
        "Oceania",
        "South America",
    ]
    return move_entities_to_column(df, "country", "continent", continents)


def pal_move_oceans(df: pd.DataFrame) -> pd.DataFrame:
    """Move countries that are actually oceans into a separate column."""
    oceans = [
        "Pacific Ocean",
        "Atlantic Ocean",
        "Indian Ocean",
        "Arctic Ocean",
        "Southern Ocean",
    ]
    return move_entities_to_column(df, "country", "waterBody", oceans)


def pad_zero(value: str) -> str:
    """Pad a string value with zeros to a minimum length of 2 characters."""
    return value.zfill(2) if value != "" else value


def pal_fix_synonyms(df: pd.DataFrame) -> pd.DataFrame:
    """Fix synonyms by creating taxon remarks from species names and authors."""
    df = df.copy()
    try:
        df["catalogNumber"] = df["catalogNumber"].ffill()
        df["Species name"] = df["Species name"].fillna("")
        df["Author"] = df["Author"].fillna("")

        species = df["Species name"].fillna("")
        author = df["Author"].fillna("")
        df["taxonRemarks"] = (species + ", " + author).str.strip(", ")

        agg_dict: Dict[str, Any] = {
            col: "first"
            for col in df.columns
            if col not in ["taxonRemarks", "catalogNumber"]
        }
        agg_dict["taxonRemarks"] = lambda x: " | ".join(x)
        df2 = df.groupby("catalogNumber", as_index=False).agg(agg_dict)

        logging.info("pal_fix_synonyms transformation completed successfully.")
        return df2
    except Exception as e:
        logging.exception(f"An unexpected error occurred in pal_fix_synonyms: {e}")
        raise


def pal_adhoc_transform(df: pd.DataFrame) -> pd.DataFrame:
    """Apply ad-hoc PAL transformations."""
    df = df.copy()
    try:
        if "LocalityName" in df.columns and "SiteName" in df.columns:
            df["locality"] = df["LocalityName"] + " - " + df["SiteName"]
        else:
            logging.info("Warning: 'LocalityName' or 'SiteName' column not found.")

        df["month"] = df["month"].fillna("").astype(str).apply(pad_zero)
        df["day"] = df["day"].fillna("").astype(str).apply(pad_zero)
        df["createdDate"] = df["modified"]

        logging.info("pal_adhoc_transform transformation completed successfully.")
    except Exception as e:
        logging.exception(f"An unexpected error occurred in adhoc_transform: {e}")
        raise

    return df
