import json
import re
from collections import defaultdict
from functools import cached_property
from os import PathLike
from pathlib import Path
from .bible_book_enums import BibleBookEnum, ParseBibleBookError
from .book import Book
from .chapter import Chapter
from .errors import *
from .verse import Verse


class Bible:
    """In-memory representation of a Bible with indexing and search helpers."""

    _NON_WORD_RE = re.compile(r"[^\w\s]")

    def __init__(self, json_path: str | PathLike[str]):
        """Load the Bible data from a JSON file and initialize state.

        Args:
            json_path (str | PathLike[str]): Path to the serialized Bible dataset.

        Returns:
            None: The instance is initialized in-place.
        """

        books, search_index = self._load_from_json(json_path)
        self._initialize_from_books(books, search_index)

    def _initialize_from_books(
        self,
        books: list[Book],
        search_index: dict[str, list[Verse]] | None = None,
    ) -> None:
        """Populate lookups from book instances and an optional search index.

        Args:
            books (list[Book]): Concrete book objects in canonical order.
            search_index (dict[str, list[Verse]] | None): Optional precomputed
                word-to-verse mapping used to seed the cache.

        Returns:
            None: Internal caches and lookups are populated in-place.
        """
        self.books = books
        self._books_by_enum = {book.book: book for book in books}
        if search_index is not None:
            # Seed the cached property so the first search can reuse the prebuilt index.
            self.__dict__["_search_index"] = search_index

    def get_book(self, book: BibleBookEnum) -> Book:
        """Fetch a book by enumeration identifier.

        Args:
            book (BibleBookEnum): The book enumeration to resolve.

        Returns:
            Book: The matching book instance.

        Raises:
            BookNotFoundError: If the book is not loaded in the Bible.
        """
        try:
            return self._books_by_enum[book]
        except KeyError as exc:
            raise BookNotFoundError(book) from exc

    def get_book_by_id(self, book_number: int) -> Book:
        """Fetch a book by its 1-based index position.

        Args:
            book_number (int): Sequential identifier (starting at 1).

        Returns:
            Book: The matching book instance.

        Raises:
            BookNotFoundError: If ``book_number`` is outside the available range.
        """
        if not (1 <= book_number <= len(self.books)):
            raise BookNotFoundError(book_number)
        return self.books[book_number - 1]

    def get_verses(self, bible_book: BibleBookEnum, chapter_number: int) -> list[Verse]:
        """Retrieve all verses for a specific chapter.

        Args:
            bible_book (BibleBookEnum): The book containing the chapter.
            chapter_number (int): The chapter identifier (1-indexed).

        Returns:
            list[Verse]: Ordered verses in the requested chapter.

        Raises:
            BookNotFoundError: If the containing book is missing.
            ChapterNotFoundError: If the chapter index is invalid for the book.
        """
        book: Book = self.get_book(bible_book)
        return book.get_verses(chapter_number)

    def get_verse(self, bible_book: BibleBookEnum, chapter_number: int, verse_number: int) -> Verse:
        """Retrieve a single verse identified by book, chapter, and verse.

        Args:
            bible_book (BibleBookEnum): The book containing the verse.
            chapter_number (int): The chapter number (1-indexed).
            verse_number (int): The verse number (1-indexed).

        Returns:
            Verse: The matching verse instance.

        Raises:
            BookNotFoundError: If the containing book is missing.
            ChapterNotFoundError: If the chapter number is invalid.
            VerseNotFoundError: If the verse number is invalid within the chapter.
        """
        book: Book = self.get_book(bible_book)
        return book.get_verse(chapter_number, verse_number)



    @classmethod
    def _normalize_text(cls, text: str) -> str:
        """Lowercase text, remove punctuation, and collapse whitespace.

        Args:
            text (str): The input text to normalize.

        Returns:
            str: The cleaned text suitable for tokenization.
        """
        normalized = cls._NON_WORD_RE.sub(" ", text.lower())
        return " ".join(normalized.split())

    @classmethod
    def _tokenize_text(cls, text: str) -> list[str]:
        """Split normalized text into tokens used for search indexing.

        Args:
            text (str): The input text to split.

        Returns:
            list[str]: Tokenized words; an empty list for blank input.
        """
        normalized = cls._normalize_text(text)
        if not normalized:
            return []
        return normalized.split()

    def _build_search_index(self) -> dict[str, list[Verse]]:
        """Create a mapping of lowercase tokens to the verses that contain them.

        Returns:
            dict[str, list[Verse]]: Dictionary mapping each word to matching verses.
        """
        index: defaultdict[str, list[Verse]] = defaultdict(list)
        for book in self.books:
            for chapter in book.get_chapters():
                for verse in chapter.get_verses():
                    for word in set(self._tokenize_text(verse.text)):
                        index[word].append(verse)
        return dict(index)

    @cached_property
    def _search_index(self) -> dict[str, list[Verse]]:
        """Return the cached word-to-verse mapping, building it on first access.

        Returns:
            dict[str, list[Verse]]: Word-to-verse mapping used for search.
        """
        return self._build_search_index()

    def invalidate_search_index(self) -> None:
        """Mark the cached search index as stale so it will be rebuilt on demand.

        Returns:
            None: Indicates the cache was cleared successfully.
        """
        self.__dict__.pop("_search_index", None)

    def search(self, word: str) -> list[Verse]:
        """Search for verses containing any of the provided words.

        Args:
            word (str): A word or phrase to search, case-insensitive.

        Returns:
            list[Verse]: Verses matching at least one token in the input.
        """
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
        """Load book data and a search index from a JSON file.

        Args:
            json_path (str | PathLike[str]): Path to the JSON data file.

        Returns:
            tuple[list[Book], dict[str, list[Verse]]]: Instantiated books and
            a prebuilt search index for fast initialization.

        Raises:
            ValueError: If the dataset includes an unknown book abbreviation.
        """
        path = Path(json_path)
        with path.open("r", encoding="utf-8-sig") as file:
            data = json.load(file)

        books: list['Book'] = []
        search_index: defaultdict[str, list[Verse]] = defaultdict(list)

        books_data = data.get("books", {})

        for book_abbr, book_data in books_data.items():
            chapters: list['Chapter'] = []

            try:
                book_enum = BibleBookEnum.from_str(book_abbr)
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
