from unittest.mock import MagicMock

import pandas as pd
import pytest
from sqlalchemy.exc import SQLAlchemyError

from loading.load import create_dwca_archive, upsert_dataframe_in_batches


def test_upsert_dataframe_in_batches_reraises_sqlalchemy_errors(monkeypatch: pytest.MonkeyPatch):
    df = pd.DataFrame({"occurrenceID": ["1"]})
    load_config = {
        "database_hostname": "localhost",
        "database_port": "3306",
        "database_name": "db",
        "database_table": "table_name",
        "database_table_pk_column": "occurrenceID",
    }
    db_config = {"database_user": "user", "database_password": "password"}

    monkeypatch.setattr(
        "loading.load.create_engine",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(SQLAlchemyError("db down")),
    )

    with pytest.raises(SQLAlchemyError, match="db down"):
        upsert_dataframe_in_batches(df, load_config, db_config)


def test_create_dwca_archive_requires_metadata(tmp_path, monkeypatch: pytest.MonkeyPatch):
    core_df = pd.DataFrame({"occurrenceID": ["1"]})
    multimedia_df = pd.DataFrame(columns=["occurrenceID", "identifier"])
    load_config = {"write_to_dwca": True, "dwcaPath": str(tmp_path / "archive.zip")}

    create_dwca_mock = MagicMock()
    monkeypatch.setattr("loading.load.DwcaHandler.create_dwca", create_dwca_mock)

    with pytest.raises(ValueError, match="missing required dwca_metadata fields"):
        create_dwca_archive(core_df, multimedia_df, load_config, {})

    create_dwca_mock.assert_not_called()


def test_create_dwca_archive_uses_config_metadata(tmp_path, monkeypatch: pytest.MonkeyPatch):
    core_df = pd.DataFrame({"occurrenceID": ["1"]})
    multimedia_df = pd.DataFrame(columns=["occurrenceID", "identifier"])
    load_config = {"write_to_dwca": True, "dwcaPath": str(tmp_path / "archive.zip")}
    metadata_config = {
        "dataset_name": "Configured Dataset",
        "description": "Configured description",
        "citation": "Configured citation",
        "rights": "Configured rights",
        "license": "https://creativecommons.org/licenses/by/4.0/",
    }

    eml_mock = MagicMock(name="eml")
    create_dwca_mock = MagicMock()
    monkeypatch.setattr("loading.load.Eml", MagicMock(return_value=eml_mock))
    monkeypatch.setattr("loading.load.DwcaHandler.create_dwca", create_dwca_mock)

    create_dwca_archive(core_df, multimedia_df, load_config, metadata_config)

    loading_eml = getattr(__import__("loading.load", fromlist=["Eml"]), "Eml")
    loading_eml.assert_called_once_with(
        dataset_name="Configured Dataset",
        description="Configured description",
        license="https://creativecommons.org/licenses/by/4.0/",
        citation="Configured citation",
        rights="Configured rights",
    )
    create_dwca_mock.assert_called_once()


def test_handle_output_writes_configured_file(tmp_path):
    from loading.load import handle_output

    df = pd.DataFrame({"occurrenceID": ["1"], "scientificName": ["Example"]})
    output_path = tmp_path / "occurrence.tsv"
    load_config = {
        "write_to_file": True,
        "write_to_db": False,
        "delimiter": "\t",
        "targetFilePath": str(output_path),
    }

    result = handle_output(df, load_config, db_config={}, source_name="occurrence")

    assert result.equals(df)
    assert output_path.exists()
    assert "occurrenceID\tscientificName" in output_path.read_text(encoding="utf-8")


def test_upsert_dataframe_in_batches_deduplicates_and_uses_upsert(monkeypatch: pytest.MonkeyPatch):
    import loading.load as load_module

    df = pd.DataFrame(
        {
            "occurrenceID": ["1", "1", "2"],
            "scientificName": ["Alpha", "Beta", "Gamma"],
            "ignored": ["x", "y", "z"],
        }
    )
    load_config = {
        "database_hostname": "localhost",
        "database_port": "3306",
        "database_name": "db",
        "database_table": "table_name",
        "database_table_pk_column": "occurrenceID",
    }
    db_config = {"database_user": "user", "database_password": "password"}

    class FakeColumn:
        def __init__(self, name):
            self.name = name

    class FakeTable:
        def __init__(self):
            self.c = [FakeColumn("occurrenceID"), FakeColumn("scientificName")]
            self.columns = self.c

    class FakeResult:
        rowcount = 1

        def fetchall(self):
            return []

    class FakeSession:
        def __init__(self):
            self.executed = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, stmt):
            self.executed.append(stmt)
            return FakeResult()

        def commit(self):
            return None

        def rollback(self):
            return None

    class FakeInsert:
        def __init__(self, table):
            self.table = table
            self.records = None
            self.on_duplicate = None
            self.prefix = None
            self.inserted = {"occurrenceID": "new.occurrenceID", "scientificName": "new.scientificName"}

        def values(self, records):
            self.records = records
            return self

        def on_duplicate_key_update(self, **kwargs):
            self.on_duplicate = kwargs
            return self

        def prefix_with(self, prefix):
            self.prefix = prefix
            return self

    fake_sessions = []
    fake_insert = None

    monkeypatch.setattr(load_module, "create_engine", lambda *_args, **_kwargs: MagicMock(dispose=lambda: None))
    monkeypatch.setattr(load_module, "Table", lambda *_args, **_kwargs: FakeTable())
    monkeypatch.setattr(
        load_module,
        "sessionmaker",
        lambda **_kwargs: (lambda: fake_sessions.append(FakeSession()) or fake_sessions[-1]),
    )

    def fake_insert_factory(table):
        nonlocal fake_insert
        fake_insert = FakeInsert(table)
        return fake_insert

    monkeypatch.setattr(load_module, "insert", fake_insert_factory)

    upsert_dataframe_in_batches(df, load_config, db_config, batch_size=1000)

    assert fake_insert is not None
    assert len(fake_sessions) == 1
    assert len(fake_sessions[0].executed) == 2
    assert len(fake_insert.records) == 2
    assert fake_insert.on_duplicate is not None
    assert "scientificName" in fake_insert.on_duplicate
