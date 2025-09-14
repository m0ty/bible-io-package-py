class BibleError(Exception):
    """Base exception for all Bible-related errors."""
    pass

class BookNotFoundError(BibleError):
    """Raised when the requested book number is out of range."""
    def __init__(self, book_number):
        super().__init__(f"Book number {book_number} is out of range.")

class ChapterNotFoundError(BibleError):
    """Raised when the requested chapter number is out of range."""
    def __init__(self, book_number, chapter_number):
        super().__init__(f"Chapter {chapter_number} in book {book_number} is out of range.")

class VerseNotFoundError(BibleError):
    """Raised when the requested verse number is out of range."""
    def __init__(self, book_number, chapter_number, verse_number):
        super().__init__(f"Verse {verse_number} in book {book_number}, chapter {chapter_number} is out of range.")
