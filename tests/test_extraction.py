# tests/test_extraction.py
import os
import tempfile
import pandas as pd
import pytest

from extraction.extract import extract_from_csv, ExtractionError


def create_csv(content: str) -> str:
    """Helper to create a temporary CSV file with given content and return its path."""
    fd, path = tempfile.mkstemp(suffix='.csv')
    os.close(fd)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return path


def test_extract_valid_csv():
    csv_content = "col1,col2\n1,2\n3,4\n"
    csv_path = create_csv(csv_content)
    config = {"srcFilePath": csv_path}
    df = extract_from_csv(config)
    assert isinstance(df, pd.DataFrame)
    assert df.shape == (2, 2)
    os.remove(csv_path)


def test_missing_src_path_raises():
    config = {}
    with pytest.raises(ExtractionError):
        extract_from_csv(config)


def test_nonexistent_file_raises():
    config = {"srcFilePath": "/nonexistent/path.csv"}
    with pytest.raises(ExtractionError):
        extract_from_csv(config)


def test_empty_csv_returns_empty_dataframe():
    csv_content = "col1,col2\n"
    csv_path = create_csv(csv_content)
    config = {"srcFilePath": csv_path}
    df = extract_from_csv(config)
    assert df.empty
    os.remove(csv_path)
