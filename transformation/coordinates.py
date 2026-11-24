import logging
import re
from typing import Any

import pandas as pd


_DMS_PATTERN = (
    r"^(?P<hemi1>[NSEW])?\s*"
    r"(?P<sign>[-+])?\s*"
    r"(?P<deg>\d+(?:\.\d+)?)"
    r"(?:\s+(?P<min>\d+(?:\.\d+)?))?"
    r"(?:\s+(?P<sec>\d+(?:\.\d+)?))?\s*"
    r"(?P<hemi2>[NSEW])?$"
)


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


def validate_decimal_coordinates(df: pd.DataFrame,
                                 decimal_lat_column: str = "decimalLatitude",
                                 decimal_lon_column: str = "decimalLongitude") -> pd.DataFrame:
    """Validates decimal latitude and longitude and removes them if invalid"""
    df = df.copy()

    for column, minimum, maximum in (
        (decimal_lat_column, -90, 90),
        (decimal_lon_column, -180, 180),
    ):
        values = pd.to_numeric(df[column], errors="coerce")
        valid = values.between(minimum, maximum)
        # Keep decimal values that are valid, set invalid values to None
        df.loc[valid, column] = values
        df.loc[~valid, column] = None

    return df


def dms_to_decimal_coordinate(
    df: pd.DataFrame, dms_column: str, decimal_column: str
) -> pd.DataFrame:
    """Convert a DMS coordinate to decimal format.

    Handles strings such as:
        40°26'46"N, 40° 26' 46.5" S, -79 58 56, W 79°58'56", 40°26.767'N
    S/W hemispheres and a leading minus produce negative values.
    Unparseable or out-of-range values (minutes/seconds >= 60) become NaN.
    """
    df = df.copy()

    # Normalize: uppercase, turn DMS symbols into spaces, collapse whitespace
    cleaned = (
        df[dms_column]
        .astype("string")
        .str.upper()
        .str.replace("''", " ", regex=False)  # double apostrophe = seconds mark
        .str.replace(r"[°º˚′'’″\"”]", " ", regex=True)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )

    parts = cleaned.str.extract(_DMS_PATTERN)

    deg = pd.to_numeric(parts["deg"], errors="coerce")
    minutes = pd.to_numeric(parts["min"], errors="coerce").fillna(0)
    seconds = pd.to_numeric(parts["sec"], errors="coerce").fillna(0)

    hemisphere = parts["hemi2"].fillna(parts["hemi1"])
    negative = (
        ((parts["sign"] == "-") | hemisphere.isin(["S", "W"]))
        .fillna(False)
        .to_numpy(dtype=bool)
    )

    decimal = deg + minutes / 60 + seconds / 3600
    decimal = decimal.where(~negative, -decimal)

    # Invalidate impossible minute/second values
    decimal = decimal.where((minutes < 60) & (seconds < 60))

    df[decimal_column] = decimal.astype("float64").round(6)
    return df
