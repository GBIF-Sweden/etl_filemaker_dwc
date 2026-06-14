import json
import yaml
import logging
from pathlib import Path
from typing import Any, Dict


def _load_file(path: str, loader):
    file_path = Path(path)
    with file_path.open("r", encoding="utf-8") as file:
        return loader(file)


def load_json_config(config_path):
    try:
        return _load_file(config_path, json.load)
    except FileNotFoundError:
        logging.exception(f"Error: Configuration file not found at {config_path}.")
        raise
    except json.JSONDecodeError:
        logging.exception("Error: Failed to decode JSON from the configuration file.")
        raise


def load_yaml_config(config_path):
    try:
        return _load_file(config_path, yaml.safe_load)
    except FileNotFoundError:
        logging.exception(f"Error: Configuration file not found at {config_path}.")
        raise
    except yaml.YAMLError:
        logging.exception("Error: Failed to parse YAML from the configuration file.")
        raise


def validate_pipeline_config(config: Dict[str, Any]) -> None:
    """
    Validate the structure required by the ETL runner.

    The goal is to fail fast before any extraction or load work starts.
    """
    if not isinstance(config, dict):
        raise ValueError("Configuration must be a mapping.")

    if not config.get("dataset"):
        raise ValueError("Configuration must define a top-level 'dataset' value.")

    source_keys = [
        key
        for key, value in config.items()
        if isinstance(value, dict) and ("extract" in value or "mapping" in value or "load" in value)
    ]
    if "occurrence" not in source_keys:
        raise ValueError("Configuration must define an 'occurrence' source.")

    for source_name in source_keys:
        source_cfg = config[source_name]
        extract_cfg = source_cfg.get("extract")
        if extract_cfg is not None and not extract_cfg.get("srcFilePath"):
            raise ValueError(
                f"Source '{source_name}' must define extract.srcFilePath."
            )

        load_cfg = source_cfg.get("load", {})
        if load_cfg.get("write_to_db"):
            required_db_fields = [
                "database_hostname",
                "database_port",
                "database_name",
                "database_table",
                "database_table_pk_column",
            ]
            missing = [field for field in required_db_fields if not load_cfg.get(field)]
            if missing:
                raise ValueError(
                    f"Source '{source_name}' is configured for database output but is missing: "
                    + ", ".join(missing)
                )

        if load_cfg.get("write_to_dwca"):
            missing_metadata = []
            metadata = config.get("dwca_metadata", {})
            for field in ("dataset_name", "description", "citation", "rights", "license"):
                if not metadata.get(field):
                    missing_metadata.append(field)
            if missing_metadata:
                raise ValueError(
                    "DwC-A output is enabled but dwca_metadata is missing: "
                    + ", ".join(missing_metadata)
                )
            if not load_cfg.get("dwcaPath"):
                raise ValueError(
                    f"Source '{source_name}' is configured for DwC-A output but is missing load.dwcaPath."
                )
