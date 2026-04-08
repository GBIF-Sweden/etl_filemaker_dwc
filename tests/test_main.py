from unittest.mock import MagicMock

import pandas as pd
import pytest

import main


def test_requires_db_config_false_when_no_source_writes_to_db():
    config = {
        "dataset": "example",
        "occurrence": {"load": {"write_to_db": False}},
        "multimedia": {"load": {"write_to_file": True}},
        "merges": [],
    }

    assert main.requires_db_config(config) is False


def test_requires_db_config_true_when_any_source_writes_to_db():
    config = {
        "dataset": "example",
        "occurrence": {"load": {"write_to_db": False}},
        "multimedia": {"load": {"write_to_db": True}},
    }

    assert main.requires_db_config(config) is True


def test_main_allows_file_only_runs_without_db_credentials(monkeypatch: pytest.MonkeyPatch):
    config = {
        "dataset": "example",
        "occurrence": {
            "extract": {"srcFilePath": "/tmp/input.csv"},
            "mapping": {"id": "occurrenceID"},
            "load": {"write_to_db": False, "write_to_file": False, "write_to_dwca": False},
        }
    }

    handle_output_mock = MagicMock(side_effect=lambda df, *_args, **_kwargs: df)
    create_dwca_archive_mock = MagicMock()

    monkeypatch.setattr(main, "load_yaml_config", lambda _path: config)
    monkeypatch.setattr(main, "extract_from_csv", lambda _cfg: pd.DataFrame({"occurrenceID": ["1"]}))
    monkeypatch.setattr(main, "apply_transformations", lambda df, _cfg: df)
    monkeypatch.setattr(main, "merge_dataframes", lambda df, _merge_specs: df)
    monkeypatch.setattr(main, "handle_output", handle_output_mock)
    monkeypatch.setattr(main, "create_dwca_archive", create_dwca_archive_mock)
    monkeypatch.delenv("DB_USER", raising=False)
    monkeypatch.delenv("DB_PASSWORD", raising=False)

    main.main("config.yml")

    assert handle_output_mock.call_count == 2
    assert handle_output_mock.call_args_list[0].args[2] == {}
    create_dwca_archive_mock.assert_called_once()


def test_main_requires_db_credentials_when_db_write_enabled(monkeypatch: pytest.MonkeyPatch):
    config = {
        "dataset": "example",
        "occurrence": {
            "extract": {"srcFilePath": "/tmp/input.csv"},
            "mapping": {"id": "occurrenceID"},
            "load": {"write_to_db": True, "write_to_file": False, "write_to_dwca": False},
        }
    }

    monkeypatch.setattr(main, "load_yaml_config", lambda _path: config)
    monkeypatch.delenv("DB_USER", raising=False)
    monkeypatch.delenv("DB_PASSWORD", raising=False)

    with pytest.raises(ValueError, match="DB_USER and DB_PASSWORD"):
        main.get_db_config()


def test_main_reraises_failures(monkeypatch: pytest.MonkeyPatch):
    config = {
        "dataset": "example",
        "occurrence": {
            "extract": {"srcFilePath": "/tmp/input.csv"},
            "mapping": {"id": "occurrenceID"},
            "load": {"write_to_db": False, "write_to_file": False, "write_to_dwca": False},
        }
    }

    monkeypatch.setattr(main, "load_yaml_config", lambda _path: config)
    monkeypatch.setattr(main, "extract_from_csv", lambda _cfg: pd.DataFrame({"occurrenceID": ["1"]}))
    monkeypatch.setattr(main, "apply_transformations", lambda df, _cfg: df)
    monkeypatch.setattr(main, "merge_dataframes", lambda df, _merge_specs: df)
    monkeypatch.setattr(
        main,
        "handle_output",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("load failed")),
    )

    with pytest.raises(RuntimeError, match="load failed"):
        main.main("config.yml")
