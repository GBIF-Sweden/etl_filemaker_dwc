import logging

import pandas as pd
from fuzzywuzzy import fuzz


def generate_occ_id_triplet(df: pd.DataFrame, collection_code_column: str = 'collectionCode') -> pd.DataFrame:
    """Generates occurrenceID from institutionCode, collectionCode, and catalogNumber."""
    df = df.copy()
    try:
        required_cols = ["institutionCode", collection_code_column, "catalogNumber"]
        if not all(col in df.columns for col in required_cols):
            missing = [col for col in required_cols if col not in df.columns]
            raise KeyError(
                f"Missing required columns for occurrenceID generation: {missing}"
            )

        df["occurrenceID"] = (
            df["institutionCode"]
            .astype(str)
            .str.cat(
                [df[collection_code_column].astype(str), df["catalogNumber"].astype(str)],
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


def generate_index_id(df: pd.DataFrame) -> pd.DataFrame:
    """Generates id for index from indexIdPrefix and catalogNumber."""
    df = df.copy()
    try:
        required_cols = ["indexIdPrefix", "catalogNumber"]
        if not all(col in df.columns for col in required_cols):
            missing = [col for col in required_cols if col not in df.columns]
            raise KeyError(
                f"Missing required columns for index id generation: {missing}"
            )

        df["id"] = (
            df["indexIdPrefix"].astype(str)
            .str.cat(
                [df["catalogNumber"].astype(str)],
                sep="_",
            )
        )

        cols = ["id"] + [col for col in df.columns if col != "id"]
        df = df[cols]
        logging.info("Successfully generated 'id' column.")
        return df
    except Exception as e:
        logging.exception(f"An error occurred in generate_index_id: {e}")
        raise


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


def clean_column_lifestage(df: pd.DataFrame, lifestage_mapping: dict = None) -> pd.DataFrame:
    """Cleans the 'lifeStage' column and standardizes values in place."""
    df = df.copy()

    if lifestage_mapping is None:
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


def add_taxon_rank(df: pd.DataFrame, taxon_rank_column: str = "taxonRank") -> pd.DataFrame:
    """Adds a taxon rank column based on the presence of taxonomic columns."""
    df = df.copy()
    taxonomic_columns = [
        "species",
        "genus",
        "family",
        "order",
        "clazz",
        "phylum",
        "kingdom",
    ]

    df[taxon_rank_column] = ""
    for column in taxonomic_columns:
        has_value = df[column].notna() & df[column].astype(str).str.strip().ne("")
        df.loc[has_value & df[taxon_rank_column].eq(""), taxon_rank_column] = column.capitalize()

    logging.info(f"Added '{taxon_rank_column}' column.")

    return df
