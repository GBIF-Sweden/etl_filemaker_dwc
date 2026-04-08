import logging
from logging.handlers import RotatingFileHandler

import pytest

from utils.logging_utils import configure_logging


def test_configure_logging_creates_console_and_file_handlers(tmp_path):
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)

    try:
        configure_logging(log_dir=str(tmp_path), log_filename="test.log")

        assert len(root_logger.handlers) == 2
        assert any(isinstance(handler, RotatingFileHandler) for handler in root_logger.handlers)
    finally:
        for handler in root_logger.handlers:
            handler.close()
        root_logger.handlers.clear()
        for handler in original_handlers:
            root_logger.addHandler(handler)


def test_configure_logging_falls_back_when_log_dir_creation_fails(monkeypatch: pytest.MonkeyPatch):
    basic_config_calls = []

    monkeypatch.setattr(
        "utils.logging_utils.os.makedirs",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("mkdir failed")),
    )
    monkeypatch.setattr(
        "utils.logging_utils.logging.basicConfig",
        lambda **kwargs: basic_config_calls.append(kwargs),
    )

    configure_logging(log_dir="unwritable")

    assert len(basic_config_calls) == 1
