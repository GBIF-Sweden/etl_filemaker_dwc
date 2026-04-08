import logging
from typing import Any, Callable, Dict, List

import pandas as pd

from transformation.coordinates import (
    generate_dms_coordinates_column,
)
from transformation.dates import convert_date_columns, create_date
from transformation.domain_pal import (
    pal_adhoc_transform,
    pal_fix_synonyms,
    pal_move_continents,
    pal_move_oceans,
)
from transformation.generic import (
    addprefix,
    clean_whitespace,
    create_dynamicproperties,
    drop_columns,
    drop_duplicate_rows,
    drop_empty_rows,
    drop_matched_string,
    drop_unmapped_columns,
    generate_occ_id_triplet,
    select_matched_string,
    split_and_explode,
)


class TransformationError(Exception):
    """Custom exception for transformation failures."""


TRANSFORMATION_DISPATCHER: Dict[str, Callable] = {
    "clean_whitespace": clean_whitespace,
    "addprefix": addprefix,
    "generate_occ_id_triplet": generate_occ_id_triplet,
    "drop_columns": drop_columns,
    "drop_unmapped_columns": drop_unmapped_columns,
    "drop_duplicate_rows": drop_duplicate_rows,
    "drop_matched_string": drop_matched_string,
    "select_matched_string": select_matched_string,
    "drop_empty_rows": drop_empty_rows,
    "generate_dms_coordinates_column": generate_dms_coordinates_column,
    "create_date": create_date,
    "replace_values": replace_values,
    "create_dynamicproperties": create_dynamicproperties,
    "trim_value": trim_value,
    "pal_move_continents": pal_move_continents,
    "pal_move_oceans": pal_move_oceans,
    "pal_adhoc_transform": pal_adhoc_transform,
    "pal_fix_synonyms": pal_fix_synonyms,
    "clean_column_sex": clean_column_sex,
    "clean_column_lifestage": clean_column_lifestage,
    "split_and_explode": split_and_explode,
    "convert_date_columns": convert_date_columns,
}


def apply_transformations(df: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    """
    Applies a series of transformations to a DataFrame based on a configuration.
    """
    df = df.copy()
    try:
        rename_mapping = config.get("mapping", {})
        if rename_mapping:
            df = df.rename(columns=rename_mapping)
            logging.info(
                f"Renamed columns based on mapping: {list(rename_mapping.keys())}"
            )

        for col, default_value in config.get("defaults", {}).items():
            df[col] = default_value
            logging.info(f"Applied default value '{default_value}' to column '{col}'.")

        for transform in config.get("transformations", []):
            func_name = transform.get("function")
            params = transform.get("params", {})

            if func_name in TRANSFORMATION_DISPATCHER:
                logging.info(
                    f"Applying transformation: '{func_name}' with params: {params}"
                )
                transform_func = TRANSFORMATION_DISPATCHER[func_name]
                if func_name in ["drop_unmapped_columns", "drop_duplicate_rows"]:
                    df = transform_func(df, config)
                else:
                    df = transform_func(df, **params)
            else:
                logging.warning(
                    f"Transformation function '{func_name}' not found. Skipping."
                )

        return df
    except Exception as e:
        logging.error(f"An error occurred during transformation: {e}", exc_info=True)
        raise


def merge_dataframes(
    base_df: pd.DataFrame, merge_specs: List[Dict[str, Any]]
) -> pd.DataFrame:
    """
    Merges a base DataFrame with multiple DataFrames based on specified keys.
    """
    for spec in merge_specs:
        try:
            logging.info(
                f"Merging with DataFrame on left:'{spec['left_on']}' "
                f"and right:'{spec['right_on']}'"
            )
            base_df = pd.merge(
                base_df,
                spec["df"],
                how=spec["how"],
                left_on=spec["left_on"],
                right_on=spec["right_on"],
            )
        except KeyError as e:
            logging.error(f"Merge failed due to missing column: {e}")
            raise
    return base_df
