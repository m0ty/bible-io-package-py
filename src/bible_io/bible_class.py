import json
import re
from collections import defaultdict
from functools import cached_property
from os import PathLike
from pathlib import Path

from .bible_book_enums import BibleBook, ParseBibleBookError
from .book import Book
from .chapter import Chapter
from .errors import *
from .verse import Verse


class Bible:
    _NON_WORD_RE = re.compile(r"[^\w\s]")

    def __init__(self, json_path: str | PathLike[str]):
        books, search_index = self._load_from_json(json_path)
        self._initialize_from_books(books, search_index)

    def _initialize_from_books(
        self,
        books: list[Book],
        search_index: dict[str, list[Verse]] | None = None,
    ) -> None:
        self.books = books
        self._books_by_enum = {book.book: book for book in books}
        if search_index is not None:
            # Seed the cached property so the first search can reuse the prebuilt index.
            self.__dict__["_search_index"] = search_index

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

    def get_book_by_enum(self, book: BibleBook) -> 'Book':
        try:
            return self._books_by_enum[book]
        except KeyError as exc:
            raise BookNotFoundError(book) from exc

    @classmethod
    def _normalize_text(cls, text: str) -> str:
        """Lowercase text and strip punctuation, collapsing whitespace."""
        normalized = cls._NON_WORD_RE.sub(" ", text.lower())
        return " ".join(normalized.split())

    @classmethod
    def _tokenize_text(cls, text: str) -> list[str]:
        normalized = cls._normalize_text(text)
        if not normalized:
            return []
        return normalized.split()

    def _build_search_index(self) -> dict[str, list[Verse]]:
        index: defaultdict[str, list[Verse]] = defaultdict(list)
        for book in self.books:
            for chapter in book.get_chapters():
                for verse in chapter.get_verses():
                    for word in set(self._tokenize_text(verse.text)):
                        index[word].append(verse)
        return dict(index)

    @cached_property
    def _search_index(self) -> dict[str, list[Verse]]:
        return self._build_search_index()

    def invalidate_search_index(self) -> None:
        """Mark the cached search index as stale so it will be rebuilt on demand."""
        self.__dict__.pop("_search_index", None)

    def search(self, word: str) -> list[Verse]:
        tokens = self._tokenize_text(word)
        if not tokens:
            return []

        index = self._search_index
        matches: list[Verse] = []
        seen_ids: set[int] = set()

        for token in tokens:
            for verse in index.get(token, []):
                verse_identifier = id(verse)
                if verse_identifier not in seen_ids:
                    seen_ids.add(verse_identifier)
                    matches.append(verse)

        return matches

    @classmethod
    def _load_from_json(
        cls, json_path: str | PathLike[str]
    ) -> tuple[list[Book], dict[str, list[Verse]]]:
        path = Path(json_path)
        with path.open("r", encoding="utf-8-sig") as file:
            data = json.load(file)

        books: list['Book'] = []
        search_index: defaultdict[str, list[Verse]] = defaultdict(list)

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
                    verse_text = verses_data[verse_key]
                    verse = Verse(
                        book_enum,
                        chapter_number,
                        verse_number,
                        verse_text,
                    )
                    verses.append(verse)

                    for word in set(cls._tokenize_text(verse_text)):
                        search_index[word].append(verse)

                chapters.append(Chapter(book_enum, chapter_number, verses))

            book_name = book_data.get("name") or book_enum.full_name

            books.append(Book(book_enum, chapters, name=book_name))

        return books, dict(search_index)

    @classmethod
    def new(
        cls,
        books: list[Book],
        search_index: dict[str, list[Verse]] | None = None,
    ) -> 'Bible':
        bible = cls.__new__(cls)
        bible._initialize_from_books(books, search_index)
        return bible
