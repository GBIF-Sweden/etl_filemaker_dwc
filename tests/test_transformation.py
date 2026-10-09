import pandas as pd
import pytest

from transformation.transform import (
    clean_whitespace,
    clean_column_lifestage,
    clean_column_sex,
    convert_date_columns,
    merge_columns,
    pal_fix_synonyms,
    replace_values,
)


def test_pal_fix_synonyms():
    df = pd.DataFrame(
        {
            "catalogNumber": ["1", "1", "2"],
            "Species name": ["Sp1", None, "Sp2"],
            "Author": ["Auth1", "Auth2", None],
            "other": [1, 2, 3],
        }
    )
    # Expected:
    # Row 0: "Sp1, Auth1"
    # Row 1: "Auth2" (Species name is None)
    # Row 2: "Sp2" (Author is None)
    # Grouped by catalogNumber:
    # 1: "Sp1, Auth1 | Auth2"
    # 2: "Sp2"

    df_res = pal_fix_synonyms(df)

    assert len(df_res) == 2
    assert (
        df_res.loc[df_res["catalogNumber"] == "1", "taxonRemarks"].iloc[0]
        == "Sp1, Auth1 | Auth2"
    )
    assert df_res.loc[df_res["catalogNumber"] == "2", "taxonRemarks"].iloc[0] == "Sp2"


def test_clean_whitespace():
    df = pd.DataFrame({"A": ["  foo  ", "bar  baz", "  "], "B": [1, 2, 3]})
    df_res = clean_whitespace(df)

    assert df_res["A"].tolist() == ["foo", "bar baz", ""]
    assert df_res["B"].tolist() == [1, 2, 3]


def test_clean_whitespace_preserves_mixed_object_values():
    df = pd.DataFrame(
        {
            "A": pd.Series(["  foo  ", 7, None], dtype=object),
            "B": [1, 2, 3],
        }
    )
    df_res = clean_whitespace(df)

    assert df_res["A"].tolist() == ["foo", 7, None]
    assert df_res["B"].tolist() == [1, 2, 3]


def test_clean_column_sex():
    df = pd.DataFrame(
        {"sex": ["Male", "female", "0", "Unknown", "MALE", "Femle", ""]}
    )
    # MALE -> Male (fuzzy or exact if mapped?) "MALE" is not in mapping, but "Male" is. Fuzzy should catch it.
    # Femle -> Female (fuzzy)
    # 0 -> Unknown
    # "" -> "" (empty input remains empty)

    df_res = clean_column_sex(df)

    expected = ["Male", "Female", "Unknown", "Unknown", "Male", "Female", ""]
    # Note: "MALE" fuzzy match to "Male" (ratio 100 if case insensitive, but our fuzzy logic compares lower to lower keys?
    # Wait, clean_column_sex logic:
    # best_match = max(sex_mapping.keys(), key=lambda x: fuzz.ratio(sex_value.lower(), x.lower()))
    # "male" vs keys lower. "Male" key -> "male". Ratio 100.
    # So "MALE" -> "Male".

    assert df_res["sex_p"].tolist() == expected


def test_clean_column_lifestage():
    df = pd.DataFrame({"lifeStage": ["Adult", "juvenile", "Adut", "Unknown", ""]})
    # Adult -> adult
    # juvenile -> juvenile
    # Adut -> adult (fuzzy)
    # Unknown -> Unknown
    # "" -> ""

    df_res = clean_column_lifestage(df)

    expected = ["adult", "juvenile", "adult", "Unknown", ""]
    assert df_res["lifeStage"].tolist() == expected


def test_merge_columns():
    df = pd.DataFrame({
        "col1": ["Same", "SimilarString", "Different"],
        "col2": ["Same", "SimilarStrings", "Other"],
    })
    # Row 0: Same -> "Same" (Exact)
    # Row 1: SimilarString vs SimilarStrings -> Ratio high -> "SimilarStrings" (Second val)
    # Row 2: Different vs Other -> Ratio low -> "Different Other" (Concat)

    df_res = merge_columns(df, "col1", "col2", "merged")

    assert df_res["merged"].iloc[0] == "Same"
    # Check fuzzy match. "SimilarString" vs "SimilarStrings"
    # fuzz.ratio("SimilarString", "SimilarStrings") is likely > 80.
    # 13 chars vs 14 chars. 1 diff.
    assert df_res["merged"].iloc[1] == "SimilarStrings"
    assert df_res["merged"].iloc[2] == "Different Other"


