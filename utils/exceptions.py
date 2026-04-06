"""Custom exceptions for the ETL application."""


class EtlError(Exception):
    """Base class for exceptions in this application."""

    pass


class DataExtractionError(EtlError):
    """Raised for errors during the data extraction phase."""

    pass


class DataTransformationError(EtlError):
    """Raised for errors during the data transformation phase."""

    pass


class DataLoadingError(EtlError):
    """Raised for errors during the data loading phase."""

    pass
