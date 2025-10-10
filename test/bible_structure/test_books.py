import pytest
from bible_io.errors import BookNotFoundError


def test_books_negative(bible):
    with pytest.raises(BookNotFoundError):
        bible.get_book(-1)
