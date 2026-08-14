"""Bible loading, navigation, reference resolution, search, and serialization."""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import sys
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from types import MappingProxyType
from typing import Any, Awaitable, Generic, TypeVar, cast, overload

from bible_io_references import (
    BibleBookEnum,
    BibleLanguageEnum,
    BookNameStyle,
    BookPassage,
    ChapterPassage,
    ParseFailure,
    ParseSuccess,
    ParseVerseRefError,
    Passage,
    PassageParser,
    PassageSequence,
    ReferenceFormatter,
    ReferenceParseErrorCode,
    ReferenceParseMetadata,
    ReferenceParser,
    VersePassage,
    VerseRangeRef,
    VerseRef,
)

from .book import Book
from .chapter import Chapter
from .errors import (
    BibleDataFormatError,
    BibleDataFormatErrorCode,
    BibleError,
    BookNotFoundError,
    ChapterNotFoundError,
    VerseNotFoundError,
)
from .json_value import (
    FrozenJsonObject,
    DuplicateJsonKeyError,
    decode_json_with_unique_keys,
    freeze_json_map,
    freeze_json_object,
    json_value_equal,
    json_value_hash,
    thaw_json_value,
)
from .loading import (
    CURRENT_BIBLE_SCHEMA_VERSION,
    BibleDataValidationOptions,
    BibleLoadOptions,
    BibleLoadPhase,
    BibleLoadProgress,
    SearchIndexMode,
)
from .location import BibleLocation, BibleVerseKey
from .result import Failure, Result, Success
from .search import (
    SearchHit,
    SearchMode,
    SearchOptions,
    SearchResults,
    build_search_index_terms,
    find_search_match_ranges,
    fuzzy_match_ranges,
    matches_search_text,
    search_index_lookup_key,
    tokenize_search_text,
)
from .search_index import SearchIndex
from .source import (
    BibleMetadata,
    BibleSource,
    TextDirectionHint,
    merge_bible_metadata,
)
from .verse import Verse


_T = TypeVar("_T")
_RANGE_SEPARATOR_RE = re.compile(r"[-\u2013\u2014\u2015]")
_SIMPLE_JSON_PATH_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_INTEGER_KEY_RE = re.compile(r"^[+-]?\d+$")
_MAX_SIGNED_64 = (1 << 63) - 1

_LEGACY_REFERENCE_ALIASES: Mapping[str, BibleBookEnum] = {
    "ge": BibleBookEnum.Genesis,
    "le": BibleBookEnum.Leviticus,
    "nu": BibleBookEnum.Numbers,
    "sos": BibleBookEnum.SongOfSolomon,
    "songofsongs": BibleBookEnum.SongOfSolomon,
    "da": BibleBookEnum.Daniel,
    "joe": BibleBookEnum.Joel,
    "1thes": BibleBookEnum.FirstThessalonians,
    "2thes": BibleBookEnum.SecondThessalonians,
    "jam": BibleBookEnum.James,
    "estg": BibleBookEnum.EstherAdditions,
    "dan3": BibleBookEnum.DanielSongOfThree,
}

_ROOT_DOCUMENT_FIELDS = frozenset(
    {
        "schemaVersion",
        "bookOrder",
        "books",
        "metadata",
        "source",
        "id",
        "editionId",
        "edition_id",
        "description",
        "summary",
        "language",
        "languageName",
        "language_name",
        "languageCode",
        "language_code",
        "lang",
        "translationName",
        "translation_name",
        "name",
        "title",
        "version",
        "abbreviation",
        "abbr",
        "shortName",
        "short_name",
        "year",
        "direction",
        "textDirection",
        "text_direction",
        "sourceName",
        "source_name",
        "copyright",
        "license",
        "canon",
        "versionDate",
        "version_date",
        "date",
    }
)
_METADATA_DOCUMENT_FIELDS = _ROOT_DOCUMENT_FIELDS - {
    "schemaVersion",
    "bookOrder",
    "books",
}


@dataclass(frozen=True, slots=True)
class EditionVerseRange:
    """Inclusive range ordered according to a loaded edition's canon."""

    start: VerseRef
    end: VerseRef

    def __post_init__(self) -> None:
        if not isinstance(self.start, VerseRef) or not isinstance(self.end, VerseRef):
            raise TypeError("start and end must be VerseRef values")


EditionReference = VerseRef | VerseRangeRef | EditionVerseRange
EditionPassage = Passage | EditionVerseRange


@dataclass(frozen=True, slots=True)
class EditionParsed(Generic[_T]):
    """A parsed value and optional reference-package parse metadata."""

    value: _T
    metadata: ReferenceParseMetadata | None = None


class VerseSelection(Sequence[Verse]):
    """Immutable, edition-ordered resolved verses.

    Passage sequences deliberately retain duplicates; a tuple-backed sequence
    makes that meaning explicit without exposing mutation methods.
    """

    __slots__ = ("_verses",)

    def __init__(self, verses: Iterable[Verse] = ()) -> None:
        self._verses = tuple(verses)

    @overload
    def __getitem__(self, index: int) -> Verse:
        ...

    @overload
    def __getitem__(self, index: slice) -> tuple[Verse, ...]:
        ...

    def __getitem__(self, index: int | slice) -> Verse | tuple[Verse, ...]:
        return self._verses[index]

    def __len__(self) -> int:
        return len(self._verses)

    def __iter__(self) -> Iterator[Verse]:
        return iter(self._verses)

    def __reversed__(self) -> Iterator[Verse]:
        return reversed(self._verses)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, VerseSelection):
            return self._verses == other._verses
        if isinstance(other, Sequence):
            return self._verses == tuple(other)
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._verses)

    def __repr__(self) -> str:
        return f"VerseSelection({self._verses!r})"

    @property
    def verses(self) -> tuple[Verse, ...]:
        return self._verses

    @property
    def first(self) -> Verse | None:
        return self._verses[0] if self._verses else None

    @property
    def last(self) -> Verse | None:
        return self._verses[-1] if self._verses else None


@dataclass(frozen=True, slots=True)
class BibleReferenceResult:
    """Shape-preserving result of resolving one verse or a verse range."""

    verse: Verse | None = None
    selection: VerseSelection | None = None

    def __post_init__(self) -> None:
        if (self.verse is None) == (self.selection is None):
            raise ValueError("exactly one of verse or selection must be supplied")

    @classmethod
    def from_verse(cls, verse: Verse) -> BibleReferenceResult:
        return cls(verse=verse)

    @classmethod
    def from_selection(cls, verses: Iterable[Verse]) -> BibleReferenceResult:
        return cls(selection=VerseSelection(verses))

    @property
    def is_verse(self) -> bool:
        return self.verse is not None

    @property
    def is_range(self) -> bool:
        return self.selection is not None

    def as_verse(self) -> Verse | None:
        return self.verse

    def as_range(self) -> VerseSelection | None:
        return self.selection


@dataclass(frozen=True, slots=True)
class BibleStats:
    book_count: int
    chapter_count: int
    verse_count: int
    total_words: int
    average_verse_length: int
    verses_per_book: Mapping[BibleBookEnum, int]

    def __hash__(self) -> int:
        return hash(
            (
                self.book_count,
                self.chapter_count,
                self.verse_count,
                self.total_words,
                self.average_verse_length,
                frozenset(self.verses_per_book.items()),
            )
        )


@dataclass(frozen=True, slots=True)
class BiblePerformanceMetrics:
    load_time: timedelta
    search_index_size: int
    search_index_built: bool
    verse_count: int
    posting_count: int
    text_bytes: int
    text_characters: int
    text_utf16_code_units: int
    memory_usage_kib: int

    @property
    def memory_usage(self) -> int:
        """Compatibility alias for the estimated retained memory in KiB."""

        return self.memory_usage_kib

    @property
    def text_code_units(self) -> int:
        """Compatibility alias for the UTF-16 units reported by Dart."""

        return self.text_utf16_code_units


@dataclass(frozen=True, slots=True)
class BibleInitializationData:
    books: Sequence[Book]
    language: BibleLanguageEnum = BibleLanguageEnum.AUTO
    metadata: BibleMetadata | None = None
    schema_version: int = CURRENT_BIBLE_SCHEMA_VERSION
    annotations: Mapping[str, Any] | None = None
    search_index: Mapping[str, Sequence[Verse]] | None = None
    search_index_mode: SearchIndexMode = SearchIndexMode.EAGER


