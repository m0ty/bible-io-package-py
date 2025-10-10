from .bible_book_enums import BibleBookEnum
from .chapter import Chapter
from .errors import ChapterNotFoundError
from .verse import Verse


class Book:
    def __init__(self, book: BibleBookEnum, chapters: list[Chapter], name: str | None = None):
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

    def search(self, word: str) -> list[Verse]:
        matches: list['Verse'] = []
        for chapter in self.chapters:
            matches.extend(chapter.search(word))
        return matches

    def __repr__(self):
        return f"Book({self.book.as_str()}: {self.name})"
