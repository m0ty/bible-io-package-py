import pytest

from bible_io import BibleBookEnum
from bible_io.errors import BookNotFoundError


def test_books_negative(bible):
    with pytest.raises(BookNotFoundError):
        bible.get_book(-1)

def test_books(bible):
    bible_books = bible.books

    assert len(bible_books) == 66

def test_specific_book(bible):

    genesis = bible.get_book(BibleBookEnum.Genesis)

    assert genesis.book_enum is BibleBookEnum.Genesis
    assert genesis.name == "Genesis"
