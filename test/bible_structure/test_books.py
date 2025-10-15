import pytest

from bible_io import BibleBookEnum
from bible_io.errors import BookNotFoundError


def test_books_negative(bible):
    with pytest.raises(BookNotFoundError):
        bible.get_book(-1)

def test_books(bible):
    bible_books = bible.books

    print(f"Total books: {len(bible_books)}")

def test_specific_book(bible):

    genesis = bible.get_book(BibleBookEnum.Genesis)

    print(genesis)
