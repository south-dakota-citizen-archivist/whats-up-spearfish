"""
tests/conftest.py

Shared fixtures for the test suite.
"""

import pytest

import scrapers.base as _base_module


@pytest.fixture
def data_dir(tmp_path):
    """Redirect scrapers' DATA_DIR to a temp directory for the duration of a test."""
    original = _base_module.DATA_DIR
    _base_module.DATA_DIR = tmp_path
    yield tmp_path
    _base_module.DATA_DIR = original