def test_move_entities_to_column():
    df = pd.DataFrame(
        {"country": ["Sweden", "Africa", "Norway", "Asia"], "continent": ["", "", "", ""]}
    )
    from transformation.transform import move_entities_to_column

    entities = ["Africa", "Asia"]
    df_res = move_entities_to_column(df, "country", "continent", entities)

    assert df_res.loc[0, "country"] == "Sweden"
    assert df_res.loc[0, "continent"] == ""

    assert df_res.loc[1, "country"] == ""
    assert df_res.loc[1, "continent"] == "Africa"

    assert df_res.loc[3, "country"] == ""
    assert df_res.loc[3, "continent"] == "Asia"


def test_filter_by_string_match():
    df = pd.DataFrame({"col": ["foo", "bar", "bazfoo"]})
    from transformation.transform import filter_by_string_match

    # Test keep_matches=True (select)
    df_sel = filter_by_string_match(df, "col", "foo", keep_matches=True)
    assert len(df_sel) == 2
    assert "foo" in df_sel["col"].values
    assert "bazfoo" in df_sel["col"].values

    # Test keep_matches=False (drop)
    df_drop = filter_by_string_match(df, "col", "foo", keep_matches=False)
    assert len(df_drop) == 1
    assert df_drop["col"].iloc[0] == "bar"


def test_replace_values_raises_for_missing_column():
    df = pd.DataFrame({"col": ["foo"]})

    with pytest.raises(ValueError, match="does not exist"):
        replace_values(df, "missing", "foo")


def test_convert_date_columns_skips_missing_column():
    df = pd.DataFrame({"createdDate": ["2024-01-01"]})

    df_res = convert_date_columns(df, "missing")

    assert df_res.equals(df)


def test_sos_diffusion_matches_production_and_diagnostic_modes():
    from transformation.sensitive_species import (
        calculate_coordinate_diffusion_stats,
        create_diffused_coordinate_info,
        diffuse_coordinates,
    )

    production = diffuse_coordinates(59.3293, 18.0686, protection_level=3)
    # DiffusionManager uses the SOS offset, not the cell centre.
    assert production["diffused_sweref99tm"][0] % 5_000 == 2_505
    assert production["diffused_sweref99tm"][1] % 5_000 == 2_505

    diagnostic = create_diffused_coordinate_info(
        59.3293, 18.0686, protection_level=3, diffusion_coordinate_system="sweref99_tm"
    )
    # CoordinateDiffusionManager's alternate SWEREF diagnostic mode uses a
    # cell centre, so it intentionally produces a different coordinate.
    assert diagnostic["diffusedPointSweref99Tm"][0] % 5_000 == 2_500
    assert diagnostic["diffusedPointSweref99Tm"][1] % 5_000 == 2_500

    stats = calculate_coordinate_diffusion_stats(sample_size=2, random_seed=1)
    assert set(stats) == {2, 3, 4, 5}


def test_sds_diffusion_sos_derives_levels_from_restricted_species_csv(tmp_path):
    from transformation.sensitive_species import sds_diffusion_sos

    rules_path = tmp_path / "restricted-species.csv"
    rules_path.write_text(
        "scientificName,taxonID,generalisation\n"
        "Test species,123,5km\n"
        "Test species aggregate,124,25km\n",
        encoding="utf-8",
    )
    df = pd.DataFrame(
        {
            "scientificName": ["Test species", "Not sensitive"],
            "decimalLatitude": [59.3690455799197, 59.3690455799197],
            "decimalLongitude": [18.0545359628885, 18.0545359628885],
        }
    )
    result = sds_diffusion_sos(
        df,
        rules_path=rules_path,
        generalisation_to_protection_level={"5km": 3, "25km": 4},
    )
    assert result.at[0, "sensitivityCategory"] == 3
    assert result.at[0, "diffusionStatus"] == "DiffusedBySystem"
    assert result.at[0, "decimalLongitude"] != 18.0545359628885
    assert pd.isna(result.at[1, "sensitivityCategory"])
    assert result.at[1, "decimalLongitude"] == 18.0545359628885


