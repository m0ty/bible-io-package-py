from bible_io.word_index import WordIndex
from bible_io.errors import VerseNotFoundError
from bible_io.verse import Verse


class Chapter:
    def __init__(self, book_number: int, chapter_number: int, verses: list[Verse]):
        self.book_number = book_number
        self.chapter_number = chapter_number
        self.verses = verses

    def get_verses(self) -> list[Verse]:
        return self.verses

    def get_verse(self, verse_number: int) -> Verse:
        if not (1 <= verse_number <= len(self.verses)):
            raise VerseNotFoundError(self.book_number, self.chapter_number, verse_number)
        return self.verses[verse_number - 1]

    def find_word(self, word: str) -> list[WordIndex]:
        indices = []
        for verse in self.verses:
            if verse.contains_word(word):
                indices.append(WordIndex(self.book_number, self.chapter_number, verse.verse_number))
        return indices
