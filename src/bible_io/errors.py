"""Structured errors raised by :mod:`bible_io`.

Serialized-content failures intentionally carry a stable code and a
JSONPath-like location.  Applications can therefore report useful diagnostics
without parsing a human-facing exception message.
"""

from __future__ import annotations

from enum import Enum
from types import TracebackType
from typing import TypeAlias

from bible_io_references import BibleBookEnum


BookRef: TypeAlias = int | str | BibleBookEnum
_MISSING = object()


class BibleError(Exception):
    """Base exception for Bible lookup, parsing, and content errors."""

    def __init__(
        self,
        message: str,
        *,
        context: object | None = None,
        cause: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.context = context
        self.cause = cause
        self.traceback = (
            traceback
            if traceback is not None
            else getattr(cause, "__traceback__", None)
        )
        if cause is not None:
            self.__cause__ = cause

    @property
    def stack_trace(self) -> TracebackType | None:
        """Compatibility name for the retained Python traceback."""

        return self.traceback


class BibleDataFormatErrorCode(str, Enum):
    """Stable machine-readable codes for malformed Bible and catalog data."""

    INVALID_JSON = "invalid_json"
    INVALID_TYPE = "invalid_type"
    MISSING_FIELD = "missing_field"
    INVALID_VALUE = "invalid_value"
    DUPLICATE_ID = "duplicate_id"
    DUPLICATE_KEY = "duplicate_key"
    RESERVED_FIELD = "reserved_field"
    NON_JSON_VALUE = "non_json_value"

    def __str__(self) -> str:
        return self.value


class BibleDataFormatError(BibleError, ValueError):
    """A path-aware violation of the serialized content contract."""

    def __init__(
        self,
        *,
        code: BibleDataFormatErrorCode | str,
        path: str,
        message: str,
        value: object = _MISSING,
        cause: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        self.code = BibleDataFormatErrorCode(code)
        self.path = path
        self.value = None if value is _MISSING else value
        self.has_value = value is not _MISSING
        context: dict[str, object] = {"code": self.code.value, "path": path}
        if self.has_value:
            context["value"] = self.value
        super().__init__(
            message,
            context=context,
            cause=cause,
            traceback=traceback,
        )

    def __str__(self) -> str:
        result = f"BibleDataFormatError({self.code.value}) at {self.path}: {self.message}"
        if self.has_value:
            result += f"\nValue: {self.value!r}"
        if self.cause is not None:
            result += f"\nCause: {self.cause}"
        return result


def _format_book(book: BookRef | object) -> str:
    if isinstance(book, BibleBookEnum):
        return book.full_name
    return str(book)


class BookNotFoundError(BibleError, LookupError):
    """Raised when the requested book is not loaded."""

    def __init__(self, book: BookRef) -> None:
        super().__init__(
            f"Book {_format_book(book)} is out of range.",
            context=book,
        )


class ChapterNotFoundError(BibleError, LookupError):
    """Raised when a declared chapter number is not loaded."""

    def __init__(self, book: BookRef, chapter_number: int) -> None:
        super().__init__(
            f"Chapter {chapter_number} in book {_format_book(book)} is out of range.",
            context={"book": book, "chapter": chapter_number},
        )


class VerseNotFoundError(BibleError, LookupError):
    """Raised when a declared verse number is not loaded."""

    def __init__(
        self,
        book: BookRef,
        chapter_number: int,
        verse_number: int,
    ) -> None:
        super().__init__(
            f"Verse {verse_number} in {_format_book(book)} {chapter_number} is out of range.",
            context={
                "book": book,
                "chapter": chapter_number,
                "verse": verse_number,
            },
        )


class ReferenceParseError(BibleError, ValueError):
    """Raised when a reference string cannot be parsed."""

    def __init__(
        self,
        reference: str,
        *,
        context: object | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(
            f'Cannot parse reference: "{reference}"',
            context=context,
            cause=cause,
        )


__all__ = [
    "BibleDataFormatError",
    "BibleDataFormatErrorCode",
    "BibleError",
    "BookNotFoundError",
    "BookRef",
    "ChapterNotFoundError",
    "ReferenceParseError",
    "VerseNotFoundError",
]
