from .bible_book_enums import BibleBook
from .word_index import WordIndex
from .chapter import Chapter
from .errors import ChapterNotFoundError
from .verse import Verse


class Book:
    def __init__(self, book: BibleBook, chapters: list[Chapter], name: str | None = None):
        self.book = book
        self.name = name or book.full_name
        self.chapters = chapters

    def get_chapters(self) -> list[Chapter]:
        return self.chapters

    def get_verses(self, chapter_number: int) -> list[Verse]:
        if not (1 <= chapter_number <= len(self.chapters)):
            raise ChapterNotFoundError(self.book, chapter_number)
        return self.chapters[chapter_number - 1].get_verses()

    def get_verse(self, chapter_number: int, verse_number: int) -> Verse:
        if not (1 <= chapter_number <= len(self.chapters)):
            raise ChapterNotFoundError(self.book, chapter_number)
        return self.chapters[chapter_number - 1].get_verse(verse_number)

    def find_word(self, word: str) -> list['WordIndex']:
        indices = []
        for chapter in self.chapters:
            indices.extend(chapter.find_word(word))
        return indices

    def __repr__(self):
        return f"Book({self.book.as_str()}: {self.name})"
