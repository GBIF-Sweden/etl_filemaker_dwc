# Makefile for the Python ETL Application

# --- Configuration ---
# Use := for immediate variable assignment.
PROJECT_DIR := $(shell pwd)

# Docker image name and tag.
IMAGE_NAME := etl_filemaker_dwc
IMAGE_TAG  := 0.0.1

# Default configuration file path. Can be overridden from the command line.
# e.g., make run CONFIG_FILE=config-files/another_config.yml
CONFIG_FILE ?= config-files/algae.yml

# Prefer the project virtual environment when it exists, otherwise fall back to
# the active Python on PATH.
PYTHON ?= $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python; fi)

# --- Path Configuration ---
# Define data paths relative to the project directory for better portability.
# These can be overridden from the command line if needed.
# e.g., make run INPUT_DATA_DIR=/absolute/path/to/data
#INPUT_DATA_DIR  ?= /opt/filemaker-exports
#OUTPUT_DATA_DIR ?= /data/dwca-export
#OUTPUT_DATA_DIR ?= /data/logs
INPUT_DATA_DIR  ?= $(PROJECT_DIR)/data
OUTPUT_DATA_DIR ?= $(PROJECT_DIR)/output
LOGS_DIR ?= $(PROJECT_DIR)/logs

# Get the current user's ID and group ID to pass to Docker build.
# This ensures the user created inside the Docker image matches the host user,
# solving file permission issues with mounted volumes.
HOST_USER_ID := $(shell id -u)
HOST_GROUP_ID := $(shell id -g)

# --- Targets ---
# Phony targets are rules that don't represent actual files.
.PHONY: help install lint format test check build build-clean run run-local clean clean-data

# Default target: runs when you just type 'make'.
default: help

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "Targets:"
	@echo "  install    Install Python dependencies locally using pip."
	@echo "  lint       Run flake8 to lint the Python source code."
	@echo "  format     Automatically format the code using black."
	@echo "  test       Run the Python test suite."
	@echo "  check      Run tests and linting."
	@echo "  build      Build the Docker image for the application."
	@echo "  build-clean Build the Docker image without cache."
	@echo "  run        Run the ETL process using credentials from a .env file."
	@echo "             Example: make run [CONFIG_FILE=config-files/your_config.yml]"
	@echo "  run-local  Run the ETL process locally with Python."
	@echo "             Example: make run-local [CONFIG_FILE=config-files/your_config.yml]"
	@echo "  clean      Remove logs and Python cache artifacts."
	@echo "  clean-data Remove generated DwC-A archives and processed export files."

install:
	@echo "--> Installing dependencies from requirements.txt..."
	pip install -r requirements.txt

lint:
	@echo "--> Linting source code with flake8..."
	flake8 .

format:
	@echo "--> Formatting source code with black..."
	black .

test:
	@echo "--> Running Python test suite..."
	$(PYTHON) -m pytest

check: test lint

build:
	@echo "--> Building Docker image '$(IMAGE_NAME):$(IMAGE_TAG)'..."
	docker build \
		--build-arg USER_ID=$(HOST_USER_ID) \
		--build-arg GROUP_ID=$(HOST_GROUP_ID) \
		-t $(IMAGE_NAME):$(IMAGE_TAG) .

build-clean:
	@echo "--> Building Docker image '$(IMAGE_NAME):$(IMAGE_TAG)' without cache..."
	docker build \
		--no-cache \
		--build-arg USER_ID=$(HOST_USER_ID) \
		--build-arg GROUP_ID=$(HOST_GROUP_ID) \
		-t $(IMAGE_NAME):$(IMAGE_TAG) .

run-local:
	@echo "--> Running ETL locally with config file: $(CONFIG_FILE)"
	$(PYTHON) main.py $(CONFIG_FILE)

run:
	@echo "--> Running ETL container with config file: $(CONFIG_FILE)"
	@# Check if the .env file exists before trying to run.
	@if [ ! -f .env ]; then \
		echo "Error: .env file not found."; \
		echo "Please create a .env file with your DB_USER and DB_PASSWORD."; \
		echo "You can copy env.template to .env and fill it out."; \
		exit 1; \
	fi
	@# Ensure output directory exists on the host to avoid permission errors.
	mkdir -p $(OUTPUT_DATA_DIR)
	docker run --rm \
		--name "$(IMAGE_NAME)-container" \
		--env-file .env \
		-v "$(PROJECT_DIR)/config-files:/app/config-files" \
		-v "$(INPUT_DATA_DIR):/app/data" \
		-v "$(OUTPUT_DATA_DIR):/app/output" \
		-v "$(LOGS_DIR):/app/logs" \
		$(IMAGE_NAME):$(IMAGE_TAG) \
		$(CONFIG_FILE)

clean:
	@echo "--> Cleaning logs and Python cache artifacts..."
	rm -f logs/*
	@# Use find to safely remove __pycache__ directories and .pyc files
	find . -type d -name "__pycache__" -exec rm -r {} +
	find . -type f -name "*.pyc" -delete
	@echo "Cleanup complete."

clean-data:
	@echo "--> Cleaning generated data outputs..."
	rm -f output/*/*.zip
	rm -f data/*/processed/*.csv
	rm -f data/*/processed/*.txt
	@echo "Generated data cleanup complete."
