# ETL FileMaker to Darwin Core

A configuration-driven ETL pipeline for converting FileMaker CSV exports to
Darwin Core Archive (DwC-A) output for biodiversity data publishing.

## Features

- YAML-based configuration for each pipeline
- Separation of extraction, transformation, and loading logic
- Pure transformation functions with tests
- Darwin Core Archive generation with occurrence and multimedia output
- Optional MySQL/MariaDB upsert support
- Rotating file logging
- Docker support for reproducible runs

## Project Structure

```
etl_filemaker_dwc/
├── config-files/          # YAML configuration files for different datasets
├── extraction/            # CSV extraction module
├── transformation/        # Data transformation functions
├── loading/              # Database and file output handlers
├── utils/                # Logging and utility functions
├── tests/                # Unit and integration tests
├── data/                 # Runtime input symlink or mounted path
├── output/               # Runtime output symlink or mounted path
├── logs/                 # Runtime log symlink or mounted path
├── main.py               # ETL orchestration script
├── requirements.txt      # Python dependencies
├── Makefile             # Build and run commands
└── Dockerfile           # Container definition
```

## Quick Start

### Prerequisites

- Python 3.12+
- pip
- (Optional) Docker for containerized deployment

### Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd etl_filemaker_dwc
   ```

2. **Create virtual environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment**
   ```bash
   cp env.template .env
   # Edit .env with your database credentials
   ```

### Running the ETL

**Local execution in the virtualenv:**
```bash
make run-local CONFIG_FILE=config-files/algae.yml
```

**Direct Python execution:**
```bash
python main.py config-files/algae.yml
```

**Using Make:**
```bash
make run CONFIG_FILE=config-files/algae.yml
```

**Using Docker:**
```bash
make build
make run CONFIG_FILE=config-files/algae.yml
```

`make run` expects `.env`, `config-files/`, `data/`, `output/`, and `logs/` to
be available in the working tree. Use `env.template` as the local environment
template.

## Configuration

### YAML Configuration Structure

Each dataset requires a YAML configuration file with the following sections:

```yaml
dataset: dataset_name

dwca_metadata:
  dataset_name: "Dataset Name"
  description: "Archive-level dataset description"
  citation: "Preferred citation text"
  rights: "Usage rights statement"
  license: "https://creativecommons.org/licenses/by/4.0/"

occurrence:
  defaults:
    basisOfRecord: PreservedSpecimen
    institutionCode: S
  extract:
    delimiter: ;
    encoding: utf8
    srcFilePath: ./data/input.csv
  mapping:
    source_column: dwc_term
  transformations:
    - function: clean_whitespace
      params: {}
    - function: generate_occ_id_triplet
      params: {}
  load:
    targetFilePath: ./output/occurrence.csv
    write_to_file: true
    write_to_db: false
    write_to_dwca: true
    dwcaPath: ./output/archive.zip
    batch_size: 1000

multimedia:
  # Similar structure for multimedia extension

merges:
  - source: katalog
    left_on: katalogID
    right_on: katalogID
    how: left
```

### Included Pipelines

The migrated configs currently include:

- `config-files/afossil.yml`
- `config-files/pfossil.yml`
- `config-files/EVmain.yml`
- `config-files/EVtype.yml`
- `config-files/fish.yml`
- `config-files/herptiles.yml`
- `config-files/mammals.yml`
- `config-files/birds.yml`
- `config-files/fbo.yml`
- `config-files/algae.yml`
- `config-files/fungi.yml`
- `config-files/mosses.yml`
- `config-files/pollen.yml`

### DwC-A Metadata Guidance

If `write_to_dwca: true`, the config must include a top-level `dwca_metadata` block.

- `dataset_name`, `description`, `citation`, `rights`, and `license` are required.
- These values are archive-level publication metadata, not transformation settings.
- They should be reviewed by the dataset owner or curator before publishing.
- Taxonomic group or collection names can often be inferred from the config, but official publication titles and citation text should not be assumed.

### Available Transformations

The active transformation modules are:

- `transformation/generic.py`
- `transformation/domain_pal.py`
- `transformation/coordinates.py`
- `transformation/dates.py`

Common functions used by the current configs include:

- `clean_whitespace`
- `generate_occ_id_triplet`
- `drop_empty_rows`
- `drop_duplicate_rows`
- `create_date`
- `convert_date_columns`
- `generate_dms_coordinates_column`
- `select_matched_string`
- `drop_matched_string`
- `merge_columns`
- `clean_column_sex`
- `clean_column_lifestage`
- `pal_move_continents`
- `pal_move_oceans`
- `pal_fix_synonyms`

## Testing

Run the test suite through the Makefile:

```bash
make test
```

Run with coverage:

```bash
.venv/bin/python -m pytest --cov=. --cov-report=html
```

## Output

The ETL process generates:

1. **CSV Files**: Tab-delimited occurrence and multimedia files
2. **Darwin Core Archive**: ZIP file containing:
   - `occurrence.txt` - Core occurrence data
   - `multimedia.txt` - Multimedia extension (if applicable)
   - `meta.xml` - Archive metadata
   - `eml.xml` - Ecological Metadata Language document

## Performance

- **Batch Processing**: Configurable batch sizes for database operations (default: 1000 rows)
- **Vectorized Operations**: Pandas vectorization for efficient data transformation
- **Optimized Fuzzy Matching**: Unique-value caching for fuzzy string matching

## Development

### Code Quality

The project follows strict code quality standards:

- **Type Hints**: All functions use Python type annotations
- **Docstrings**: NumPy-style documentation
- **Linting**: Flake8 configuration in `.flake8`
- **Testing**: Comprehensive unit and integration tests
- **Purity**: Transformation functions are side-effect free

### Adding New Transformations

1. Add the function to the appropriate module, usually `transformation/generic.py`,
   `transformation/domain_pal.py`, `transformation/coordinates.py`, or
   `transformation/dates.py`.
2. Import and register it in `transformation/transform.py` if it should be
   callable from YAML.
3. Add or update tests in `tests/test_transformation.py`.
4. Update the relevant YAML config file.

## Troubleshooting

### Common Issues

**Missing Files**: If a source file is missing, the ETL will log a warning and continue processing other sources.

**Database Connection**: Ensure `.env` file contains valid `DB_USER` and `DB_PASSWORD`.

**DwC-A Metadata**: If `write_to_dwca: true`, the config must include a top-level `dwca_metadata` block with dataset metadata.

**Memory Issues**: For large datasets, increase batch size or process in chunks.

**Merge Key Errors**: If the ETL fails with a merge error such as `KeyError:
'art id'`, confirm the input CSV header exists after extraction and that the
merge keys in the config match the processed column names exactly.

**Mixed-Type Whitespace Cleanup**: `clean_whitespace` now preserves non-string
values inside object columns. If you see unexpected values in a transformed
column, inspect the source CSV types rather than assuming string cleanup failed.

### Logs

Check `logs/app.log` for detailed execution logs with timestamps and error traces.

## License

[Add your license information]

## Contributors

[Add contributor information]

## Acknowledgments

Built with:
- [pandas](https://pandas.pydata.org/) - Data manipulation
- [SQLAlchemy](https://www.sqlalchemy.org/) - Database ORM
- [dwcahandler](https://pypi.org/project/dwcahandler/) - Darwin Core Archive creation
- [fuzzywuzzy](https://github.com/seatgeek/fuzzywuzzy) - Fuzzy string matching
