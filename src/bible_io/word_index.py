
from .bible_book_enums import BibleBook


class WordIndex:
    def __init__(self, book: BibleBook, chapter_number: int, verse_number: int):
        self.book = book
        self.chapter_number = chapter_number
        self.verse_number = verse_number

    def __repr__(self):
        return (
            "WordIndex("
            f"Book {self.book.as_str()}, "
            f"Chapter {self.chapter_number}, "
            f"Verse {self.verse_number})"
        )
