import logging
from typing import List

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
