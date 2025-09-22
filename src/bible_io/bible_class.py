import json
from .bible_book_enums import BibleBook, ParseBibleBookError
from .word_index import WordIndex
from .book import Book
from .chapter import Chapter
from .errors import *
from .verse import Verse


class Bible:
    def __init__(self, books: list[Book]):
        self.books = books
        self._books_by_enum = {book.book: book for book in books}

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
        book = self.get_book_by_enum(word_index.book)
        return book.get_verse(word_index.chapter_number, word_index.verse_number)

    def get_book_by_enum(self, book: BibleBook) -> 'Book':
        try:
            return self._books_by_enum[book]
        except KeyError as exc:
            raise BookNotFoundError(book) from exc

    def find_word(self, word: str) -> list[WordIndex]:
        indices: list['WordIndex'] = []
        for book in self.books:
            indices += book.find_word(word)
        return indices

    @classmethod
    def new(cls, json_path: str) -> 'Bible':
        with open(json_path, "r", encoding="utf-8-sig") as file:
            data = json.load(file)

        books: list['Book'] = []

        books_data = data.get("books", {})

        for book_abbr, book_data in books_data.items():
            chapters: list['Chapter'] = []

            try:
                book_enum = BibleBook.from_str(book_abbr)
            except ParseBibleBookError as exc:
                raise ValueError(
                    f"Unsupported Bible book abbreviation '{book_abbr}' in {json_path}"
                ) from exc

            chapters_data = book_data.get("chapters", {})

            for chapter_key in sorted(chapters_data.keys(), key=lambda c: int(c)):
                verses: list['Verse'] = []
                chapter_number = int(chapter_key)

                verses_data = chapters_data[chapter_key]

                for verse_key in sorted(verses_data.keys(), key=lambda v: int(v)):
                    verse_number = int(verse_key)
                    verses.append(
                        Verse(
                            book_enum,
                            chapter_number,
                            verse_number,
                            verses_data[verse_key],
                        )
                    )

                chapters.append(Chapter(book_enum, chapter_number, verses))

            book_name = book_data.get("name") or book_enum.full_name

            books.append(Book(book_enum, chapters, name=book_name))

        return cls(books)
