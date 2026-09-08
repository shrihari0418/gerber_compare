"""Reusable, geometry-first Gerber comparison core."""
from .core import ComparisonConfig, ComparisonResult, compare_gerbers

__version__ = "0.1.0"

__all__ = ["ComparisonConfig", "ComparisonResult", "compare_gerbers", "__version__"]
