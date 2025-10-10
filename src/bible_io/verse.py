
from .bible_book_enums import BibleBookEnum


class Verse:
    def __init__(self, book: BibleBookEnum, chapter_number: int, verse_number: int, text: str):
        self.book = book
        self.chapter_number = chapter_number
        self.verse_number = verse_number
        self.text = text

    def __repr__(self):
        return (
            f"Verse({self.book.as_str()}:{self.chapter_number}:{self.verse_number}) -> {self.text}"
        )

    def contains_word(self, word: str) -> bool:
        """Check if the verse contains a given word (case-insensitive)."""
        return word.lower() in self.text.lower()
