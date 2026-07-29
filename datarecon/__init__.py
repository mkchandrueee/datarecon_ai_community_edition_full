"""DataRecon AI — core comparison engine package (framework-agnostic)."""

from .core.engine import (
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
