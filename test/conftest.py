import pytest
from src.bible_json import Bible
from src.bible_json.enums import BibleVersions


@pytest.fixture()
def bible():
    return Bible.new(BibleVersions.EnKjv)
