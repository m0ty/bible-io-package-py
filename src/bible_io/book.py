from bible_io.word_index import WordIndex
from bible_io.chapter import Chapter
from bible_io.errors import ChapterNotFoundError
from bible_io.verse import Verse


class Book:
    def __init__(self, name: str, book_number: int, chapters: list[Chapter]):
        self.name = name
        self.book_number = book_number
        self.chapters = chapters

    def get_chapters(self) -> list[Chapter]:
        return self.chapters

    def get_verses(self, chapter_number: int) -> list[Verse]:
        if not (1 <= chapter_number <= len(self.chapters)):
            raise ChapterNotFoundError(self.book_number, chapter_number)
        return self.chapters[chapter_number - 1].get_verses()

    def get_verse(self, chapter_number: int, verse_number: int) -> Verse:
        if not (1 <= chapter_number <= len(self.chapters)):
            raise ChapterNotFoundError(self.book_number, chapter_number)
        return self.chapters[chapter_number - 1].get_verse(verse_number)

    def find_word(self, word: str) -> list['WordIndex']:
        indices = []
        for chapter in self.chapters:
            indices.extend(chapter.find_word(word))
        return indices

    def __repr__(self):
        return f"Book({self.book_number}: {self.name})"
