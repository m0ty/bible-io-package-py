"""Stable Bible locations and edition-aware persisted-state keys."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping, cast

from bible_io_references import (
    BibleBookEnum,
    ChapterPassage,
    Passage,
    VersePassage,
    VerseRef,
    book_from_osis_identifier,
    book_from_usfm_identifier,
)

from .json_value import validate_json_string

if TYPE_CHECKING:
    from .verse import Verse


_KEEP_VERSE = object()


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _book_from_string(value: object) -> BibleBookEnum:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("book must be a non-empty string")
    identifier = value.strip()
    parsers = (
        BibleBookEnum.from_str,
        book_from_osis_identifier,
        book_from_usfm_identifier,
    )
    for parser in parsers:
        try:
            return parser(identifier)
        except (TypeError, ValueError):
            pass
    for book in BibleBookEnum:
        if book.full_name.casefold() == identifier.casefold():
            return book
    raise ValueError(f"unknown Bible book: {value}")


@dataclass(frozen=True, slots=True)
class BibleLocation:
    """Stable location for a chapter or verse within one Bible edition."""

    book: BibleBookEnum
    chapter: int
    verse: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.book, BibleBookEnum):
            raise TypeError("book must be BibleBookEnum")
        _positive_int(self.chapter, "chapter")
        if self.verse is not None:
            _positive_int(self.verse, "verse")

    @classmethod
    def checked(
        cls,
        *,
        book: BibleBookEnum,
        chapter: int,
        verse: int | None = None,
    ) -> "BibleLocation":
        """Construct a location with runtime validation."""

        return cls(book, chapter, verse)

    @classmethod
    def from_verse(cls, verse: "Verse") -> "BibleLocation":
        return cls(verse.book, verse.chapter_number, verse.verse_number)

    @classmethod
    def from_verse_ref(cls, reference: VerseRef) -> "BibleLocation":
        if not isinstance(reference, VerseRef):
            raise TypeError("reference must be VerseRef")
        return cls(reference.book, reference.chapter, reference.verse)

    @classmethod
    def from_json(cls, value: Mapping[str, object]) -> "BibleLocation":
        """Restore a location previously produced by :meth:`to_json`."""

        if not isinstance(value, Mapping):
            raise TypeError("location must be a mapping")
        if any(not isinstance(key, str) for key in value):
            raise ValueError("location keys must be strings")
        book = _book_from_string(value.get("book"))
        chapter = _positive_int(value.get("chapter"), "chapter")
        raw_verse = value.get("verse")
        verse = None if raw_verse is None else _positive_int(raw_verse, "verse")
        return cls(book, chapter, verse)

    from_dict = from_json

    @property
    def chapter_number(self) -> int:
        return self.chapter

    @property
    def verse_number(self) -> int | None:
        return self.verse

    @property
    def has_verse(self) -> bool:
        return self.verse is not None

    def copy_with(
        self,
        *,
        book: BibleBookEnum | None = None,
        chapter: int | None = None,
        verse: object = _KEEP_VERSE,
    ) -> "BibleLocation":
        """Return a changed location; explicit ``verse=None`` clears it."""

        next_verse: int | None
        if verse is _KEEP_VERSE:
            next_verse = self.verse
        elif verse is None:
            next_verse = None
        else:
            next_verse = _positive_int(verse, "verse")
        return BibleLocation(
            self.book if book is None else book,
            self.chapter if chapter is None else chapter,
            next_verse,
        )

    def to_passage(self) -> Passage:
        if self.verse is None:
            return ChapterPassage(self.book, self.chapter)
        return VersePassage((self.to_verse_ref(),))

    def to_verse_ref(self) -> VerseRef:
        if self.verse is None:
            raise ValueError("a chapter-only BibleLocation has no VerseRef")
        return VerseRef(self.book, self.chapter, self.verse)

    def to_json(self) -> dict[str, object]:
        result: dict[str, object] = {
            "book": self.book.abbreviation,
            "chapter": self.chapter,
        }
        if self.verse is not None:
            result["verse"] = self.verse
        return result

    to_dict = to_json

    @property
    def reference(self) -> str:
        base = f"{self.book.full_name} {self.chapter}"
        return base if self.verse is None else f"{base}:{self.verse}"

    def __str__(self) -> str:
        return self.reference


@dataclass(frozen=True, slots=True)
class BibleVerseKey:
    """Edition-aware key for bookmarks, highlights, notes, and progress."""

    edition_id: str
    location: BibleLocation

    def __post_init__(self) -> None:
        if (
            not isinstance(self.edition_id, str)
            or not self.edition_id.strip()
            or self.edition_id != self.edition_id.strip()
        ):
            raise ValueError(
                "edition_id must be non-blank and have no surrounding whitespace"
            )
        validate_json_string(self.edition_id, path="edition_id")
        if not isinstance(self.location, BibleLocation):
            raise TypeError("location must be BibleLocation")
        if not self.location.has_verse:
            raise ValueError("location must identify a verse")

    @classmethod
    def checked(
        cls,
        *,
        edition_id: str,
        location: BibleLocation,
    ) -> "BibleVerseKey":
        return cls(edition_id, location)

    @classmethod
    def from_verse(cls, edition_id: str, verse: "Verse") -> "BibleVerseKey":
        return cls(edition_id, BibleLocation.from_verse(verse))

    @classmethod
    def from_json(cls, value: Mapping[str, object]) -> "BibleVerseKey":
        if not isinstance(value, Mapping):
            raise TypeError("BibleVerseKey must be a mapping")
        if any(not isinstance(key, str) for key in value):
            raise ValueError("BibleVerseKey keys must be strings")
        edition_id = value.get("editionId", value.get("edition_id"))
        if not isinstance(edition_id, str):
            raise ValueError("editionId must be a non-blank, trimmed string")
        raw_location = value.get("location")
        if not isinstance(raw_location, Mapping):
            raise ValueError("location must be an object")
        return cls(
            edition_id,
            BibleLocation.from_json(cast(Mapping[str, object], raw_location)),
        )

    from_dict = from_json

    def to_verse_ref(self) -> VerseRef:
        return self.location.to_verse_ref()

    def copy_with(
        self,
        *,
        edition_id: str | None = None,
        location: BibleLocation | None = None,
    ) -> "BibleVerseKey":
        return BibleVerseKey(
            self.edition_id if edition_id is None else edition_id,
            self.location if location is None else location,
        )

    def with_edition_id(self, edition_id: str) -> "BibleVerseKey":
        return BibleVerseKey(edition_id, self.location)

    def with_location(self, location: BibleLocation) -> "BibleVerseKey":
        return BibleVerseKey(self.edition_id, location)

    def to_json(self) -> dict[str, object]:
        return {
            "editionId": self.edition_id,
            "location": self.location.to_json(),
        }

    to_dict = to_json

    def __str__(self) -> str:
        return f"{self.edition_id}:{self.location.reference}"


__all__ = ["BibleLocation", "BibleVerseKey"]
