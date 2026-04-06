# ETL FileMaker to Darwin Core

A robust, configuration-driven ETL (Extract, Transform, Load) pipeline for converting FileMaker CSV exports to Darwin Core Archive (DwC-A) format for biodiversity data publishing.

## Features

- **Configuration-Driven**: YAML-based configuration for flexible data mapping and transformations
- **Modular Architecture**: Clean separation of extraction, transformation, and loading logic
- **Pure Functions**: Transformation functions are side-effect free and fully tested
- **Vectorized Operations**: Optimized pandas operations for high performance
- **Darwin Core Compliance**: Generates valid DwC-A archives with occurrence and multimedia extensions
- **Database Integration**: Optional MySQL/MariaDB upsert support with configurable batch sizes
- **Comprehensive Logging**: Rotating file logs with detailed execution tracking
- **Docker Support**: Containerized deployment for reproducibility

## Project Structure

```
etl_filemaker_dwc/
├── config-files/          # YAML configuration files for different datasets
├── extraction/            # CSV extraction module
├── transformation/        # Data transformation functions
├── loading/              # Database and file output handlers
├── utils/                # Logging and utility functions
├── tests/                # Unit and integration tests
├── data/                 # Input data directory
├── output/               # DwC-A output directory
├── logs/                 # Application logs
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

**Local execution:**
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

### DwC-A Metadata Guidance

If `write_to_dwca: true`, the config must include a top-level `dwca_metadata` block.

- `dataset_name`, `description`, `citation`, `rights`, and `license` are required.
- These values are archive-level publication metadata, not transformation settings.
- They should be reviewed by the dataset owner or curator before publishing.
- Taxonomic group or collection names can often be inferred from the config, but official publication titles and citation text should not be assumed.

### Available Transformations

- `clean_whitespace` - Remove leading/trailing whitespace
- `generate_occ_id_triplet` - Create occurrenceID from institution:collection:catalog
- `drop_empty_rows` - Remove rows with null values in specified column
- `drop_duplicate_rows` - Remove duplicates based on primary key
- `create_date` - Generate ISO date from year/month/day columns
- `merge_columns` - Merge columns with fuzzy matching
- `clean_column_sex` - Standardize sex values
- `clean_column_lifestage` - Standardize life stage values
- `pal_move_continents` - Move continent values to correct column
- `pal_move_oceans` - Move ocean values to correct column
- And many more...

## Testing

Run the test suite:

```bash
pytest
```

Run with coverage:

```bash
pytest --cov=. --cov-report=html
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

1. Add function to `transformation/transform.py`
2. Register in `TRANSFORMATION_DISPATCHER`
3. Add tests to `tests/test_transformation.py`
4. Update configuration YAML files

## Troubleshooting

### Common Issues

**Missing Files**: If a source file is missing, the ETL will log a warning and continue processing other sources.

**Database Connection**: Ensure `.env` file contains valid `DB_USER` and `DB_PASSWORD`.

**DwC-A Metadata**: If `write_to_dwca: true`, the config must include a top-level `dwca_metadata` block with dataset metadata.

**Memory Issues**: For large datasets, increase batch size or process in chunks.

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
