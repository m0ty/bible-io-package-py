import json
from .errors import *



class WordIndex:
    def __init__(self, book_number: int, chapter_number: int, verse_number: int):
        self.book_number = book_number
        self.chapter_number = chapter_number
        self.verse_number = verse_number

    def __repr__(self):
        return f"WordIndex(Book {self.book_number}, Chapter {self.chapter_number}, Verse {self.verse_number})"


class Verse:
    def __init__(self, book_number: int, chapter_number: int, verse_number: int, text: str):
        self.book_number = book_number
        self.chapter_number = chapter_number
        self.verse_number = verse_number
        self.text = text

    def __repr__(self):
        return f"Verse({self.book_number}:{self.chapter_number}:{self.verse_number}) -> {self.text}"

    def contains_word(self, word: str) -> bool:
        """Check if the verse contains a given word (case-insensitive)."""
        return word.lower() in self.text.lower()


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


class Bible:
    def __init__(self, books: list[Book]):
        self.books = books

    def get_book(self, book_number: int) -> 'Book':
        if not (1 <= book_number <= len(self.books)):
            raise BookNotFoundError(book_number)
        return self.books[book_number - 1]

    def get_verses(self, book_number: int, chapter_number: int) -> list['Verse']:
        book = self.get_book(book_number)
        return book.get_verses(chapter_number)

    def get_verse(self, book_number: int, chapter_number: int, verse_number: int) -> 'Verse':
        book = self.get_book(book_number)
        return book.get_verse(chapter_number, verse_number)

    def get_verse_by_index(self, word_index: 'WordIndex') -> 'Verse':
        return self.get_verse(word_index.book_number, word_index.chapter_number, word_index.verse_number)

    def find_word(self, word: str) -> list[WordIndex]:
        indices: list['WordIndex'] = []
        for book in self.books:
            indices += book.find_word(word)
        return indices

    @classmethod
    def new(cls, json_path: str) -> 'Bible':
        with open(json_path, "r", encoding='utf-8-sig') as file:
            jtopy = "".join(file.readlines())
            book_list = json.loads(jtopy)

            books: list['Book'] = []

            for book_index, book in enumerate(book_list):
                chapters: list['Chapter'] = []
                book_number = book_index + 1

                for chapter_index, verse_list in enumerate(book["chapters"]):
                    verses: list['Verse'] = []
                    chapter_number = chapter_index + 1

                    for verse_index, verse in enumerate(verse_list):
                        verse_number = verse_index + 1
                        verses.append(Verse(book_number, chapter_number, verse_number, verse))

                    chapter = Chapter(book_number, chapter_number, verses)
                    chapters.append(chapter)

                book = Book(book["name"], book_number, chapters)
                books.append(book)

            return cls(books)