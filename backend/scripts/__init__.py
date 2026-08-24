"""Operator entry points: metadata import, calendar validation, market-data validation.

These are scripts, not library code. Each bootstraps ``sys.path`` so it can be run directly
from ``backend/`` with ``uv run python scripts/<name>.py``; the package marker exists so the
type checker resolves ``scripts.data_sources.*`` to one module path rather than two.
"""
