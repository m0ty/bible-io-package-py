from typing import Union

from .bible_book_enums import BibleBookEnum


BookRef = Union[int, BibleBookEnum]


class BibleError(Exception):
    """Base exception for all Bible-related errors."""


def _format_book(book: BookRef) -> str:
    if isinstance(book, BibleBookEnum):
        return book.full_name
    return str(book)


class BookNotFoundError(BibleError):
    """Raised when the requested book is out of range."""

    def __init__(self, book: BookRef):
        super().__init__(f"Book {_format_book(book)} is out of range.")


class ChapterNotFoundError(BibleError):
    """Raised when the requested chapter number is out of range."""

    def __init__(self, book: BookRef, chapter_number: int):
        super().__init__(
            f"Chapter {chapter_number} in book {_format_book(book)} is out of range."
        )


class VerseNotFoundError(BibleError):
    """Raised when the requested verse number is out of range."""

    def __init__(self, book: BookRef, chapter_number: int, verse_number: int):
        super().__init__(
            "Verse "
            f"{verse_number} in book {_format_book(book)}, "
            f"chapter {chapter_number} is out of range."
        )
