import logging
import os
from logging.handlers import RotatingFileHandler


def configure_logging(
    log_level: int = logging.INFO,
    log_dir: str = "logs",
    log_filename: str = "app.log",
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB
    backup_count: int = 5,
):
    """
    Configures a robust logging setup for the application.

    This function sets up the root logger to output messages to both the console
    and a rotating log file. It avoids the limitations of `logging.basicConfig`.

    Args:
        log_level: The minimum logging level to capture (e.g., logging.INFO).
        log_dir: The directory where log files will be stored.
        log_filename: The name of the log file.
        log_format: The format string for log messages.
        max_bytes: The maximum size of a log file before it is rotated.
        backup_count: The number of old log files to keep.
    """
    # 1. Ensure the log directory exists
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError as e:
        logging.error(f"Error creating log directory {log_dir}: {e}")
        # Fallback to a simple console logger if directory creation fails
        logging.basicConfig(level=log_level, format=log_format)
        return

    log_file_path = os.path.join(log_dir, log_filename)

    # 2. Get the root logger and set its level
    # This is more robust than logging.basicConfig()
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # 3. Clear any existing handlers to prevent duplicate logs
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # 4. Create a shared formatter
    formatter = logging.Formatter(log_format)

    # 5. Create and add a console handler (for printing to the terminal)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 6. Create and add a rotating file handler (for writing to a file)
    try:
        file_handler = RotatingFileHandler(
            log_file_path, maxBytes=max_bytes, backupCount=backup_count
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except (IOError, OSError) as e:
        logging.error(f"Error setting up file handler at {log_file_path}: {e}")
        logging.warning("Logging to file is disabled.")

    logging.info("Logging has been configured successfully.")
