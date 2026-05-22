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
