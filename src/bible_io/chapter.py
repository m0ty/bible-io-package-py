"""Validated Bible chapter value model."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from types import MappingProxyType
from typing import Any

from bible_io_references import BibleBookEnum

from .errors import VerseNotFoundError
from .json_value import (
    FrozenJsonObject,
    JsonValue,
    freeze_json_object,
    json_value_equal,
    json_value_hash,
    thaw_json_value,
)
from .stats import ChapterStats
from .verse import Verse, _require_book, _require_positive_int


class Chapter:
    """An immutable, sorted collection of verses with a declared location."""

    __slots__ = (
        "_annotations",
        "_book",
        "_chapter_number",
        "_verses",
        "_verses_by_number",
    )

    def __init__(
        self,
        book: BibleBookEnum,
        chapter_number: int,
        verses: Iterable[Verse],
        *,
        annotations: Mapping[str, object] | None = None,
    ) -> None:
        validated_book = _require_book(book)
        validated_number = _require_positive_int(chapter_number, "chapter_number")
        prepared = _prepare_verses(validated_book, validated_number, verses)

        self._book = validated_book
        self._chapter_number = validated_number
        self._verses = prepared
        self._verses_by_number = MappingProxyType(
            {verse.verse_number: verse for verse in prepared}
        )
        self._annotations = freeze_json_object(
            annotations,
            reserved_keys={"verses"},
        )

    @property
    def book(self) -> BibleBookEnum:
        return self._book

    @property
    def chapter_number(self) -> int:
        return self._chapter_number

    @property
    def number(self) -> int:
        return self._chapter_number

    @property
    def verses(self) -> tuple[Verse, ...]:
        return self._verses

    @property
    def annotations(self) -> FrozenJsonObject:
        return self._annotations

    def get_verses(self) -> tuple[Verse, ...]:
        return self.verses

    def get_verse(self, verse_number: int) -> Verse:
        try:
            declared_number = _require_positive_int(verse_number, "verse_number")
        except (TypeError, ValueError):
            raise VerseNotFoundError(
                self.book,
                self.chapter_number,
                verse_number,
            ) from None
        verse = self._verses_by_number.get(declared_number)
        if verse is None:
            raise VerseNotFoundError(self.book, self.chapter_number, verse_number)
        return verse

    def search(self, word: str) -> tuple[Verse, ...]:
        return self.verses_containing(word)

    def contains_word(self, word: str) -> bool:
        return any(verse.contains_word(word) for verse in self.verses)

    def verses_containing(self, word: str) -> tuple[Verse, ...]:
        return tuple(verse for verse in self.verses if verse.contains_word(word))

    @property
    def reference(self) -> str:
        return f"{self.book.full_name} {self.chapter_number}"

    @property
    def stats(self) -> ChapterStats:
        character_count = sum(verse.length for verse in self.verses)
        verse_count = len(self.verses)
        return ChapterStats(
            verse_count=verse_count,
            total_words=sum(len(verse.words) for verse in self.verses),
            average_verse_length=(
                (character_count + verse_count // 2) // verse_count
                if verse_count
                else 0
            ),
        )

    def copy_with(
        self,
        *,
        book: BibleBookEnum | None = None,
        chapter_number: int | None = None,
        verses: Iterable[Verse] | None = None,
        annotations: Mapping[str, object] | None = None,
    ) -> Chapter:
        """Return a validated structural copy with selected replacements."""

        return type(self)(
            self.book if book is None else book,
            self.chapter_number if chapter_number is None else chapter_number,
            self.verses if verses is None else verses,
            annotations=self.annotations if annotations is None else annotations,
        )

    def with_annotations(self, annotations: Mapping[str, object]) -> Chapter:
        return self.copy_with(annotations=annotations)

    def to_json_value(self) -> JsonValue:
        verses_json: dict[str, JsonValue] = {
            str(verse.verse_number): verse.to_json_value() for verse in self.verses
        }
        if not self.annotations:
            return verses_json
        annotations = thaw_json_value(self.annotations)
        assert isinstance(annotations, dict)
        return {**annotations, "verses": verses_json}

    def __iter__(self) -> Iterator[Verse]:
        return iter(self.verses)

    def __len__(self) -> int:
        return len(self.verses)

    def __contains__(self, value: object) -> bool:
        return value in self.verses

    def __repr__(self) -> str:
        return (
            f"Chapter({self.book.as_str()}:{self.chapter_number}, "
            f"verses={len(self.verses)})"
        )

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Chapter):
            return NotImplemented
        return (
            self.book == other.book
            and self.chapter_number == other.chapter_number
            and self.verses == other.verses
            and json_value_equal(self.annotations, other.annotations)
        )

    def __hash__(self) -> int:
        return hash(
            (
                self.book,
                self.chapter_number,
                self.verses,
                json_value_hash(self.annotations),
            )
        )


def _prepare_verses(
    book: BibleBookEnum,
    chapter_number: int,
    verses: Iterable[Verse],
) -> tuple[Verse, ...]:
    try:
        prepared = tuple(verses)
    except TypeError as exc:
        raise TypeError("verses must be an iterable of Verse objects") from exc

    seen: set[int] = set()
    for verse in prepared:
        if not isinstance(verse, Verse):
            raise TypeError("verses must contain only Verse objects")
        if verse.book != book:
            raise ValueError(
                f"verse {verse.verse_number} belongs to another book"
            )
        if verse.chapter_number != chapter_number:
            raise ValueError(
                f"verse {verse.verse_number} belongs to another chapter"
            )
        if verse.verse_number in seen:
            raise ValueError(f"duplicate verse number {verse.verse_number}")
        seen.add(verse.verse_number)
    return tuple(sorted(prepared, key=lambda verse: verse.verse_number))
