"""Fixtures generales, disponibles para los tests de todas las apps."""

import pytest


@pytest.fixture
def import_dir(tmp_path, settings):
    """Carpeta de importación temporal: los comandos de carga leen los CSV de acá."""
    settings.IMPORT_DIR = tmp_path
    return tmp_path
