from .bible_book_enums import BibleBook
from .word_index import WordIndex
from .errors import VerseNotFoundError
from .verse import Verse


class Chapter:
    def __init__(self, book: BibleBook, chapter_number: int, verses: list[Verse]):
        self.book = book
        self.chapter_number = chapter_number
        self.verses = verses

    def get_verses(self) -> list[Verse]:
        return self.verses

    def get_verse(self, verse_number: int) -> Verse:
        if not (1 <= verse_number <= len(self.verses)):
            raise VerseNotFoundError(self.book, self.chapter_number, verse_number)
        return self.verses[verse_number - 1]

    def find_word(self, word: str) -> list[WordIndex]:
        indices = []
        for verse in self.verses:
            if verse.contains_word(word):
                indices.append(WordIndex(self.book, self.chapter_number, verse.verse_number))
        return indices
