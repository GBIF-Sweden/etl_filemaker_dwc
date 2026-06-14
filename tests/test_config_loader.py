import json

import pytest
import yaml

from config.config_loader import load_json_config, load_yaml_config
from config.config_loader import validate_pipeline_config


def test_load_json_config_success(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"dataset": "example"}), encoding="utf-8")

    assert load_json_config(str(config_path)) == {"dataset": "example"}


def test_load_json_config_raises_for_invalid_json(tmp_path):
    config_path = tmp_path / "invalid.json"
    config_path.write_text("{invalid json}", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        load_json_config(str(config_path))


def test_load_yaml_config_success(tmp_path):
    config_path = tmp_path / "config.yml"
    config_path.write_text("dataset: example\n", encoding="utf-8")

    assert load_yaml_config(str(config_path)) == {"dataset": "example"}


def test_load_yaml_config_raises_for_invalid_yaml(tmp_path):
    config_path = tmp_path / "invalid.yml"
    config_path.write_text("dataset: [broken\n", encoding="utf-8")

    with pytest.raises(yaml.YAMLError):
        load_yaml_config(str(config_path))


def test_validate_pipeline_config_accepts_minimal_valid_config():
    config = {
        "dataset": "example",
        "occurrence": {
            "extract": {"srcFilePath": "/tmp/input.csv"},
            "load": {"write_to_file": False, "write_to_db": False, "write_to_dwca": False},
        },
    }

    validate_pipeline_config(config)


def test_validate_pipeline_config_rejects_missing_dataset():
    config = {
        "occurrence": {
            "extract": {"srcFilePath": "/tmp/input.csv"},
            "load": {"write_to_file": False, "write_to_db": False, "write_to_dwca": False},
        },
    }

    with pytest.raises(ValueError, match="top-level 'dataset'"):
        validate_pipeline_config(config)
