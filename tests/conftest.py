"""Pytest configuration for the offline unit-test suite.

Makes the repository root importable so ``pytest tests/`` works from any
working directory without installing the package first.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
