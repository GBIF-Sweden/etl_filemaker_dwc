import json
import logging
import re
from typing import Any, Dict, List

import numpy as np
import pandas as pd
from fuzzywuzzy import fuzz


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
