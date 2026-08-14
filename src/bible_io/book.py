"""Validated Bible book value model."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from types import MappingProxyType
from typing import Any

from bible_io_references import BibleBookEnum

from .chapter import Chapter
from .errors import ChapterNotFoundError
from .json_value import (
    FrozenJsonObject,
    JsonValue,
    freeze_json_object,
    json_value_equal,
    json_value_hash,
    thaw_json_value,
    validate_json_string,
)
from .stats import BookStats
from .verse import Verse, _require_book, _require_positive_int


class Book:
    """An immutable, sorted collection of chapters for one Bible book."""

    __slots__ = (
        "_annotations",
        "_book_enum",
        "_chapters",
        "_chapters_by_number",
        "_name",
    )

    def __init__(
        self,
        book_enum: BibleBookEnum,
        chapters: Iterable[Chapter],
        name: str | None = None,
        *,
        annotations: Mapping[str, object] | None = None,
    ) -> None:
        validated_book = _require_book(book_enum)
        validated_name = _require_name(
            validated_book.full_name if name is None else name
        )
        prepared = _prepare_chapters(validated_book, chapters)

        self._book_enum = validated_book
        self._name = validated_name
        self._chapters = prepared
        self._chapters_by_number = MappingProxyType(
            {chapter.chapter_number: chapter for chapter in prepared}
        )
        self._annotations = freeze_json_object(
            annotations,
            reserved_keys={"name", "chapters"},
        )

    @property
    def book_enum(self) -> BibleBookEnum:
        return self._book_enum

    @property
    def book(self) -> BibleBookEnum:
        """Alias for ``book_enum`` matching the sibling value models."""

        return self._book_enum

    @property
    def name(self) -> str:
        return self._name

    @property
    def title(self) -> str:
        return self._name

    @property
    def abbreviation(self) -> str:
        return self.book_enum.as_str()

    @property
    def abbrev(self) -> str:
        return self.abbreviation

    @property
    def chapters(self) -> tuple[Chapter, ...]:
        return self._chapters

    @property
    def annotations(self) -> FrozenJsonObject:
        return self._annotations

    def get_chapters(self) -> tuple[Chapter, ...]:
        return self.chapters

    def get_chapter(self, chapter_number: int) -> Chapter:
        try:
            declared_number = _require_positive_int(chapter_number, "chapter_number")
        except (TypeError, ValueError):
            raise ChapterNotFoundError(self.book_enum, chapter_number) from None
        chapter = self._chapters_by_number.get(declared_number)
        if chapter is None:
            raise ChapterNotFoundError(self.book_enum, chapter_number)
        return chapter

    def get_verses(self, chapter_number: int) -> tuple[Verse, ...]:
        return self.get_chapter(chapter_number).get_verses()

    def get_verse(self, chapter_number: int, verse_number: int) -> Verse:
        return self.get_chapter(chapter_number).get_verse(verse_number)

    @property
    def all_verses(self) -> tuple[Verse, ...]:
        return tuple(verse for chapter in self.chapters for verse in chapter.verses)

    @property
    def verse_count(self) -> int:
        return sum(len(chapter.verses) for chapter in self.chapters)

    def search(self, word: str) -> tuple[Verse, ...]:
        return tuple(
            verse
            for chapter in self.chapters
            for verse in chapter.verses_containing(word)
        )

    def chapters_containing(self, word: str) -> tuple[Chapter, ...]:
        return tuple(
            chapter for chapter in self.chapters if chapter.contains_word(word)
        )

    @property
    def reference(self) -> str:
        return self.book_enum.full_name

    @property
    def stats(self) -> BookStats:
        chapter_count = len(self.chapters)
        verse_count = self.verse_count
        return BookStats(
            chapter_count=chapter_count,
            verse_count=verse_count,
            total_words=sum(len(verse.words) for verse in self.all_verses),
            average_verses_per_chapter=(
                verse_count / chapter_count if chapter_count else 0.0
            ),
        )

    def copy_with(
        self,
        *,
        book_enum: BibleBookEnum | None = None,
        chapters: Iterable[Chapter] | None = None,
        name: str | None = None,
        annotations: Mapping[str, object] | None = None,
    ) -> Book:
        """Return a validated structural copy with selected replacements."""

        return type(self)(
            self.book_enum if book_enum is None else book_enum,
            self.chapters if chapters is None else chapters,
            self.name if name is None else name,
            annotations=self.annotations if annotations is None else annotations,
        )

    def with_name(self, name: str) -> Book:
        return self.copy_with(name=name)

    def with_title(self, title: str) -> Book:
        return self.with_name(title)

    def with_annotations(self, annotations: Mapping[str, object]) -> Book:
        return self.copy_with(annotations=annotations)

    def to_json_value(self) -> JsonValue:
        annotations = thaw_json_value(self.annotations)
        assert isinstance(annotations, dict)
        chapters: dict[str, JsonValue] = {
            str(chapter.chapter_number): chapter.to_json_value()
            for chapter in self.chapters
        }
        return {**annotations, "name": self.name, "chapters": chapters}

    def __iter__(self) -> Iterator[Chapter]:
        return iter(self.chapters)

    def __len__(self) -> int:
        return len(self.chapters)

    def __contains__(self, value: object) -> bool:
        return value in self.chapters

    def __repr__(self) -> str:
        return f"Book({self.book_enum.as_str()}: {self.name})"

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Book):
            return NotImplemented
        return (
            self.book_enum == other.book_enum
            and self.name == other.name
            and self.chapters == other.chapters
            and json_value_equal(self.annotations, other.annotations)
        )

    def __hash__(self) -> int:
        return hash(
            (
                self.book_enum,
                self.name,
                self.chapters,
                json_value_hash(self.annotations),
            )
        )


def _prepare_chapters(
    book: BibleBookEnum,
    chapters: Iterable[Chapter],
) -> tuple[Chapter, ...]:
    try:
        prepared = tuple(chapters)
    except TypeError as exc:
        raise TypeError("chapters must be an iterable of Chapter objects") from exc

    seen: set[int] = set()
    for chapter in prepared:
        if not isinstance(chapter, Chapter):
            raise TypeError("chapters must contain only Chapter objects")
        if chapter.book != book:
            raise ValueError(
                f"chapter {chapter.chapter_number} belongs to another book"
            )
        if chapter.chapter_number in seen:
            raise ValueError(f"duplicate chapter number {chapter.chapter_number}")
        seen.add(chapter.chapter_number)
    return tuple(sorted(prepared, key=lambda chapter: chapter.chapter_number))


def _require_name(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("name must be a string")
    if not value.strip():
        raise ValueError("name must not be blank")
    return validate_json_string(value, path="name")
