"""Validated Bible verse value model."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from bible_io_references import BibleBookEnum, VerseRef

from .json_value import (
    FrozenJsonObject,
    JsonValue,
    freeze_json_object,
    json_value_equal,
    json_value_hash,
    thaw_json_value,
    validate_json_string,
)
from .stats import VerseStats

if TYPE_CHECKING:
    from .location import BibleLocation


class Verse:
    """A validated verse coordinate, its text, and optional annotations.

    Coordinates, text, and annotations are immutable. Use :meth:`with_text`
    or :meth:`copy_with` to derive a changed value.
    """

    __slots__ = ("_annotations", "_book", "_chapter_number", "_text", "_verse_number")

    def __init__(
        self,
        book: BibleBookEnum,
        chapter_number: int,
        verse_number: int,
        text: str,
        *,
        annotations: Mapping[str, object] | None = None,
    ) -> None:
        self._book = _require_book(book)
        self._chapter_number = _require_positive_int(
            chapter_number,
            "chapter_number",
        )
        self._verse_number = _require_positive_int(verse_number, "verse_number")
        self._text = _require_text(text)
        self._annotations = freeze_json_object(
            annotations,
            reserved_keys={"text"},
        )

    @property
    def book(self) -> BibleBookEnum:
        return self._book

    @property
    def chapter_number(self) -> int:
        return self._chapter_number

    @property
    def chapter(self) -> int:
        """Alias for ``chapter_number`` matching the reference package."""

        return self._chapter_number

    @property
    def verse_number(self) -> int:
        return self._verse_number

    @property
    def number(self) -> int:
        """Alias for ``verse_number``."""

        return self._verse_number

    @property
    def text(self) -> str:
        return self._text

    @property
    def annotations(self) -> FrozenJsonObject:
        return self._annotations

    @property
    def location(self) -> BibleLocation:
        """Return this verse's validated edition-independent location."""

        from .location import BibleLocation

        return BibleLocation(self.book, self.chapter_number, self.verse_number)

    def to_verse_ref(self) -> VerseRef:
        """Convert this verse coordinate to a reference-package value."""

        return VerseRef(self.book, self.chapter_number, self.verse_number)

    def contains_word(self, word: str) -> bool:
        """Return whether ``word`` is exactly one matching Unicode token."""

        if not isinstance(word, str):
            raise TypeError("word must be a string")
        from .text_search import tokenize_search_text

        query = tokenize_search_text(word)
        return len(query) == 1 and query[0] in tokenize_search_text(self.text)

    def contains_text(self, query: str) -> bool:
        """Return whether a non-empty normalized substring occurs in the text."""

        if not isinstance(query, str):
            raise TypeError("query must be a string")
        from .text_search import contains_normalized_text

        return contains_normalized_text(self.text, query)

    def contains_any(self, words: Iterable[str]) -> bool:
        """Return whether at least one supplied word occurs as a whole token."""

        return any(self.contains_word(word) for word in words)

    def contains_all(self, words: Iterable[str]) -> bool:
        """Return whether every supplied word occurs as a whole token."""

        return all(self.contains_word(word) for word in words)

    @property
    def words(self) -> tuple[str, ...]:
        """Return original Unicode letter/mark/number tokens in source order."""

        from .text_search import extract_unicode_words

        return tuple(extract_unicode_words(self.text))

    @property
    def length(self) -> int:
        """Return the text length in Unicode code points."""

        return len(self.text)

    @property
    def reference(self) -> str:
        return f"{self.book.full_name} {self.chapter_number}:{self.verse_number}"

    @property
    def short_reference(self) -> str:
        return f"{self.book.as_str()}{self.chapter_number}:{self.verse_number}"

    @property
    def stats(self) -> VerseStats:
        words = self.words
        return VerseStats(
            word_count=len(words),
            character_count=self.length,
            average_word_length=(
                sum(len(word) for word in words) / len(words) if words else 0.0
            ),
        )

    def copy_with(
        self,
        *,
        book: BibleBookEnum | None = None,
        chapter_number: int | None = None,
        verse_number: int | None = None,
        text: str | None = None,
        annotations: Mapping[str, object] | None = None,
    ) -> Verse:
        """Return a validated structural copy with selected replacements."""

        return type(self)(
            self.book if book is None else book,
            self.chapter_number if chapter_number is None else chapter_number,
            self.verse_number if verse_number is None else verse_number,
            self.text if text is None else text,
            annotations=self.annotations if annotations is None else annotations,
        )

    def with_text(self, text: str) -> Verse:
        return self.copy_with(text=text)

    def with_annotations(self, annotations: Mapping[str, object]) -> Verse:
        return self.copy_with(annotations=annotations)

    def to_json_value(self) -> JsonValue:
        """Encode this verse in the compatible plain or annotated JSON shape."""

        if not self.annotations:
            return self.text
        annotations = thaw_json_value(self.annotations)
        assert isinstance(annotations, dict)
        return {"text": self.text, **annotations}

    def __len__(self) -> int:
        return self.length

    def __repr__(self) -> str:
        return (
            f"Verse({self.book.as_str()}:{self.chapter_number}:"
            f"{self.verse_number}) -> {self.text}"
        )

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Verse):
            return NotImplemented
        return (
            self.book == other.book
            and self.chapter_number == other.chapter_number
            and self.verse_number == other.verse_number
            and self.text == other.text
            and json_value_equal(self.annotations, other.annotations)
        )

    def __hash__(self) -> int:
        return hash(
            (
                self.book,
                self.chapter_number,
                self.verse_number,
                self.text,
                json_value_hash(self.annotations),
            )
        )


def _require_book(value: BibleBookEnum) -> BibleBookEnum:
    if not isinstance(value, BibleBookEnum):
        raise TypeError("book must be a BibleBookEnum")
    return value


def _require_positive_int(value: int, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


def _require_text(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("text must be a string")
    return validate_json_string(value, path="text")
