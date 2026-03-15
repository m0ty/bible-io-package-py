from typing import Union
from bible_io_references import BibleBookEnum


BookRef = Union[int, BibleBookEnum]


class BibleError(Exception):
    """Base exception for all Bible-related errors."""


def _format_book(book: BookRef) -> str:
    """Convert a book reference to a human-friendly string.

    Args:
        book (BookRef): Either an integer index or a ``BibleBookEnum`` member.

    Returns:
        str: The display name for the book reference.
    """

    if isinstance(book, BibleBookEnum):
        return book.full_name
    return str(book)


class BookNotFoundError(BibleError):
    """Raised when the requested book is out of range."""

    def __init__(self, book: BookRef):
        """Initialize the error with the missing book reference.

        Args:
            book (BookRef): Identifier for the missing book.

        Returns:
            None: The exception is configured with the formatted message.
        """

        super().__init__(f"Book {_format_book(book)} is out of range.")


class ChapterNotFoundError(BibleError):
    """Raised when the requested chapter number is out of range."""

    def __init__(self, book: BookRef, chapter_number: int):
        """Initialize the error with the missing chapter details.

        Args:
            book (BookRef): Identifier for the related book.
            chapter_number (int): Chapter number that was requested.

        Returns:
            None: The exception message is prepared for display.
        """

        super().__init__(
            f"Chapter {chapter_number} in book {_format_book(book)} is out of range."
        )


class VerseNotFoundError(BibleError):
    """Raised when the requested verse number is out of range."""

    def __init__(self, book: BookRef, chapter_number: int, verse_number: int):
        """Initialize the error with the missing verse details.

        Args:
            book (BookRef): Identifier for the related book.
            chapter_number (int): Chapter containing the verse.
            verse_number (int): Verse number that was requested.

        Returns:
            None: The exception message is prepared for display.
        """

        super().__init__(
            "Verse "
            f"{verse_number} in book {_format_book(book)}, "
            f"chapter {chapter_number} is out of range."
        )
