import logging
import re
from typing import Any

import pandas as pd


def construct_coordinate_string(
    degrees: Any, minutes: Any, seconds: Any, direction: Any
) -> str:
    """Constructs a string representation of coordinates in DMS format."""
    parts = []
    if pd.notna(degrees):
        parts.append(f"{degrees}°")
    if pd.notna(minutes):
        parts.append(f"{minutes}'")
    if pd.notna(seconds):
        parts.append(f"{seconds}''")
    if pd.notna(direction) and direction:
        parts.append(str(direction))
    return " ".join(parts)


def generate_dms_coordinates_column(
    df: pd.DataFrame,
    degrees_column_name: str,
    minutes_column_name: str,
    seconds_column_name: str,
    direction_column_name: str,
    dms_column_name: str,
) -> pd.DataFrame:
    """Generates a new column with coordinates in DMS format."""
    df = df.copy()
    required = [
        degrees_column_name,
        minutes_column_name,
        seconds_column_name,
        direction_column_name,
    ]
    if not all(col in df.columns for col in required):
        missing = [col for col in required if col not in df.columns]
        raise KeyError(f"Missing required columns for DMS generation: {missing}")

    df[dms_column_name] = df.apply(
        lambda row: construct_coordinate_string(
            row[degrees_column_name],
            row[minutes_column_name],
            row[seconds_column_name],
            row[direction_column_name],
        ),
        axis=1,
    )
    logging.info(f"Generated DMS coordinates in column '{dms_column_name}'.")
    return df
