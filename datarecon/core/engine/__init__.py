# datarecon/core/engine/__init__.py  (NEW — package export for the comparison engine)
from .comparison_engine import (
    ComparisonConfig,
    ComparisonEngine,
    ComparisonEngineError,
    ComparisonResult,
    DuplicateBusinessKeyError,
    SchemaAlignmentError,
)

__all__ = [
    "ComparisonConfig",
    "ComparisonEngine",
    "ComparisonEngineError",
    "ComparisonResult",
    "DuplicateBusinessKeyError",
    "SchemaAlignmentError",
]