class Bible:
    """Validated, edition-aware in-memory Bible content.

    ``Bible(path)`` remains the compact compatibility constructor. Alternate
    constructors accept UTF-8 bytes, JSON strings, decoded mappings, or direct
    model values.
    """

    def __init__(
        self,
        input_path: str | Path,
        *,
        source: BibleSource | None = None,
        options: BibleLoadOptions | None = None,
        on_load_progress: Callable[[BibleLoadProgress], None] | None = None,
        on_progress: Callable[[float], None] | None = None,
    ) -> None:
        load_options = options or BibleLoadOptions()
        started = perf_counter()
        self._report_progress(
            on_load_progress,
            BibleLoadPhase.READING,
            0.0,
            0.0,
            None,
        )
        raw = self._read_path_bytes(
            input_path,
            on_load_progress=on_load_progress,
            on_progress=on_progress,
        )
        self._report_progress(
            on_load_progress,
            BibleLoadPhase.PROCESSING,
            0.65,
            0.0,
            None,
        )
        initialization = self._initialization_from_bytes(
            raw, source=source, options=load_options
        )
        self._initialize(initialization)
        self._load_time = timedelta(seconds=perf_counter() - started)
        self._report_progress(
            on_load_progress,
            BibleLoadPhase.PROCESSING,
            1.0,
            1.0,
            None,
        )
        self._report_progress(
            on_load_progress,
            BibleLoadPhase.COMPLETE,
            1.0,
            1.0,
            on_progress,
        )

    @classmethod
    def _read_path_bytes(
        cls,
        input_path: str | Path,
        *,
        on_load_progress: Callable[[BibleLoadProgress], None] | None,
        on_progress: Callable[[float], None] | None,
    ) -> bytes:
        """Read one file incrementally and report its read-stage progress."""

        path = Path(input_path)
        expected_size = path.stat().st_size
        buffer = bytearray()
        last_read_fraction = 0.0
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                buffer.extend(chunk)
                last_read_fraction = (
                    min(len(buffer) / expected_size, 1.0)
                    if expected_size
                    else 1.0
                )
                cls._report_progress(
                    on_load_progress,
                    BibleLoadPhase.READING,
                    0.65 * last_read_fraction,
                    last_read_fraction,
                    on_progress,
                )
        if last_read_fraction < 1.0:
            cls._report_progress(
                on_load_progress,
                BibleLoadPhase.READING,
                0.65,
                1.0,
                on_progress,
            )
        return bytes(buffer)

    @classmethod
    def load(
        cls,
        input_path: str | Path,
        *,
        source: BibleSource | None = None,
        options: BibleLoadOptions | None = None,
        on_load_progress: Callable[[BibleLoadProgress], None] | None = None,
        on_progress: Callable[[float], None] | None = None,
    ) -> Bible:
        """Load a Bible synchronously from a JSON file."""

        return cls(
            input_path,
            source=source,
            options=options,
            on_load_progress=on_load_progress,
            on_progress=on_progress,
        )

    @classmethod
    async def load_async(
        cls,
        input_path: str | Path,
        *,
        source: BibleSource | None = None,
        options: BibleLoadOptions | None = None,
        on_load_progress: Callable[[BibleLoadProgress], None] | None = None,
        on_progress: Callable[[float], None] | None = None,
    ) -> Bible:
        """Load asynchronously, using a worker when configured to do so."""

        load_options = options or BibleLoadOptions()
        if load_options.parse_in_background:
            return await asyncio.to_thread(
                cls.load,
                input_path,
                source=source,
                options=load_options,
                on_load_progress=on_load_progress,
                on_progress=on_progress,
            )
        started = perf_counter()
        cls._report_progress(
            on_load_progress,
            BibleLoadPhase.READING,
            0.0,
            0.0,
            None,
        )
        raw = await asyncio.to_thread(
            cls._read_path_bytes,
            input_path,
            on_load_progress=on_load_progress,
            on_progress=on_progress,
        )
        cls._report_progress(
            on_load_progress,
            BibleLoadPhase.PROCESSING,
            0.65,
            0.0,
            None,
        )
        initialization = cls._initialization_from_bytes(
            raw,
            source=source,
            options=load_options,
        )
        instance = cls.__new__(cls)
        instance._initialize(initialization)
        instance._load_time = timedelta(seconds=perf_counter() - started)
        cls._report_progress(
            on_load_progress,
            BibleLoadPhase.PROCESSING,
            1.0,
            1.0,
            None,
        )
        cls._report_progress(
            on_load_progress,
            BibleLoadPhase.COMPLETE,
            1.0,
            1.0,
            on_progress,
        )
        return instance

    @classmethod
    async def load_asset(
        cls,
        asset_bundle: object,
        key: str,
        *,
        source: BibleSource | None = None,
        options: BibleLoadOptions | None = None,
        on_load_progress: Callable[[BibleLoadProgress], None] | None = None,
        on_progress: Callable[[float], None] | None = None,
    ) -> Bible:
        """Load JSON text from an async or synchronous asset-bundle adapter."""

        if not isinstance(key, str) or not key.strip():
            raise ValueError("key must be a non-blank string")
        started = perf_counter()
        cls._report_progress(
            on_load_progress,
            BibleLoadPhase.READING,
            0.0,
            0.0,
            None,
        )
        loader = getattr(asset_bundle, "load_string", None) or getattr(
            asset_bundle,
            "loadString",
            None,
        )
        if not callable(loader):
            raise TypeError("asset_bundle must provide load_string(key)")
        loaded = loader(key)
        if inspect.isawaitable(loaded):
            loaded = await cast(Awaitable[object], loaded)
        if not isinstance(loaded, str):
            raise BibleDataFormatError(
                code=BibleDataFormatErrorCode.INVALID_TYPE,
                path="$",
                message="Asset bundle load_string must return a string.",
                value=loaded,
            )
        cls._report_progress(
            on_load_progress,
            BibleLoadPhase.READING,
            0.65,
            1.0,
            on_progress,
        )
        cls._report_progress(
            on_load_progress,
            BibleLoadPhase.PROCESSING,
            0.65,
            0.0,
            None,
        )
        instance = await cls.from_json_async(
            loaded,
            source=source,
            options=options,
        )
        instance._load_time = timedelta(seconds=perf_counter() - started)
        cls._report_progress(
            on_load_progress,
            BibleLoadPhase.PROCESSING,
            1.0,
            1.0,
            None,
        )
        cls._report_progress(
            on_load_progress,
            BibleLoadPhase.COMPLETE,
            1.0,
            1.0,
            on_progress,
        )
        return instance

    @classmethod
    def from_json(
        cls,
        json_string: str,
        *,
        source: BibleSource | None = None,
        options: BibleLoadOptions | None = None,
    ) -> Bible:
        """Create a Bible from a JSON string."""

        started = perf_counter()
        if not isinstance(json_string, str):
            raise TypeError("json_string must be a string")
        try:
            decoded = decode_json_with_unique_keys(json_string)
        except DuplicateJsonKeyError as exc:
            raise BibleDataFormatError(
                code=BibleDataFormatErrorCode.DUPLICATE_KEY,
                path="$",
                message=f"Bible JSON repeats object key {exc.key!r}.",
                value=exc.key,
                cause=exc,
            ) from exc
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise BibleDataFormatError(
                code=BibleDataFormatErrorCode.INVALID_JSON,
                path="$",
                message="Bible content is not valid JSON.",
                cause=exc,
            ) from exc
        instance = cls.from_decoded_json(decoded, source=source, options=options)
        instance._load_time = timedelta(seconds=perf_counter() - started)
        return instance

    @classmethod
    async def from_json_async(
        cls,
        json_string: str,
        *,
        source: BibleSource | None = None,
        options: BibleLoadOptions | None = None,
    ) -> Bible:
        """Decode asynchronously, using a worker when configured to do so."""

        load_options = options or BibleLoadOptions()
        if not load_options.parse_in_background:
            return cls.from_json(
                json_string,
                source=source,
                options=load_options,
            )
        return await asyncio.to_thread(
            cls.from_json,
            json_string,
            source=source,
            options=load_options,
        )

    @classmethod
    def from_utf8_bytes(
        cls,
        data: bytes | bytearray | memoryview,
        *,
        source: BibleSource | None = None,
        options: BibleLoadOptions | None = None,
    ) -> Bible:
        """Create a Bible from UTF-8 encoded JSON bytes."""

        started = perf_counter()
        initialization = cls._initialization_from_bytes(
            bytes(data), source=source, options=options or BibleLoadOptions()
        )
        instance = cls.__new__(cls)
        instance._initialize(initialization)
        instance._load_time = timedelta(seconds=perf_counter() - started)
        return instance

    from_bytes = from_utf8_bytes

    @classmethod
    def from_decoded_json(
        cls,
        data: object,
        *,
        source: BibleSource | None = None,
        options: BibleLoadOptions | None = None,
    ) -> Bible:
        """Create a Bible from an already-decoded JSON object."""

        started = perf_counter()
        initialization = cls._parse_document(
            data, source=source, options=options or BibleLoadOptions()
        )
        instance = cls.__new__(cls)
        instance._initialize(initialization)
        instance._load_time = timedelta(seconds=perf_counter() - started)
        return instance

    from_dict = from_decoded_json

    @classmethod
    def from_books(
        cls,
        books: Iterable[Book],
        *,
        language: BibleLanguageEnum = BibleLanguageEnum.ENGLISH,
        metadata: BibleMetadata | None = None,
        source: BibleSource | None = None,
        schema_version: int = CURRENT_BIBLE_SCHEMA_VERSION,
        annotations: Mapping[str, Any] | None = None,
        validation: BibleDataValidationOptions = (
            BibleDataValidationOptions.STRICT
        ),
        search_index_mode: SearchIndexMode = SearchIndexMode.EAGER,
    ) -> Bible:
        """Create a Bible directly from validated model values."""

        started = perf_counter()
        if schema_version != CURRENT_BIBLE_SCHEMA_VERSION:
            raise ValueError(
                f"only schema version {CURRENT_BIBLE_SCHEMA_VERSION} is supported"
            )
        if not isinstance(language, BibleLanguageEnum):
            raise TypeError("language must be a BibleLanguageEnum")
        if not isinstance(validation, BibleDataValidationOptions):
            raise TypeError("validation must be BibleDataValidationOptions")
        book_values = tuple(books)
        if validation.require_books and not book_values:
            raise ValueError("books must contain at least one Book")
        for book in book_values:
            if not isinstance(book, Book):
                raise TypeError("books must contain only Book objects")
            if validation.require_chapters and not book.chapters:
                raise ValueError(
                    f"{book.book_enum.full_name} must contain a chapter"
                )
            for chapter in book.chapters:
                if validation.require_verses and not chapter.verses:
                    raise ValueError(
                        f"{chapter.reference} must contain a verse"
                    )
                if validation.require_verse_text and any(
                    not verse.text.strip() for verse in chapter.verses
                ):
                    raise ValueError(
                        f"{chapter.reference} contains blank verse text"
                    )
        merged_metadata = merge_bible_metadata(
            metadata=metadata,
            source=source,
            fallback_language_name=str(language),
            fallback_language_code=None if language is BibleLanguageEnum.AUTO else language.code,
        )
        instance = cls.__new__(cls)
        instance._initialize(
            BibleInitializationData(
                books=book_values,
                language=language,
                metadata=merged_metadata,
                schema_version=schema_version,
                annotations=annotations,
                search_index_mode=SearchIndexMode(search_index_mode),
            )
        )
        instance._load_time = timedelta(seconds=perf_counter() - started)
        return instance

    @staticmethod
    def _report_progress(
        callback: Callable[[BibleLoadProgress], None] | None,
        phase: BibleLoadPhase,
        fraction: float,
        phase_fraction: float,
        scalar_callback: Callable[[float], None] | None = None,
    ) -> None:
        if callback is not None:
            callback(
                BibleLoadProgress(
                    phase=phase,
                    fraction=fraction,
                    phase_fraction=phase_fraction,
                )
            )
        if scalar_callback is not None:
            scalar_callback(fraction)

    @classmethod
    def _initialization_from_bytes(
        cls,
        data: bytes,
        *,
        source: BibleSource | None,
        options: BibleLoadOptions,
    ) -> BibleInitializationData:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise BibleDataFormatError(
                code=BibleDataFormatErrorCode.INVALID_JSON,
                path="$",
                message="Bible content is not valid UTF-8 JSON.",
                cause=exc,
            ) from exc
        try:
            decoded = decode_json_with_unique_keys(text)
        except DuplicateJsonKeyError as exc:
            raise BibleDataFormatError(
                code=BibleDataFormatErrorCode.DUPLICATE_KEY,
                path="$",
                message=f"Bible JSON repeats object key {exc.key!r}.",
                value=exc.key,
                cause=exc,
            ) from exc
        except json.JSONDecodeError as exc:
            raise BibleDataFormatError(
                code=BibleDataFormatErrorCode.INVALID_JSON,
                path="$",
                message="Bible content is not valid JSON.",
                cause=exc,
            ) from exc
        return cls._parse_document(decoded, source=source, options=options)

    @classmethod
    def _parse_document(
        cls,
        value: object,
        *,
        source: BibleSource | None,
        options: BibleLoadOptions,
    ) -> BibleInitializationData:
        if not isinstance(value, Mapping):
            raise BibleDataFormatError(
                code=BibleDataFormatErrorCode.INVALID_TYPE,
                path="$",
                message="Bible JSON must have an object at its root.",
                value=value,
            )
        data = cls._string_mapping(value, "$", "Bible JSON object keys must be strings.")
        schema_version = cls._read_schema_version(data)
        # Metadata understands both legacy root-level fields and the schema-v1
        # nested object. Feed it only those fields: structural keys and root
        # extension annotations belong to the Bible document itself.
        metadata = BibleMetadata.from_decoded_json(
            {
                key: item
                for key, item in data.items()
                if key in _METADATA_DOCUMENT_FIELDS
            },
            source=source,
        )
        language = cls._resolve_language(data.get("language"), metadata)
        validation = options.validation

        has_books = "books" in data
        raw_books = data.get("books")
        if not has_books:
            if validation.require_books:
                raise BibleDataFormatError(
                    code=BibleDataFormatErrorCode.MISSING_FIELD,
                    path="$.books",
                    message="Bible content must declare a books object.",
                )
            books_data: dict[str, object] = {}
        elif not isinstance(raw_books, Mapping):
            raise BibleDataFormatError(
                code=BibleDataFormatErrorCode.INVALID_TYPE,
                path="$.books",
                message="Bible books must be an object.",
                value=raw_books,
            )
        else:
            books_data = cls._string_mapping(
                raw_books, "$.books", "Bible book keys must be strings."
            )

        if validation.require_books and not books_data:
            raise BibleDataFormatError(
                code=BibleDataFormatErrorCode.INVALID_VALUE,
                path="$.books",
                message="Bible content must contain at least one book.",
                value=raw_books,
            )

        parsed_books: dict[BibleBookEnum, Book] = {}
        for identifier, raw_book in books_data.items():
            path = cls._json_path("$.books", identifier)
            book_enum = cls._read_book_identifier(identifier, path)
            if book_enum in parsed_books:
                raise BibleDataFormatError(
                    code=BibleDataFormatErrorCode.INVALID_VALUE,
                    path=path,
                    message="The same Bible book is declared more than once.",
                    value=identifier,
                )
            parsed_books[book_enum] = cls._read_book(
                book_enum, raw_book, path, validation
            )

        order = cls._read_book_order(
            data.get("bookOrder"),
            parsed_books,
            is_present="bookOrder" in data,
        )
        books = tuple(parsed_books[item] for item in order)
        cls._validate_book_aliases(books, error_path="$.books")

        root_annotations = cls._freeze_annotations(
            {key: item for key, item in data.items() if key not in _ROOT_DOCUMENT_FIELDS},
            path="$",
        )
        return BibleInitializationData(
            books=books,
            language=language,
            metadata=metadata,
            schema_version=schema_version,
            annotations=root_annotations,
            search_index_mode=options.search_index_mode,
        )

    @staticmethod
    def _read_schema_version(data: Mapping[str, object]) -> int:
        if "schemaVersion" not in data:
            return CURRENT_BIBLE_SCHEMA_VERSION
        raw = data["schemaVersion"]
        if not isinstance(raw, int) or isinstance(raw, bool):
            raise BibleDataFormatError(
                code=BibleDataFormatErrorCode.INVALID_TYPE,
                path="$.schemaVersion",
                message="schemaVersion must be an integer.",
                value=raw,
            )
        if raw != CURRENT_BIBLE_SCHEMA_VERSION:
            raise BibleDataFormatError(
                code=BibleDataFormatErrorCode.INVALID_VALUE,
                path="$.schemaVersion",
                message=(
                    f"Unsupported Bible schema version {raw}; supported version: "
                    f"{CURRENT_BIBLE_SCHEMA_VERSION}."
                ),
                value=raw,
            )
        return raw

    @classmethod
    def _read_book(
        cls,
        book: BibleBookEnum,
        raw_book: object,
        path: str,
        validation: BibleDataValidationOptions,
    ) -> Book:
        if not isinstance(raw_book, Mapping):
            raise BibleDataFormatError(
                code=BibleDataFormatErrorCode.INVALID_TYPE,
                path=path,
                message="A Bible book must be an object.",
                value=raw_book,
            )
        book_data = cls._string_mapping(raw_book, path, "Book keys must be strings.")
        raw_name = book_data.get("name")
        if raw_name is not None and (
            not isinstance(raw_name, str) or not raw_name.strip()
        ):
            raise BibleDataFormatError(
                code=(
                    BibleDataFormatErrorCode.INVALID_VALUE
                    if isinstance(raw_name, str)
                    else BibleDataFormatErrorCode.INVALID_TYPE
                ),
                path=f"{path}.name",
                message="Book name must be a non-blank string.",
                value=raw_name,
            )

        has_chapters = "chapters" in book_data
        raw_chapters = book_data.get("chapters")
        if not has_chapters:
            if validation.require_chapters:
                raise BibleDataFormatError(
                    code=BibleDataFormatErrorCode.MISSING_FIELD,
                    path=f"{path}.chapters",
                    message="A Bible book must declare chapters.",
                )
            chapters_data: dict[str, object] = {}
        else:
            chapters_data = cls._numeric_container(
                raw_chapters,
                f"{path}.chapters",
                "Book chapters must be an object or array.",
            )
        if validation.require_chapters and not chapters_data:
            raise BibleDataFormatError(
                code=BibleDataFormatErrorCode.INVALID_VALUE,
                path=f"{path}.chapters",
                message="A Bible book must contain at least one chapter.",
                value=raw_chapters,
            )

        chapters: list[Chapter] = []
        seen: set[int] = set()
        for key, raw_chapter in chapters_data.items():
            chapter_path = cls._json_path(f"{path}.chapters", key)
            number = cls._positive_numeric_key(key, chapter_path)
            if number in seen:
                raise BibleDataFormatError(
                    code=BibleDataFormatErrorCode.INVALID_VALUE,
                    path=chapter_path,
                    message=f"Duplicate numeric chapter number {number}.",
                    value=key,
                )
            seen.add(number)
            chapters.append(
                cls._read_chapter(
                    book, number, raw_chapter, chapter_path, validation
                )
            )
        annotations = cls._freeze_annotations(
            {key: item for key, item in book_data.items() if key not in {"name", "chapters"}},
            path=path,
        )
        try:
            return Book(
                book,
                chapters,
                name=raw_name if isinstance(raw_name, str) else None,
                annotations=annotations,
            )
        except (TypeError, ValueError) as exc:
            raise BibleDataFormatError(
                code=BibleDataFormatErrorCode.INVALID_VALUE,
                path=path,
                message="Bible book data violates model invariants.",
                cause=exc,
            ) from exc

    @classmethod
    def _read_chapter(
        cls,
        book: BibleBookEnum,
        chapter_number: int,
        raw_chapter: object,
        path: str,
        validation: BibleDataValidationOptions,
    ) -> Chapter:
        if isinstance(raw_chapter, Sequence) and not isinstance(
            raw_chapter, (str, bytes, bytearray)
        ):
            chapter_data: dict[str, object] = {
                str(index): item for index, item in enumerate(raw_chapter, start=1)
            }
            structured = False
            raw_verses: object = raw_chapter
            verses_path = path
        elif isinstance(raw_chapter, Mapping):
            chapter_data = cls._string_mapping(
                raw_chapter, path, "Chapter keys must be strings."
            )
            structured = "verses" in chapter_data
            raw_verses = chapter_data.get("verses") if structured else chapter_data
            verses_path = f"{path}.verses" if structured else path
        else:
            raise BibleDataFormatError(
                code=BibleDataFormatErrorCode.INVALID_TYPE,
                path=path,
                message="A Bible chapter must be an object or array.",
                value=raw_chapter,
            )

        verses_data = cls._numeric_container(
            raw_verses,
            verses_path,
            "Chapter verses must be an object or array.",
        )
        if validation.require_verses and not verses_data:
            raise BibleDataFormatError(
                code=BibleDataFormatErrorCode.INVALID_VALUE,
                path=verses_path,
                message="A Bible chapter must contain at least one verse.",
                value=raw_verses,
            )
        verses: list[Verse] = []
        seen: set[int] = set()
        for key, raw_verse in verses_data.items():
            verse_path = cls._json_path(verses_path, key)
            number = cls._positive_numeric_key(key, verse_path)
            if number in seen:
                raise BibleDataFormatError(
                    code=BibleDataFormatErrorCode.INVALID_VALUE,
                    path=verse_path,
                    message=f"Duplicate numeric verse number {number}.",
                    value=key,
                )
            seen.add(number)
            verses.append(
                cls._read_verse(
                    book,
                    chapter_number,
                    number,
                    raw_verse,
                    verse_path,
                    validation,
                )
            )
        annotations = (
            cls._freeze_annotations(
                {key: item for key, item in chapter_data.items() if key != "verses"},
                path=path,
            )
            if structured
            else freeze_json_map({})
        )
        try:
            return Chapter(
                book,
                chapter_number,
                verses,
                annotations=annotations,
            )
        except (TypeError, ValueError) as exc:
            raise BibleDataFormatError(
                code=BibleDataFormatErrorCode.INVALID_VALUE,
                path=path,
                message="Bible chapter data violates model invariants.",
                cause=exc,
            ) from exc

    @classmethod
    def _read_verse(
        cls,
        book: BibleBookEnum,
        chapter_number: int,
        verse_number: int,
        raw_verse: object,
        path: str,
        validation: BibleDataValidationOptions,
    ) -> Verse:
        annotations: Mapping[str, Any]
        if isinstance(raw_verse, str):
            text = raw_verse
            annotations = freeze_json_map({})
        elif isinstance(raw_verse, Mapping):
            verse_data = cls._string_mapping(
                raw_verse, path, "Verse annotation keys must be strings."
            )
            if "text" not in verse_data:
                raise BibleDataFormatError(
                    code=BibleDataFormatErrorCode.MISSING_FIELD,
                    path=f"{path}.text",
                    message="An annotated verse must declare text.",
                )
            raw_text = verse_data["text"]
            if not isinstance(raw_text, str):
                raise BibleDataFormatError(
                    code=BibleDataFormatErrorCode.INVALID_TYPE,
                    path=f"{path}.text",
                    message="Verse text must be a string.",
                    value=raw_text,
                )
            text = raw_text
            annotations = cls._freeze_annotations(
                {key: item for key, item in verse_data.items() if key != "text"},
                path=path,
            )
        else:
            raise BibleDataFormatError(
                code=BibleDataFormatErrorCode.INVALID_TYPE,
                path=path,
                message="A verse must be a string or an object containing text.",
                value=raw_verse,
            )
        if validation.require_verse_text and not text.strip():
            raise BibleDataFormatError(
                code=BibleDataFormatErrorCode.INVALID_VALUE,
                path=f"{path}.text" if isinstance(raw_verse, Mapping) else path,
                message="Verse text must not be blank.",
                value=text,
            )
        try:
            return Verse(
                book,
                chapter_number,
                verse_number,
                text,
                annotations=annotations,
            )
        except (TypeError, ValueError) as exc:
            raise BibleDataFormatError(
                code=BibleDataFormatErrorCode.INVALID_VALUE,
                path=path,
                message="Bible verse data violates model invariants.",
                cause=exc,
            ) from exc

    @classmethod
    def _read_book_order(
        cls,
        raw_order: object,
        books: Mapping[BibleBookEnum, Book],
        *,
        is_present: bool,
    ) -> tuple[BibleBookEnum, ...]:
        if not is_present:
            canonical = {book: index for index, book in enumerate(BibleBookEnum)}
            return tuple(sorted(books, key=canonical.__getitem__))
        if not isinstance(raw_order, Sequence) or isinstance(
            raw_order, (str, bytes, bytearray)
        ):
            raise BibleDataFormatError(
                code=BibleDataFormatErrorCode.INVALID_TYPE,
                path="$.bookOrder",
                message="bookOrder must be an array of book identifiers.",
                value=raw_order,
            )
        order: list[BibleBookEnum] = []
        seen: set[BibleBookEnum] = set()
        for index, value in enumerate(raw_order):
            path = f"$.bookOrder[{index}]"
            if not isinstance(value, str) or not value.strip():
                raise BibleDataFormatError(
                    code=(
                        BibleDataFormatErrorCode.INVALID_VALUE
                        if isinstance(value, str)
                        else BibleDataFormatErrorCode.INVALID_TYPE
                    ),
                    path=path,
                    message="Each bookOrder item must be a non-blank string.",
                    value=value,
                )
            book = cls._read_book_identifier(value, path)
            if book not in books:
                raise BibleDataFormatError(
                    code=BibleDataFormatErrorCode.INVALID_VALUE,
                    path=path,
                    message="bookOrder references a book that is not loaded.",
                    value=value,
                )
            if book in seen:
                raise BibleDataFormatError(
                    code=BibleDataFormatErrorCode.INVALID_VALUE,
                    path=path,
                    message="bookOrder contains a duplicate book.",
                    value=value,
                )
            seen.add(book)
            order.append(book)
        if len(order) != len(books):
            missing = [book.as_str() for book in books if book not in seen]
            raise BibleDataFormatError(
                code=BibleDataFormatErrorCode.INVALID_VALUE,
                path="$.bookOrder",
                message="bookOrder must list every loaded book exactly once.",
                value=missing,
            )
        return tuple(order)

    @staticmethod
    def _read_book_identifier(value: str, path: str) -> BibleBookEnum:
        if not value.strip():
            raise BibleDataFormatError(
                code=BibleDataFormatErrorCode.INVALID_VALUE,
                path=path,
                message="Bible book identifiers must not be blank.",
                value=value,
            )
        try:
            return BibleBookEnum.parse(value)
        except (TypeError, ValueError) as exc:
            raise BibleDataFormatError(
                code=BibleDataFormatErrorCode.INVALID_VALUE,
                path=path,
                message="Unsupported Bible book identifier.",
                value=value,
                cause=exc,
            ) from exc

    @staticmethod
    def _positive_numeric_key(value: str, path: str) -> int:
        stripped = value.strip()
        if not _INTEGER_KEY_RE.fullmatch(stripped):
            parsed = None
        else:
            try:
                parsed = int(stripped)
            except ValueError:
                parsed = None
        if parsed is None or parsed < 1 or parsed > _MAX_SIGNED_64:
            raise BibleDataFormatError(
                code=BibleDataFormatErrorCode.INVALID_VALUE,
                path=path,
                message="Chapter and verse keys must be positive integers.",
                value=value,
            )
        return parsed

    @classmethod
    def _numeric_container(
        cls, value: object, path: str, message: str
    ) -> dict[str, object]:
        if isinstance(value, Mapping):
            return cls._string_mapping(value, path, "JSON object keys must be strings.")
        if isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            return {str(index): item for index, item in enumerate(value, start=1)}
        raise BibleDataFormatError(
            code=BibleDataFormatErrorCode.INVALID_TYPE,
            path=path,
            message=message,
            value=value,
        )

    @staticmethod
    def _string_mapping(
        value: Mapping[object, object], path: str, message: str
    ) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise BibleDataFormatError(
                    code=BibleDataFormatErrorCode.NON_JSON_VALUE,
                    path=path,
                    message=message,
                    value=key,
                )
            result[key] = item
        return result

    @staticmethod
    def _freeze_annotations(
        values: Mapping[str, object], *, path: str
    ) -> Mapping[str, Any]:
        try:
            return freeze_json_map(values)
        except (TypeError, ValueError) as exc:
            raise BibleDataFormatError(
                code=BibleDataFormatErrorCode.NON_JSON_VALUE,
                path=path,
                message="Additional content fields must be JSON-compatible.",
                cause=exc,
            ) from exc

    @staticmethod
    def _json_path(base: str, key: str) -> str:
        if _SIMPLE_JSON_PATH_KEY_RE.fullmatch(key):
            return f"{base}.{key}"
        return f"{base}[{json.dumps(key, ensure_ascii=False)}]"

    @staticmethod
    def _resolve_language(
        raw_language: object, metadata: BibleMetadata
    ) -> BibleLanguageEnum:
        if raw_language is not None and not isinstance(raw_language, str):
            raise BibleDataFormatError(
                code=BibleDataFormatErrorCode.INVALID_TYPE,
                path="$.language",
                message="Bible language must be a string.",
                value=raw_language,
            )
        for candidate in (
            raw_language,
            metadata.language_code,
            metadata.language_name,
        ):
            if not isinstance(candidate, str) or not candidate.strip():
                continue
            try:
                return BibleLanguageEnum.from_str(candidate)
            except ValueError:
                continue
        return BibleLanguageEnum.AUTO

    @staticmethod
    def _normalize_alias(value: str) -> str:
        return " ".join(value.split()).casefold()

    @classmethod
    def _validate_book_aliases(
        cls, books: Sequence[Book], *, error_path: str | None = None
    ) -> None:
        owners: dict[str, BibleBookEnum] = {}
        for book in books:
            for term in (book.book_enum.full_name, book.book_enum.as_str(), book.name):
                normalized = cls._normalize_alias(term)
                existing = owners.get(normalized)
                if existing is not None and existing is not book.book_enum:
                    error = ValueError(
                        f"reference alias {term!r} conflicts between "
                        f"{existing.full_name} and {book.book_enum.full_name}"
                    )
                    if error_path is not None:
                        raise BibleDataFormatError(
                            code=BibleDataFormatErrorCode.INVALID_VALUE,
                            path=error_path,
                            message="Loaded book names create an ambiguous reference alias.",
                            cause=error,
                        ) from error
                    raise error
                owners[normalized] = book.book_enum

    def _initialize(self, data: BibleInitializationData) -> None:
        books = tuple(data.books)
        if any(not isinstance(book, Book) for book in books):
            raise TypeError("books must contain only Book objects")
        if not isinstance(data.language, BibleLanguageEnum):
            raise TypeError("language must be a BibleLanguageEnum")
        if (
            not isinstance(data.schema_version, int)
            or isinstance(data.schema_version, bool)
            or data.schema_version != CURRENT_BIBLE_SCHEMA_VERSION
        ):
            raise ValueError(
                f"only schema version {CURRENT_BIBLE_SCHEMA_VERSION} is supported"
            )
        if data.metadata is not None and not isinstance(
            data.metadata, BibleMetadata
        ):
            raise TypeError("metadata must be BibleMetadata or None")
        self._validate_book_aliases(books)
        by_enum = {book.book_enum: book for book in books}
        if len(by_enum) != len(books):
            raise ValueError("Bible books must have unique book identifiers")
        self._books = books
        self._language = data.language
        self._metadata = data.metadata or merge_bible_metadata(
            fallback_language_name=str(data.language),
            fallback_language_code=(
                None if data.language is BibleLanguageEnum.AUTO else data.language.code
            ),
        )
        self._schema_version = data.schema_version
        self._annotations = freeze_json_object(
            data.annotations,
            reserved_keys=_ROOT_DOCUMENT_FIELDS,
            parameter_name="annotations",
        )
        self._search_index_mode = SearchIndexMode(data.search_index_mode)
        self._books_by_enum = by_enum
        self._book_positions = {
            book.book_enum: index for index, book in enumerate(self.books)
        }
        self._all_verses = tuple(
            verse
            for book in self.books
            for chapter in book.chapters
            for verse in chapter.verses
        )
        self._verse_positions = {
            (verse.book, verse.chapter_number, verse.verse_number): index
            for index, verse in enumerate(self._all_verses)
        }
        self._created_at = datetime.now(timezone.utc)
        self._load_time = timedelta(0)
        self._search_index: dict[str, tuple[Verse, ...]] | None = None
        if (
            self.search_index_mode is not SearchIndexMode.DISABLED
            and data.search_index is not None
        ):
            self._search_index = {
                key: tuple(verses) for key, verses in data.search_index.items()
            }
        elif self.search_index_mode is SearchIndexMode.EAGER:
            self._search_index = self._build_search_index()
        self._reference_parser = self._build_reference_parser()
        self._passage_parser = PassageParser(
            reference_parser=self._reference_parser
        )

    def _build_reference_parser(self) -> ReferenceParser:
        aliases: dict[str, BibleBookEnum] = dict(_LEGACY_REFERENCE_ALIASES)
        for book in self.books:
            if self._normalize_alias(book.name) != self._normalize_alias(
                book.book_enum.full_name
            ):
                aliases[book.name] = book.book_enum
        if self.language is BibleLanguageEnum.AUTO:
            return ReferenceParser(aliases=aliases)
        return ReferenceParser(
            aliases_by_language={self.language: aliases},
            preferred_languages=(self.language,),
        )

    @property
    def books(self) -> tuple[Book, ...]:
        return self._books

    @property
    def language(self) -> BibleLanguageEnum:
        return self._language

    @property
    def metadata(self) -> BibleMetadata:
        return self._metadata

    @property
    def schema_version(self) -> int:
        return self._schema_version

    @property
    def annotations(self) -> FrozenJsonObject:
        return self._annotations

    @property
    def search_index_mode(self) -> SearchIndexMode:
        return self._search_index_mode

    @property
    def reference_parser(self) -> ReferenceParser:
        return self._reference_parser

    @property
    def passage_parser(self) -> PassageParser:
        return self._passage_parser

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def source(self) -> BibleSource | None:
        return self.metadata.source

    @property
    def id(self) -> str | None:
        return self.metadata.id

    @property
    def name(self) -> str | None:
        return self.metadata.translation_name

    @property
    def description(self) -> str | None:
        return self.metadata.description

    @property
    def language_name(self) -> str | None:
        return self.metadata.language_name

    @property
    def language_code(self) -> str | None:
        return self.metadata.language_code

    @property
    def translation_name(self) -> str | None:
        return self.metadata.translation_name

    @property
    def abbreviation(self) -> str | None:
        return self.metadata.abbreviation

    @property
    def year(self) -> int | None:
        return self.metadata.year

    @property
    def text_direction(self) -> TextDirectionHint:
        return self.metadata.direction

    @property
    def source_name(self) -> str | None:
        return self.metadata.source_name

    @property
    def copyright(self) -> str | None:
        return self.metadata.copyright

    @property
    def license(self) -> str | None:
        return self.metadata.license

    @property
    def canon(self) -> str | None:
        return self.metadata.canon

    @property
    def version_date(self) -> datetime | None:
        return self.metadata.version_date

    def copy_with(
        self,
        *,
        books: Iterable[Book] | None = None,
        language: BibleLanguageEnum | None = None,
        metadata: BibleMetadata | None = None,
        annotations: Mapping[str, Any] | None = None,
        search_index_mode: SearchIndexMode | None = None,
    ) -> Bible:
        next_books = self.books if books is None else tuple(books)
        next_mode = (
            self.search_index_mode
            if search_index_mode is None
            else SearchIndexMode(search_index_mode)
        )
        instance = self.__class__.__new__(self.__class__)
        instance._initialize(
            BibleInitializationData(
                books=next_books,
                language=self.language if language is None else language,
                metadata=self.metadata if metadata is None else metadata,
                schema_version=self.schema_version,
                annotations=self.annotations if annotations is None else annotations,
                search_index=(
                    self._search_index
                    if next_books is self.books and next_mode is self.search_index_mode
                    else None
                ),
                search_index_mode=next_mode,
            )
        )
        instance._load_time = self._load_time
        return instance

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Bible)
            and self.schema_version == other.schema_version
            and self.language is other.language
            and self.metadata == other.metadata
            and self.books == other.books
            and json_value_equal(self.annotations, other.annotations)
        )

    def __hash__(self) -> int:
        return hash(
            (
                self.schema_version,
                self.language,
                self.metadata,
                self.books,
                json_value_hash(self.annotations),
            )
        )

    def __getitem__(
        self,
        key: BibleBookEnum | tuple[BibleBookEnum, int] | tuple[BibleBookEnum, int, int],
    ) -> Book | Chapter | Verse:
        if isinstance(key, BibleBookEnum):
            return self.get_book(key)
        if isinstance(key, tuple) and len(key) == 2:
            book, chapter = key
            return self.get_chapter(book, chapter)
        if isinstance(key, tuple) and len(key) == 3:
            book, chapter, verse = key
            return self.get_verse(book, chapter, verse)
        raise TypeError(
            "use bible[book], bible[(book, chapter)], or "
            "bible[(book, chapter, verse)]"
        )

    @property
    def all_verses(self) -> Iterator[Verse]:
        return iter(self._all_verses)

    @property
    def book_count(self) -> int:
        return len(self.books)

    @property
    def chapter_count(self) -> int:
        return sum(len(book.chapters) for book in self.books)

    @property
    def verse_count(self) -> int:
        return len(self._all_verses)

    @property
    def books_with_index(self) -> Iterator[tuple[int, Book]]:
        return iter(enumerate(self.books))

    def get_book(self, book: BibleBookEnum) -> Book:
        try:
            return self._books_by_enum[book]
        except (KeyError, TypeError) as exc:
            raise BookNotFoundError(book) from exc

    def get_book_by_abbreviation(self, identifier: str) -> Book:
        try:
            return self.get_book(BibleBookEnum.parse(identifier))
        except (TypeError, ValueError, BookNotFoundError) as exc:
            raise BookNotFoundError(identifier) from exc

    get_book_by_abbrev = get_book_by_abbreviation

    def get_book_by_id(self, book_number: int) -> Book:
        if (
            not isinstance(book_number, int)
            or isinstance(book_number, bool)
            or not 1 <= book_number <= len(self.books)
        ):
            raise BookNotFoundError(book_number)
        return self.books[book_number - 1]

    def get_chapter(self, bible_book: BibleBookEnum, chapter_number: int) -> Chapter:
        return self.get_book(bible_book).get_chapter(chapter_number)

    def get_verses(
        self, bible_book: BibleBookEnum, chapter_number: int
    ) -> Sequence[Verse]:
        return self.get_book(bible_book).get_verses(chapter_number)

    def get_verse(
        self,
        bible_book: BibleBookEnum,
        chapter_number: int,
        verse_number: int,
    ) -> Verse:
        return self.get_book(bible_book).get_verse(chapter_number, verse_number)

    def get_chapter_at(self, location: BibleLocation) -> Chapter:
        return self.get_chapter(location.book, location.chapter)

    def get_verse_at(self, location: BibleLocation) -> Verse:
        if location.verse is None:
            raise ValueError("BibleLocation.verse is required")
        return self.get_verse(location.book, location.chapter, location.verse)

    def contains_reference(self, location: BibleLocation) -> bool:
        try:
            if location.verse is None:
                self.get_chapter_at(location)
            else:
                self.get_verse_at(location)
        except (BibleError, TypeError, ValueError):
            return False
        return True

    def _book_position(self, book: BibleBookEnum) -> int:
        try:
            return self._book_positions[book]
        except KeyError as exc:
            raise BookNotFoundError(book) from exc

    def next_chapter(self, current: BibleLocation) -> BibleLocation | None:
        book_index = self._book_position(current.book)
        book = self.books[book_index]
        try:
            chapter_index = next(
                index
                for index, chapter in enumerate(book.chapters)
                if chapter.chapter_number == current.chapter
            )
        except StopIteration as exc:
            raise ChapterNotFoundError(current.book, current.chapter) from exc
        if chapter_index + 1 < len(book.chapters):
            return BibleLocation(
                book=current.book,
                chapter=book.chapters[chapter_index + 1].chapter_number,
            )
        for next_book in self.books[book_index + 1 :]:
            if next_book.chapters:
                return BibleLocation(
                    book=next_book.book_enum,
                    chapter=next_book.chapters[0].chapter_number,
                )
        return None

    def previous_chapter(self, current: BibleLocation) -> BibleLocation | None:
        book_index = self._book_position(current.book)
        book = self.books[book_index]
        try:
            chapter_index = next(
                index
                for index, chapter in enumerate(book.chapters)
                if chapter.chapter_number == current.chapter
            )
        except StopIteration as exc:
            raise ChapterNotFoundError(current.book, current.chapter) from exc
        if chapter_index:
            return BibleLocation(
                book=current.book,
                chapter=book.chapters[chapter_index - 1].chapter_number,
            )
        for previous_book in reversed(self.books[:book_index]):
            if previous_book.chapters:
                return BibleLocation(
                    book=previous_book.book_enum,
                    chapter=previous_book.chapters[-1].chapter_number,
                )
        return None

    def has_next_chapter(self, current: BibleLocation) -> bool:
        return self.next_chapter(current) is not None

    def has_previous_chapter(self, current: BibleLocation) -> bool:
        return self.previous_chapter(current) is not None

    def next_verse(self, current: BibleLocation) -> BibleLocation | None:
        self.get_verse_at(current)
        try:
            position = self._verse_positions[
                (current.book, current.chapter, cast(int, current.verse))
            ]
        except KeyError as exc:
            raise VerseNotFoundError(
                current.book, current.chapter, current.verse or 0
            ) from exc
        return (
            self._all_verses[position + 1].location
            if position + 1 < len(self._all_verses)
            else None
        )

    def previous_verse(self, current: BibleLocation) -> BibleLocation | None:
        self.get_verse_at(current)
        try:
            position = self._verse_positions[
                (current.book, current.chapter, cast(int, current.verse))
            ]
        except KeyError as exc:
            raise VerseNotFoundError(
                current.book, current.chapter, current.verse or 0
            ) from exc
        return self._all_verses[position - 1].location if position else None

    def has_next_verse(self, current: BibleLocation) -> bool:
        return self.next_verse(current) is not None

    def has_previous_verse(self, current: BibleLocation) -> bool:
        return self.previous_verse(current) is not None

    # ------------------------------------------------------------------
    # Reference and passage parsing/resolution

    def _parse_edition_range_fallback(
        self,
        input_text: str,
        error: ParseVerseRefError,
        input_language: BibleLanguageEnum | str | None,
    ) -> EditionVerseRange | None:
        if error.error_code is not ReferenceParseErrorCode.CROSS_BOOK_RANGE_NOT_ASCENDING:
            return None
        for separator in _RANGE_SEPARATOR_RE.finditer(input_text):
            left = input_text[: separator.start()].strip()
            right = input_text[separator.end() :].strip()
            if not left or not right:
                continue
            try:
                start = self.reference_parser.parse_verse(left, language=input_language)
                end = self.reference_parser.parse_verse(right, language=input_language)
            except (ParseVerseRefError, TypeError, ValueError):
                continue
            try:
                is_edition_ascending = (
                    start.book is not end.book
                    and self._book_position(start.book)
                    < self._book_position(end.book)
                )
            except BookNotFoundError:
                continue
            if is_edition_ascending:
                return EditionVerseRange(start=start, end=end)
        return None

    def parse_reference(
        self,
        input_text: str,
        *,
        input_language: BibleLanguageEnum | str | None = None,
    ) -> EditionReference:
        """Parse a reference using loaded language/name preferences.

        Unlike the dependency-level helper, this method can return an
        :class:`EditionVerseRange` when a custom canon makes a cross-book range
        ascend in this edition but descend in canonical enum order.
        """

        try:
            return self.reference_parser.parse(input_text, language=input_language)
        except ParseVerseRefError as exc:
            fallback = self._parse_edition_range_fallback(
                input_text, exc, input_language
            )
            if fallback is None:
                raise
            return fallback

    def try_parse_reference(
        self,
        input_text: str,
        *,
        input_language: BibleLanguageEnum | str | None = None,
    ) -> EditionReference | None:
        try:
            return self.parse_reference(input_text, input_language=input_language)
        except (ParseVerseRefError, BibleError, TypeError, ValueError):
            return None

    def parse_reference_detailed(
        self,
        input_text: str,
        *,
        input_language: BibleLanguageEnum | str | None = None,
    ) -> EditionParsed[EditionReference]:
        try:
            parsed = self.reference_parser.parse_detailed(
                input_text, language=input_language
            )
            return EditionParsed(parsed.value, parsed.metadata)
        except ParseVerseRefError as exc:
            fallback = self._parse_edition_range_fallback(
                input_text, exc, input_language
            )
            if fallback is None:
                raise
            return EditionParsed(fallback)

    def parse_reference_result(
        self,
        input_text: str,
        *,
        input_language: BibleLanguageEnum | str | None = None,
    ) -> ParseSuccess[EditionReference] | ParseFailure[EditionReference]:
        try:
            parsed = self.parse_reference_detailed(
                input_text, input_language=input_language
            )
        except ParseVerseRefError as exc:
            return ParseFailure(exc)
        return ParseSuccess(
            parsed.value,
            parsed.metadata or ReferenceParseMetadata(normalized_input=""),
        )

    def parse_canonical_reference(
        self,
        input_text: str,
        *,
        input_language: BibleLanguageEnum | str | None = None,
    ) -> VerseRef | VerseRangeRef:
        """Parse only dependency-canonical reference ordering."""

        return self.reference_parser.parse(input_text, language=input_language)

    def parse_passage(
        self,
        input_text: str,
        *,
        input_language: BibleLanguageEnum | str | None = None,
    ) -> EditionPassage:
        try:
            return self.passage_parser.parse(input_text, language=input_language)
        except ParseVerseRefError as exc:
            fallback = self._parse_edition_range_fallback(
                input_text, exc, input_language
            )
            if fallback is None:
                raise
            return fallback

    def try_parse_passage(
        self,
        input_text: str,
        *,
        input_language: BibleLanguageEnum | str | None = None,
    ) -> EditionPassage | None:
        try:
            return self.parse_passage(input_text, input_language=input_language)
        except (ParseVerseRefError, BibleError, TypeError, ValueError):
            return None

    def parse_passage_detailed(
        self,
        input_text: str,
        *,
        input_language: BibleLanguageEnum | str | None = None,
    ) -> EditionParsed[EditionPassage]:
        try:
            parsed = self.passage_parser.parse_detailed(
                input_text, language=input_language
            )
            return EditionParsed(parsed.value, parsed.metadata)
        except ParseVerseRefError as exc:
            fallback = self._parse_edition_range_fallback(
                input_text, exc, input_language
            )
            if fallback is None:
                raise
            return EditionParsed(fallback)

    def parse_passage_result(
        self,
        input_text: str,
        *,
        input_language: BibleLanguageEnum | str | None = None,
    ) -> ParseSuccess[EditionPassage] | ParseFailure[EditionPassage]:
        try:
            parsed = self.parse_passage_detailed(
                input_text, input_language=input_language
            )
        except ParseVerseRefError as exc:
            return ParseFailure(exc)
        return ParseSuccess(
            parsed.value,
            parsed.metadata or ReferenceParseMetadata(normalized_input=""),
        )

    def resolve_verse_reference(self, reference: VerseRef) -> Verse:
        return self.get_verse(reference.book, reference.chapter, reference.verse)

    def resolve_reference(
        self, reference: VerseRef | VerseRangeRef | EditionVerseRange
    ) -> VerseSelection:
        if isinstance(reference, VerseRef):
            return VerseSelection((self.resolve_verse_reference(reference),))
        if isinstance(reference, (VerseRangeRef, EditionVerseRange)):
            return self.resolve_edition_range(reference)
        raise TypeError("reference must be a VerseRef or verse range")

    resolve_edition_reference = resolve_reference

    def resolve_verse_range(
        self, verse_range: VerseRangeRef
    ) -> VerseSelection:
        return self.resolve_edition_range(verse_range)

    def resolve_edition_range(
        self, verse_range: VerseRangeRef | EditionVerseRange
    ) -> VerseSelection:
        start, end = verse_range.start, verse_range.end
        start_book_index = self._book_position(start.book)
        end_book_index = self._book_position(end.book)

        # Validate both endpoints before yielding any partial result.
        self.resolve_verse_reference(start)
        self.resolve_verse_reference(end)
        if start_book_index > end_book_index or (
            start_book_index == end_book_index
            and (start.chapter, start.verse) > (end.chapter, end.verse)
        ):
            raise ValueError("Verse range start must come before the end")

        selected: list[Verse] = []
        for book_index in range(start_book_index, end_book_index + 1):
            book = self.books[book_index]
            for chapter in book.chapters:
                for verse in chapter.verses:
                    before_start = book_index == start_book_index and (
                        chapter.chapter_number < start.chapter
                        or (
                            chapter.chapter_number == start.chapter
                            and verse.verse_number < start.verse
                        )
                    )
                    after_end = book_index == end_book_index and (
                        chapter.chapter_number > end.chapter
                        or (
                            chapter.chapter_number == end.chapter
                            and verse.verse_number > end.verse
                        )
                    )
                    if not before_start and not after_end:
                        selected.append(verse)
        return VerseSelection(selected)

    @overload
    def get_verse_by_ref(
        self,
        verse_ref: VerseRef,
        *,
        input_language: BibleLanguageEnum | str | None = None,
    ) -> Verse:
        ...

    @overload
    def get_verse_by_ref(
        self,
        verse_ref: str,
        *,
        input_language: BibleLanguageEnum | str | None = None,
    ) -> Verse:
        ...

    def get_verse_by_ref(
        self,
        verse_ref: VerseRef | str,
        *,
        input_language: BibleLanguageEnum | str | None = None,
    ) -> Verse:
        if isinstance(verse_ref, str):
            parsed = self.parse_reference(
                verse_ref, input_language=input_language
            )
            if not isinstance(parsed, VerseRef):
                raise TypeError("verse_ref must identify exactly one verse")
            verse_ref = parsed
        if not isinstance(verse_ref, VerseRef):
            raise TypeError("verse_ref must be a VerseRef or reference string")
        return self.resolve_verse_reference(verse_ref)

    def verse_or_none(
        self,
        reference: str,
        *,
        input_language: BibleLanguageEnum | str | None = None,
    ) -> Verse | None:
        try:
            return self.get_verse_by_ref(
                reference, input_language=input_language
            )
        except (BibleError, ParseVerseRefError, TypeError, ValueError):
            return None

    verse_or_null = verse_or_none

    def get_verse_range_by_ref(
        self,
        verse_range_ref: VerseRangeRef | EditionVerseRange | str,
        *,
        input_language: BibleLanguageEnum | str | None = None,
    ) -> VerseSelection:
        reference: EditionReference
        if isinstance(verse_range_ref, str):
            reference = self.parse_reference(
                verse_range_ref, input_language=input_language
            )
        else:
            reference = verse_range_ref
        if not isinstance(reference, (VerseRangeRef, EditionVerseRange)):
            raise TypeError(
                "verse_range_ref must be a VerseRangeRef, EditionVerseRange, "
                "or reference string"
            )
        return self.resolve_edition_range(reference)

    def verses_or_none(
        self,
        reference: str,
        *,
        input_language: BibleLanguageEnum | str | None = None,
    ) -> VerseSelection | None:
        try:
            return self.get_verse_range_by_ref(
                reference, input_language=input_language
            )
        except (BibleError, ParseVerseRefError, TypeError, ValueError):
            return None

    verses_or_null = verses_or_none

    @overload
    def get_by_ref(
        self,
        verse_ref: VerseRef,
        *,
        input_language: BibleLanguageEnum | str | None = None,
    ) -> Verse:
        ...

    @overload
    def get_by_ref(
        self,
        verse_ref: VerseRangeRef | EditionVerseRange,
        *,
        input_language: BibleLanguageEnum | str | None = None,
    ) -> VerseSelection:
        ...

    @overload
    def get_by_ref(
        self,
        verse_ref: str,
        *,
        input_language: BibleLanguageEnum | str | None = None,
    ) -> Verse | VerseSelection:
        ...

    def get_by_ref(
        self,
        verse_ref: VerseRef | VerseRangeRef | EditionVerseRange | str,
        *,
        input_language: BibleLanguageEnum | str | None = None,
    ) -> Verse | VerseSelection:
        if isinstance(verse_ref, str):
            verse_ref = self.parse_reference(
                verse_ref, input_language=input_language
            )
        if isinstance(verse_ref, VerseRef):
            return self.resolve_verse_reference(verse_ref)
        if isinstance(verse_ref, (VerseRangeRef, EditionVerseRange)):
            return self.resolve_edition_range(verse_ref)
        raise TypeError(
            "verse_ref must be a VerseRef, verse range, or reference string"
        )

    def get_by_reference(
        self,
        input_text: str,
        *,
        input_language: BibleLanguageEnum | str | None = None,
    ) -> BibleReferenceResult:
        reference = self.parse_reference(
            input_text, input_language=input_language
        )
        if isinstance(reference, VerseRef):
            return BibleReferenceResult.from_verse(
                self.resolve_verse_reference(reference)
            )
        return BibleReferenceResult.from_selection(
            self.resolve_edition_range(reference)
        )

    def resolve_passage(self, passage: Passage | EditionVerseRange) -> VerseSelection:
        if isinstance(passage, EditionVerseRange):
            return self.resolve_edition_range(passage)
        verses: list[Verse] = []
        if isinstance(passage, BookPassage):
            verses.extend(self.get_book(passage.book).all_verses)
        elif isinstance(passage, ChapterPassage):
            book = self.get_book(passage.book)
            end = (
                passage.start_chapter
                if passage.end_chapter is None
                else passage.end_chapter
            )
            # A declared chapter range is contiguous. Navigation supports
            # sparse editions, but resolving ``1-3`` must not silently change
            # its meaning to ``1,3`` when chapter 2 is absent.
            for chapter_number in range(passage.start_chapter, end + 1):
                verses.extend(book.get_chapter(chapter_number).verses)
        elif isinstance(passage, VersePassage):
            for selection in passage.selections:
                verses.extend(self.resolve_reference(selection))
        elif isinstance(passage, PassageSequence):
            for child in passage.passages:
                verses.extend(self.resolve_passage(child))
        else:
            raise TypeError(f"unsupported passage type: {type(passage).__name__}")
        return VerseSelection(verses)

    resolve_edition_passage = resolve_passage

    def get_passage(
        self,
        passage: str | Passage | VerseRef | VerseRangeRef | EditionVerseRange,
        *,
        input_language: BibleLanguageEnum | str | None = None,
    ) -> VerseSelection:
        if isinstance(passage, str):
            passage = self.parse_passage(
                passage, input_language=input_language
            )
        if isinstance(passage, VerseRef):
            return VerseSelection((self.resolve_verse_reference(passage),))
        if isinstance(passage, (VerseRangeRef, EditionVerseRange)):
            return self.resolve_edition_range(passage)
        if isinstance(passage, Passage):
            return self.resolve_passage(passage)
        raise TypeError("passage must be a Passage, Reference, or string")

    def get_passage_selection(
        self,
        passage: str | Passage | VerseRef | VerseRangeRef | EditionVerseRange,
        *,
        input_language: BibleLanguageEnum | str | None = None,
    ) -> VerseSelection:
        return self.get_passage(passage, input_language=input_language)

    def format_location(
        self,
        location: BibleLocation,
        *,
        output_language: BibleLanguageEnum | str | None = None,
        book_name_style: BookNameStyle | str = BookNameStyle.LONG,
        prefer_edition_book_name: bool = True,
    ) -> str:
        if location.verse is None:
            self.get_chapter_at(location)
        else:
            self.get_verse_at(location)
        style = BookNameStyle(book_name_style)
        if prefer_edition_book_name and style is BookNameStyle.LONG:
            book_name = self.get_book(location.book).name
        else:
            formatter_language = (
                BibleLanguageEnum.from_str(output_language)
                if isinstance(output_language, str)
                else output_language or self.language
            )
            formatter = ReferenceFormatter(
                language=formatter_language,
                book_name_style=style,
            )
            book_name = formatter.format_book_name(location.book)
        suffix = str(location.chapter)
        if location.verse is not None:
            suffix += f":{location.verse}"
        return f"{book_name} {suffix}"

    def key_for_verse(self, verse: Verse) -> BibleVerseKey:
        edition_id = self.id
        if edition_id is None or not edition_id.strip():
            raise ValueError(
                "Bible metadata must define an id before creating persisted keys"
            )
        loaded = self.get_verse(
            verse.book, verse.chapter_number, verse.verse_number
        )
        if loaded != verse:
            raise ValueError("verse must be the value loaded by this edition")
        return BibleVerseKey.from_verse(edition_id, verse)

    def key_for_location(self, location: BibleLocation) -> BibleVerseKey:
        return self.key_for_verse(self.get_verse_at(location))

    # ------------------------------------------------------------------
    # Search and index lifecycle

    @property
    def has_search_index(self) -> bool:
        return self._search_index is not None

    def _build_search_index(self) -> dict[str, tuple[Verse, ...]]:
        mutable: defaultdict[str, list[Verse]] = defaultdict(list)
        for verse in self.all_verses:
            for term in build_search_index_terms(verse.text):
                mutable[term].append(verse)
        return {term: tuple(verses) for term, verses in mutable.items()}

    def build_search_index(self) -> SearchIndex:
        """Build a reusable public index without changing retained state."""

        return SearchIndex.from_verses(self.all_verses)

    def prewarm_search_index(self) -> None:
        if (
            self.search_index_mode is not SearchIndexMode.DISABLED
            and self._search_index is None
        ):
            self._search_index = self._build_search_index()

    async def prewarm_search_index_async(self) -> None:
        if (
            self.search_index_mode is SearchIndexMode.DISABLED
            or self._search_index is not None
        ):
            return
        index = await asyncio.to_thread(self._build_search_index)
        if self.search_index_mode is not SearchIndexMode.DISABLED:
            self._search_index = index

    def clear_search_index(self) -> None:
        self._search_index = None

    def invalidate_search_index(self) -> None:
        """Compatibility alias for clearing the retained search cache."""

        self.clear_search_index()

    def _index_for(self, options: SearchOptions) -> Mapping[str, tuple[Verse, ...]] | None:
        if (
            options.case_sensitive
            or not options.normalize_unicode
            or options.ignore_diacritics
            or self.search_index_mode is SearchIndexMode.DISABLED
        ):
            return None
        if self._search_index is None:
            self._search_index = self._build_search_index()
        return self._search_index

    def _verses_for_scope(self, options: SearchOptions) -> Iterator[Verse]:
        books: Iterable[Book]
        if options.book is None:
            books = self.books
        else:
            book = (
                self._books_by_enum.get(options.book)
                if isinstance(options.book, BibleBookEnum)
                else None
            )
            books = () if book is None else (book,)
        for book in books:
            for chapter in book.chapters:
                if options.chapter is not None and chapter.chapter_number != options.chapter:
                    continue
                for verse in chapter.verses:
                    if options.verse is not None and verse.verse_number != options.verse:
                        continue
                    yield verse

    def _search_candidates(
        self, query: str, options: SearchOptions
    ) -> Iterable[Verse]:
        index = self._index_for(options)
        if index is None or options.mode is SearchMode.EXACT and not options.whole_words:
            return self._verses_for_scope(options)
        tokens = {
            search_index_lookup_key(token)
            for token in tokenize_search_text(
                query,
                case_sensitive=options.case_sensitive,
                normalize_unicode=options.normalize_unicode,
                ignore_diacritics=options.ignore_diacritics,
            )
        }
        if not tokens:
            return ()
        postings: list[Sequence[Verse]] = [
            index.get(token, ()) for token in tokens
        ]
        if options.mode in (SearchMode.ALL, SearchMode.EXACT):
            if any(not posting for posting in postings):
                return ()
            rarest = postings[0]
            for posting in postings[1:]:
                if len(posting) < len(rarest):
                    rarest = posting
            candidate_ids = set(map(id, rarest))
            for posting in postings:
                candidate_ids.intersection_update(map(id, posting))
        else:
            candidate_ids = {id(verse) for posting in postings for verse in posting}
        return (
            verse
            for verse in self._verses_for_scope(options)
            if id(verse) in candidate_ids
        )

    def search(self, query: str) -> list[Verse]:
        """Return verses containing every distinct token in ``query``."""

        tokens = tokenize_search_text(query)
        if not tokens:
            return []
        options = SearchOptions(mode=SearchMode.ALL)
        return [
            verse
            for verse in self._search_candidates(query, options)
            if matches_search_text(verse.text, query, options)
        ]

    def search_with_options(
        self, query: str, options: SearchOptions
    ) -> SearchResults:
        options.validate()
        has_text = bool(query.strip())
        candidates = (
            self._search_candidates(query, options)
            if has_text
            else self._verses_for_scope(options)
        )
        matches = (
            verse
            for verse in candidates
            if not has_text or matches_search_text(verse.text, query, options)
        )
        page, has_more, total_count = self._collect_page(
            matches, offset=options.offset, limit=options.max_results
        )
        hits = tuple(
            SearchHit.with_context(
                verse=verse,
                book=self.get_book(verse.book),
                match_ranges=(
                    find_search_match_ranges(verse.text, query, options)
                    if has_text
                    else ()
                ),
            )
            for verse in page
        )
        return SearchResults.from_hits(
            query,
            hits,
            offset=options.offset,
            limit=options.max_results,
            total_count=total_count,
            has_more=has_more,
        )

    def search_advanced(
        self,
        text: str | None = None,
        *,
        mode: SearchMode = SearchMode.EXACT,
        book: BibleBookEnum | None = None,
        chapter: int | None = None,
        verse: int | None = None,
        case_sensitive: bool = False,
        whole_words: bool = False,
        max_results: int | None = None,
        offset: int = 0,
        normalize_unicode: bool = True,
        ignore_diacritics: bool = False,
    ) -> SearchResults:
        return self.search_with_options(
            text or "",
            SearchOptions(
                mode=mode,
                case_sensitive=case_sensitive,
                whole_words=whole_words,
                max_results=max_results,
                offset=offset,
                book=book,
                chapter=chapter,
                verse=verse,
                normalize_unicode=normalize_unicode,
                ignore_diacritics=ignore_diacritics,
            ),
        )

    def fuzzy_search(
        self,
        query: str,
        options: SearchOptions | None = None,
        *,
        max_distance: int = 2,
        max_results: int | None = None,
        offset: int | None = None,
        mode: SearchMode | str | None = None,
        case_sensitive: bool | None = None,
        whole_words: bool | None = None,
        normalize_unicode: bool | None = None,
        ignore_diacritics: bool | None = None,
        book: BibleBookEnum | None = None,
        chapter: int | None = None,
        verse: int | None = None,
    ) -> SearchResults:
        if isinstance(max_distance, bool) or not isinstance(max_distance, int):
            raise TypeError("max_distance must be an integer")
        if max_distance < 0:
            raise ValueError("max_distance must be non-negative")
        if options is not None and not isinstance(options, SearchOptions):
            raise TypeError("options must be SearchOptions or None")
        base = options or SearchOptions()
        effective = SearchOptions(
            mode=base.mode if mode is None else mode,
            max_results=(
                base.max_results
                if options is not None and max_results is None
                else max_results
            ),
            offset=base.offset if offset is None else offset,
            book=base.book if book is None else book,
            chapter=base.chapter if chapter is None else chapter,
            verse=base.verse if verse is None else verse,
            case_sensitive=(
                base.case_sensitive
                if case_sensitive is None
                else case_sensitive
            ),
            whole_words=(
                base.whole_words if whole_words is None else whole_words
            ),
            normalize_unicode=(
                base.normalize_unicode
                if normalize_unicode is None
                else normalize_unicode
            ),
            ignore_diacritics=(
                base.ignore_diacritics
                if ignore_diacritics is None
                else ignore_diacritics
            ),
        )
        if not tokenize_search_text(
            query,
            case_sensitive=effective.case_sensitive,
            normalize_unicode=effective.normalize_unicode,
            ignore_diacritics=effective.ignore_diacritics,
        ):
            return SearchResults.from_hits(
                query,
                (),
                offset=effective.offset,
                limit=effective.max_results,
                total_count=0,
            )
        matched: Iterator[tuple[Verse, Sequence[Any]]] = (
            (candidate, ranges)
            for candidate in self._verses_for_scope(effective)
            if (
                ranges := fuzzy_match_ranges(
                    candidate.text,
                    query,
                    effective,
                    max_distance,
                )
            )
            is not None
        )
        page, has_more, total_count = self._collect_page(
            matched,
            offset=effective.offset,
            limit=effective.max_results,
        )
        hits = tuple(
            SearchHit.with_context(
                verse=item[0],
                book=self.get_book(item[0].book),
                match_ranges=item[1],
            )
            for item in page
        )
        return SearchResults.from_hits(
            query,
            hits,
            offset=effective.offset,
            limit=effective.max_results,
            total_count=total_count,
            has_more=has_more,
        )

    @staticmethod
    def _collect_page(
        values: Iterable[_T], *, offset: int, limit: int | None
    ) -> tuple[tuple[_T, ...], bool, int | None]:
        page: list[_T] = []
        matched_count = 0
        skipped_count = 0
        has_more = False
        for value in values:
            matched_count += 1
            if skipped_count < offset:
                skipped_count += 1
                continue
            if limit is not None and len(page) >= limit:
                has_more = True
                break
            page.append(value)
        return tuple(page), has_more, None if has_more else matched_count

    def books_containing(self, word: str) -> tuple[Book, ...]:
        return tuple(
            book
            for book in self.books
            if any(verse.contains_word(word) for verse in book.all_verses)
        )

    # ------------------------------------------------------------------
    # Result helpers, statistics, metrics, and serialization

    @staticmethod
    def _as_result(operation: Callable[[], _T]) -> Result[_T]:
        try:
            return Success(operation())
        except Exception as exc:  # application-boundary helper by design
            return Failure.from_exception(exc)

    def get_book_result(self, book: BibleBookEnum) -> Result[Book]:
        return self._as_result(lambda: self.get_book(book))

    def get_book_by_id_result(self, book_number: int) -> Result[Book]:
        return self._as_result(lambda: self.get_book_by_id(book_number))

    def get_verse_result(
        self, book: BibleBookEnum, chapter: int, verse: int
    ) -> Result[Verse]:
        return self._as_result(lambda: self.get_verse(book, chapter, verse))

    def get_verse_by_ref_result(
        self,
        reference: VerseRef | str,
        *,
        input_language: BibleLanguageEnum | str | None = None,
    ) -> Result[Verse]:
        return self._as_result(
            lambda: self.get_verse_by_ref(
                reference, input_language=input_language
            )
        )

    def get_verse_range_by_ref_result(
        self,
        reference: VerseRangeRef | EditionVerseRange | str,
        *,
        input_language: BibleLanguageEnum | str | None = None,
    ) -> Result[VerseSelection]:
        return self._as_result(
            lambda: self.get_verse_range_by_ref(
                reference, input_language=input_language
            )
        )

    def get_passage_result(
        self,
        passage: str | Passage | VerseRef | VerseRangeRef | EditionVerseRange,
        *,
        input_language: BibleLanguageEnum | str | None = None,
    ) -> Result[VerseSelection]:
        return self._as_result(
            lambda: self.get_passage(passage, input_language=input_language)
        )

    @property
    def stats(self) -> BibleStats:
        verses = tuple(self.all_verses)
        total_words = sum(verse.stats.word_count for verse in verses)
        character_count = sum(len(verse) for verse in verses)
        average = (
            (character_count + len(verses) // 2) // len(verses)
            if verses
            else 0
        )
        return BibleStats(
            book_count=self.book_count,
            chapter_count=self.chapter_count,
            verse_count=self.verse_count,
            total_words=total_words,
            average_verse_length=average,
            verses_per_book=MappingProxyType(
                {book.book_enum: book.verse_count for book in self.books}
            ),
        )

    @property
    def performance_metrics(self) -> BiblePerformanceMetrics:
        verses = tuple(self.all_verses)
        index = self._search_index
        text_bytes = sum(len(verse.text.encode("utf-8")) for verse in verses)
        text_characters = sum(len(verse.text) for verse in verses)
        text_utf16_code_units = sum(
            len(verse.text.encode("utf-16-le")) // 2
            for verse in verses
        )
        posting_count = (
            sum(len(postings) for postings in index.values()) if index else 0
        )
        estimate = sum(sys.getsizeof(verse) + sys.getsizeof(verse.text) for verse in verses)
        estimate += sum(sys.getsizeof(book) + sys.getsizeof(book.name) for book in self.books)
        if index:
            estimate += sum(
                sys.getsizeof(term) + sys.getsizeof(postings)
                for term, postings in index.items()
            )
        return BiblePerformanceMetrics(
            load_time=self._load_time,
            search_index_size=len(index) if index else 0,
            search_index_built=index is not None,
            verse_count=len(verses),
            posting_count=posting_count,
            text_bytes=text_bytes,
            text_characters=text_characters,
            text_utf16_code_units=text_utf16_code_units,
            memory_usage_kib=(estimate + 1023) // 1024,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the canonical, lossless schema-v1 JSON representation."""

        thawed_annotations = thaw_json_value(self.annotations)
        root: dict[str, Any] = dict(
            cast(dict[str, Any], thawed_annotations)
        )
        root.update(
            {
                "schemaVersion": self.schema_version,
                "language": str(self.language),
                "metadata": self.metadata.to_json(),
                "bookOrder": [book.book_enum.as_str() for book in self.books],
                "books": {
                    book.book_enum.as_str(): book.to_json_value()
                    for book in self.books
                },
            }
        )
        return root

    def to_json(self, *, indent: int | None = None) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            allow_nan=False,
            indent=indent,
            separators=None if indent is not None else (",", ":"),
        )
