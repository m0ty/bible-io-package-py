import json
from bible_io.word_index import WordIndex
from bible_io.book import Book
from bible_io.chapter import Chapter
from bible_io.errors import *
from bible_io.verse import Verse


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