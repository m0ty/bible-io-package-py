from pathlib import Path

import pytest
from bible_io import Bible


@pytest.fixture()
def bible():
    data_path = Path(__file__).parent / "bible_versions" / "en_kjv.json"
    assert data_path.is_file(), f"Test data not found at {data_path}"
    return Bible(data_path)
