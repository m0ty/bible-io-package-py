import pytest
from bible_json.errors import BookNotFoundError


def test_chapters_negative(bible):
    with pytest.raises(BookNotFoundError):
        bible.get_book(-1)

