"""General fixtures, available to the tests of every app."""

import pytest


@pytest.fixture
def import_dir(tmp_path, settings):
    """Temporary import folder: the load commands read the CSV files from here."""
    settings.IMPORT_DIR = tmp_path
    return tmp_path
