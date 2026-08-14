"""Bible loading, validation, progress, and search-index options."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Callable, ClassVar, TypeAlias


CURRENT_BIBLE_SCHEMA_VERSION = 1


class SearchIndexMode(str, Enum):
    """Controls when a Bible retains its normalized search index."""

    EAGER = "eager"
    LAZY = "lazy"
    DISABLED = "disabled"

    # Cheap source-compatibility aliases for the Dart spelling.
    eager = EAGER
    lazy = LAZY
    disabled = DISABLED

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class BibleDataValidationOptions:
    """Strictness controls for decoded Bible content."""

    require_books: bool = True
    require_chapters: bool = True
    require_verses: bool = True
    require_verse_text: bool = True

    STRICT: ClassVar["BibleDataValidationOptions"]
    PERMISSIVE: ClassVar["BibleDataValidationOptions"]

    def __post_init__(self) -> None:
        for name in (
            "require_books",
            "require_chapters",
            "require_verses",
            "require_verse_text",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a bool")

    def copy_with(
        self,
        *,
        require_books: bool | None = None,
        require_chapters: bool | None = None,
        require_verses: bool | None = None,
        require_verse_text: bool | None = None,
    ) -> "BibleDataValidationOptions":
        """Return a value with selected flags replaced."""

        return BibleDataValidationOptions(
            require_books=self.require_books if require_books is None else require_books,
            require_chapters=(
                self.require_chapters if require_chapters is None else require_chapters
            ),
            require_verses=self.require_verses if require_verses is None else require_verses,
            require_verse_text=(
                self.require_verse_text
                if require_verse_text is None
                else require_verse_text
            ),
        )


BibleDataValidationOptions.STRICT = BibleDataValidationOptions()
BibleDataValidationOptions.PERMISSIVE = BibleDataValidationOptions(
    require_books=False,
    require_chapters=False,
    require_verses=False,
    require_verse_text=False,
)
# Sibling-package spelling retained alongside conventional Python constants.
BibleDataValidationOptions.strict = BibleDataValidationOptions.STRICT  # type: ignore[attr-defined]
BibleDataValidationOptions.permissive = (  # type: ignore[attr-defined]
    BibleDataValidationOptions.PERMISSIVE
)


@dataclass(frozen=True, slots=True)
class BibleLoadOptions:
    """Options shared by synchronous and asynchronous Bible construction."""

    validation: BibleDataValidationOptions = BibleDataValidationOptions.STRICT
    search_index_mode: SearchIndexMode = SearchIndexMode.EAGER
    parse_in_background: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.validation, BibleDataValidationOptions):
            raise TypeError("validation must be BibleDataValidationOptions")
        if not isinstance(self.search_index_mode, SearchIndexMode):
            try:
                object.__setattr__(
                    self,
                    "search_index_mode",
                    SearchIndexMode(self.search_index_mode),
                )
            except (TypeError, ValueError) as error:
                raise TypeError("search_index_mode must be SearchIndexMode") from error
        if not isinstance(self.parse_in_background, bool):
            raise TypeError("parse_in_background must be a bool")

    def copy_with(
        self,
        *,
        validation: BibleDataValidationOptions | None = None,
        search_index_mode: SearchIndexMode | None = None,
        parse_in_background: bool | None = None,
    ) -> "BibleLoadOptions":
        """Return a value with selected options replaced."""

        return BibleLoadOptions(
            validation=self.validation if validation is None else validation,
            search_index_mode=(
                self.search_index_mode
                if search_index_mode is None
                else search_index_mode
            ),
            parse_in_background=(
                self.parse_in_background
                if parse_in_background is None
                else parse_in_background
            ),
        )


class BibleLoadPhase(str, Enum):
    """Stable phase reported while Bible content is loading."""

    READING = "reading"
    PROCESSING = "processing"
    COMPLETE = "complete"

    reading = READING
    processing = PROCESSING
    complete = COMPLETE

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class BibleLoadProgress:
    """A validated progress snapshot suitable for a UI indicator."""

    phase: BibleLoadPhase
    fraction: float
    phase_fraction: float

    def __post_init__(self) -> None:
        if not isinstance(self.phase, BibleLoadPhase):
            try:
                object.__setattr__(self, "phase", BibleLoadPhase(self.phase))
            except (TypeError, ValueError) as error:
                raise TypeError("phase must be BibleLoadPhase") from error

        for name in ("fraction", "phase_fraction"):
            raw_value = getattr(self, name)
            if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
                raise TypeError(f"{name} must be a real number")
            value = float(raw_value)
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be finite and between 0 and 1")
            object.__setattr__(self, name, value)


BibleLoadProgressCallback: TypeAlias = Callable[[BibleLoadProgress], None]


__all__ = [
    "BibleDataValidationOptions",
    "BibleLoadOptions",
    "BibleLoadPhase",
    "BibleLoadProgress",
    "BibleLoadProgressCallback",
    "CURRENT_BIBLE_SCHEMA_VERSION",
    "SearchIndexMode",
]
