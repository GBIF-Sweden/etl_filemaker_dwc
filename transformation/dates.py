import logging

import numpy as np
import pandas as pd


def create_date(
    df: pd.DataFrame, col_year: str, col_month: str, col_day: str, col_date: str
) -> pd.DataFrame:
    """
    Creates a new ISO 8601 partial date column from year, month, and day columns.
    """
    df = df.copy()
    required = [col_year, col_month, col_day]
    if not all(col in df.columns for col in required):
        missing = [col for col in required if col not in df.columns]
        raise KeyError(f"Missing required columns for date creation: {missing}")

    year = (
        df[col_year]
        .fillna("")
        .astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .str.strip()
    )
    month = (
        df[col_month]
        .fillna("")
        .astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .str.strip()
    )
    day = (
        df[col_day]
        .fillna("")
        .astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .str.strip()
    )

    has_year = year != ""
    has_month = month != ""
    has_day = day != ""

    df[col_date] = np.select(
        [
            has_year & has_month & has_day,
            has_year & has_month,
            has_year,
        ],
        [
            year + "-" + month.str.zfill(2) + "-" + day.str.zfill(2),
            year + "-" + month.str.zfill(2),
            year,
        ],
        default="",
    )

    logging.info(f"Generated date column '{col_date}'.")
    return df


def convert_date_columns(df: pd.DataFrame, date_column: str) -> pd.DataFrame:
    """
    Converts a specified string column to a consistent ISO 8601 UTC datetime format.
    """
    if date_column not in df.columns:
        logging.warning(
            f"Column '{date_column}' not found in DataFrame. Skipping date conversion."
        )
        return df.copy()

    df = df.copy()
    original_dates_series = df[date_column].copy()

    cleaned_date_strings = original_dates_series.fillna("").astype(str)
    cleaned_date_strings = cleaned_date_strings.str.strip()
    cleaned_date_strings = cleaned_date_strings.str.replace(
        r"[\u00A0\u200B\uFEFF]", "", regex=True
    )
    cleaned_date_strings = cleaned_date_strings.replace(["", "None", "nan"], np.nan)

    date_formats_to_try = [
        "%Y-%m-%d %H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
        "%Y-%m",
        "%Y",
    ]

    parsed_dates = pd.Series(
        [pd.NaT] * len(df), index=df.index, dtype="datetime64[ns, UTC]"
    )

    for fmt in date_formats_to_try:
        unparsed_mask = pd.isna(parsed_dates)
        if unparsed_mask.any():
            temp_parsed = pd.to_datetime(
                cleaned_date_strings[unparsed_mask],
                format=fmt,
                utc=True,
                errors="coerce",
            )
            parsed_dates.loc[unparsed_mask] = parsed_dates.loc[unparsed_mask].fillna(
                temp_parsed
            )

    remaining_indices = parsed_dates[pd.isna(parsed_dates)].index
    if not remaining_indices.empty:
        remaining_cleaned_strings = cleaned_date_strings.loc[remaining_indices]
        general_parsed = pd.to_datetime(
            remaining_cleaned_strings, utc=True, errors="coerce"
        )
        parsed_dates.loc[remaining_indices] = general_parsed

    new_date_column_values = []
    for idx in df.index:
        current_parsed_val = parsed_dates.loc[idx]
        current_original_str = original_dates_series.loc[idx]

        if pd.isna(current_parsed_val):
            if pd.isna(current_original_str) or str(current_original_str).strip() == "":
                new_date_column_values.append("")
            else:
                new_date_column_values.append(str(current_original_str))
        else:
            new_date_column_values.append(
                current_parsed_val.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            )

    processed_df = df.copy()
    processed_df[date_column] = pd.Series(
        new_date_column_values, index=df.index, dtype="object"
    )
    logging.info(f"Converted date column '{date_column}' to ISO 8601 UTC where possible.")
    return processed_df
