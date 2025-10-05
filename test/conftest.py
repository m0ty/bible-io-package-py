import pytest
from bible_io import Bible


@pytest.fixture()
def bible():
    return Bible.new("test/bible_versions/en_kjv.json")