def test_sds_generalization_ala_applies_zone_and_withhold_rules(tmp_path):
    from transformation.sensitive_species import sds_generalization_ala
    from transformation.transform import apply_transformations

    xml_path = tmp_path / "sensitive-species-data.xml"
    xml_path.write_text(
        """<sensitiveSpeciesList>
        <sensitiveSpecies name="Test species" guid="123">
          <instances>
            <conservationInstance generalisation="5km" zone="Sweden" dataResourceId="dr1" />
            <conservationInstance generalisation="WITHHOLD" zone="Sweden" dataResourceId="dr2" />
          </instances>
        </sensitiveSpecies>
        </sensitiveSpeciesList>""",
        encoding="utf-8",
    )
    df = pd.DataFrame(
        {
            "taxonId": ["123", "123", "123"],
            "dataResourceId": ["dr1", "dr2", "dr1"],
            "zone": ["Sweden", "Sweden", "Norway"],
            "decimalLatitude": [-37.2234, -37.2234, -37.2234],
            "decimalLongitude": [145.786, 145.786, 145.786],
        }
    )
    result = sds_generalization_ala(df, xml_path)
    assert (result.at[0, "decimalLatitude"], result.at[0, "decimalLongitude"]) == (
        "-37.2",
        "145.8",
    )
    assert result.at[1, "decimalLatitude"] is None
    assert result.at[1, "informationWithheld"] != ""
    assert result.at[2, "decimalLatitude"] == -37.2234

    dispatched = apply_transformations(
        df,
        {"transformations": [{"function": "sds_generalization_ala", "params": {"xml_path": xml_path}}]},
    )
    assert dispatched.at[0, "decimalLatitude"] == "-37.2"


def test_sds_generalization_ala_preserves_sds_coordinate_precision():
    from transformation.sensitive_species import sds_generalise_coordinates

    latitude, longitude = 59.3690455799197, 18.0545359628885
    assert sds_generalise_coordinates(latitude, longitude, "5km") == (
        "59.4",
        "18.0",
    )
    assert sds_generalise_coordinates(latitude, longitude, "25km") == (
        "59",
        "18",
    )


def test_sds_generalization_gbif_applies_governed_decimal_grid_policy():
    from transformation.sensitive_species import sds_generalization_gbif
    from transformation.transform import apply_transformations

    rules = {
        "example species": {
            "scientificName": "Example species",
            "category": "high",
            "reason": "Collection risk",
            "reviewDate": "2099-01-01",
            "originalCoordinatePrecision": "10 m",
        },
        "extreme species": {
            "scientificName": "Extreme species",
            "category": "extreme",
            "reason": "Severe collection risk",
            "reviewDate": "2099-01-01",
            "originalCoordinatePrecision": "10 m",
        },
        "not sensitive species": {
            "scientificName": "Not sensitive species",
            "category": "not_sensitive",
            "reason": "No sensitivity restriction",
            "reviewDate": "2099-01-01",
            "originalCoordinatePrecision": "10 m",
        },
    }
    df = pd.DataFrame(
        {
            "scientificName": [
                "Example species",
                "Extreme species",
                "Not sensitive species",
                "Unknown species",
            ],
            "decimalLatitude": [59.3293, 59.3293, 59.3293, 59.3293],
            "decimalLongitude": [18.0686, 18.0686, 18.0686, 18.0686],
            "coordinateUncertaintyInMeters": [10, 10, 10, 10],
        }
    )
    result = sds_generalization_gbif(df, rules=rules)
    assert (result.at[0, "decimalLatitude"], result.at[0, "decimalLongitude"]) == (59.3, 18.1)
    assert result.at[0, "coordinatePrecision"] == 0.1
    assert result.at[0, "coordinateUncertaintyInMeters"] > 10
    assert pd.isna(result.at[1, "decimalLatitude"])
    assert result.at[1, "sensitivityCategory"] == "extreme"
    assert result.at[2, "decimalLatitude"] == 59.3293
    assert result.at[2, "decimalLongitude"] == 18.0686
    assert result.at[2, "coordinateUncertaintyInMeters"] == 10
    assert not result.at[2, "sensitive"]
    assert result.at[2, "sensitivityCategory"] == "not_sensitive"
    assert result.at[2, "dataGeneralizations"] == ""
    assert result.at[3, "decimalLatitude"] == 59.3293
    assert result.at[3, "decimalLongitude"] == 18.0686
    assert result.at[3, "coordinateUncertaintyInMeters"] == 10
    assert not result.at[3, "sensitive"]
    assert result.at[3, "sensitivityCategory"] == ""
    assert result.at[3, "dataGeneralizations"] == ""
    assert result.at[3, "informationWithheld"] == ""

    dispatched = apply_transformations(
        df,
        {
            "transformations": [
                {"function": "sds_generalization_gbif", "params": {"rules": rules}}
            ]
        },
    )
    assert dispatched.at[0, "decimalLatitude"] == 59.3
