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


def clean_coordinates(coordinate_string: str) -> str:
    """
    Cleans a coordinate string by standardizing latitude and/or longitude coordinates.
    """

    def standardize_coordinate(coord: str) -> str:
        pattern = re.compile(r"(\d+)°(\d*)'(\d*)''?([NSEW])")
        match = pattern.match(coord)
        if not match:
            return coord

        degrees, minutes, seconds, direction = match.groups()
        if minutes == "":
            return f"{degrees}°{direction}"
        if seconds == "":
            return f"{degrees}°{minutes}'{direction}"
        return f"{degrees}°{minutes}'{seconds}''{direction}"

    coordinates = coordinate_string.split()
    standardized_coordinates = [standardize_coordinate(coord) for coord in coordinates]
    return " ".join(standardized_coordinates)


def update_coordinates(df: pd.DataFrame, coordinate_column: str) -> pd.DataFrame:
    """Updates the values in a coordinate column by cleaning the coordinates."""
    df = df.copy()
    df[coordinate_column] = df[coordinate_column].fillna("")
    df[coordinate_column] = df[coordinate_column].astype(str)
    df["verbatimCoordinates"] = df[coordinate_column].apply(clean_coordinates)

    logging.info(f"Cleaning column '{coordinate_column}' completed successfully.")
    return df
