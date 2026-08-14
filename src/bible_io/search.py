"""Immutable search values and Unicode-aware matching algorithms.

This module is intentionally independent from :mod:`bible_io.bible_class`.
It reads the small public surface of verse and book objects by duck typing, so
the content model can import these helpers without creating an import cycle.

All text ranges use half-open Python string indices (Unicode code points).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Hashable, Iterator, TypeVar, cast

from .loading import SearchIndexMode

from .text_search import (
    SearchTextToken,
    _grapheme_spans,
    build_search_index_terms,
    contains_normalized_text,
    find_normalized_substring_ranges,
    is_within_levenshtein_distance,
    normalized_range_to_source,
    search_index_lookup_key,
    tokenize_search_text,
    tokenize_search_text_with_ranges,
    uses_unspaced_word_boundaries,
)


class SearchMode(str, Enum):
    """How query terms are combined."""

    EXACT = "exact"
    ALL = "all"
    ANY = "any"

    # Source-compatible aliases for callers ported from Dart.
    exact = EXACT
    all = ALL
    any = ANY

    @classmethod
    def _missing_(cls, value: object) -> SearchMode | None:
        if isinstance(value, str):
            normalized = value.strip().lower().replace("-", "_")
            for member in cls:
                if normalized in {member.value, member.name.lower()}:
                    return member
        return None

    @classmethod
    def coerce(cls, value: SearchMode | str) -> SearchMode:
        """Return a mode from either an enum member or its string value."""

        if isinstance(value, cls):
            return value
        if not isinstance(value, str):
            raise TypeError("mode must be a SearchMode or string")
        return cls(value)

    def __str__(self) -> str:
        return self.value


_UNSET = object()


@dataclass(frozen=True, slots=True)
class SearchOptions:
    """Validated options shared by exact and fuzzy searches.

    ``copy_with`` distinguishes an omitted argument from ``None``.  Passing
    ``None`` therefore explicitly clears any nullable limit or scope.
    """

    mode: SearchMode | str = SearchMode.EXACT
    case_sensitive: bool = False
    whole_words: bool = False
    max_results: int | None = None
    offset: int = 0
    book: Hashable | None = None
    chapter: int | None = None
    verse: int | None = None
    normalize_unicode: bool = True
    ignore_diacritics: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", SearchMode.coerce(self.mode))
        _require_bool(self.case_sensitive, "case_sensitive")
        _require_bool(self.whole_words, "whole_words")
        _require_bool(self.normalize_unicode, "normalize_unicode")
        _require_bool(self.ignore_diacritics, "ignore_diacritics")
        _validate_optional_nonnegative_int(self.max_results, "max_results")
        _validate_nonnegative_int(self.offset, "offset")
        _validate_optional_positive_int(self.chapter, "chapter")
        _validate_optional_positive_int(self.verse, "verse")
        if self.book is not None:
            try:
                hash(self.book)
            except TypeError as error:
                raise TypeError("book scope must be hashable") from error

    def copy_with(
        self,
        *,
        mode: SearchMode | str | object = _UNSET,
        case_sensitive: bool | object = _UNSET,
        whole_words: bool | object = _UNSET,
        max_results: int | None | object = _UNSET,
        offset: int | object = _UNSET,
        book: Hashable | None | object = _UNSET,
        chapter: int | None | object = _UNSET,
        verse: int | None | object = _UNSET,
        normalize_unicode: bool | object = _UNSET,
        ignore_diacritics: bool | object = _UNSET,
    ) -> SearchOptions:
        """Return a validated copy with selected replacement values."""

        return SearchOptions(
            mode=self.mode if mode is _UNSET else cast(SearchMode | str, mode),
            case_sensitive=(
                self.case_sensitive
                if case_sensitive is _UNSET
                else cast(bool, case_sensitive)
            ),
            whole_words=(
                self.whole_words if whole_words is _UNSET else cast(bool, whole_words)
            ),
            max_results=(
                self.max_results
                if max_results is _UNSET
                else cast(int | None, max_results)
            ),
            offset=self.offset if offset is _UNSET else cast(int, offset),
            book=self.book if book is _UNSET else book,
            chapter=(
                self.chapter if chapter is _UNSET else cast(int | None, chapter)
            ),
            verse=self.verse if verse is _UNSET else cast(int | None, verse),
            normalize_unicode=(
                self.normalize_unicode
                if normalize_unicode is _UNSET
                else cast(bool, normalize_unicode)
            ),
            ignore_diacritics=(
                self.ignore_diacritics
                if ignore_diacritics is _UNSET
                else cast(bool, ignore_diacritics)
            ),
        )

    def validate(self) -> SearchOptions:
        """Return this already-validated immutable options value."""

        return self


@dataclass(frozen=True, order=True, slots=True)
class TextRange:
    """A half-open range in a Python source string."""

    start: int
    end: int

    def __post_init__(self) -> None:
        _validate_nonnegative_int(self.start, "start")
        _validate_nonnegative_int(self.end, "end")
        if self.end < self.start:
            raise ValueError("range end must not precede start")

    def __len__(self) -> int:
        return self.end - self.start

    @property
    def length(self) -> int:
        """Return the number of Python code points in the range."""

        return len(self)

    @property
    def is_empty(self) -> bool:
        """Return whether the range has no content."""

        return self.start == self.end

    def contains(self, offset: int) -> bool:
        """Return whether ``offset`` lies inside the half-open range."""

        _validate_nonnegative_int(offset, "offset")
        return self.start <= offset < self.end

    def __contains__(self, offset: object) -> bool:
        return isinstance(offset, int) and not isinstance(offset, bool) and self.contains(offset)

    def to_slice(self) -> slice:
        """Return the equivalent Python slice."""

        return slice(self.start, self.end)


@dataclass(frozen=True, slots=True, init=False, eq=False)
class SearchHit:
    """Display-ready metadata for one matched verse.

    Construct a hit directly from explicit snippet bounds, or use
    :meth:`with_context` to derive a grapheme-safe context window.
    """

    verse: object
    book_name: str
    reference: str
    match_ranges: tuple[TextRange, ...]
    snippet: str
    snippet_start: int
    snippet_end: int
    snippet_match_ranges: tuple[TextRange, ...]
    _verse_snapshot: tuple[object, ...] = field(repr=False)

    def __init__(
        self,
        verse: object,
        book: object,
        reference: str | None = None,
        match_ranges: Iterable[TextRange | range | tuple[int, int]] = (),
        snippet_start: int = 0,
        snippet_end: int | None = None,
    ) -> None:
        text = _verse_text(verse)
        end = len(text) if snippet_end is None else snippet_end
        _validate_nonnegative_int(snippet_start, "snippet_start")
        _validate_nonnegative_int(end, "snippet_end")
        if snippet_start > end or end > len(text):
            raise ValueError("snippet bounds must be ordered and inside the verse")
        ranges = _coerce_ranges(match_ranges)
        _validate_match_ranges(ranges, len(text))
        _validate_book_membership(verse, book)
        book_name = _book_title(book)
        if reference is None:
            reference = f"{book_name} {_verse_chapter(verse)}:{_verse_number(verse)}"
        elif not isinstance(reference, str):
            raise TypeError("reference must be a string or None")
        relative = _relative_match_ranges(ranges, snippet_start, end)

        object.__setattr__(self, "verse", verse)
        object.__setattr__(self, "book_name", book_name)
        object.__setattr__(self, "reference", reference)
        object.__setattr__(self, "match_ranges", ranges)
        object.__setattr__(self, "snippet", text[snippet_start:end])
        object.__setattr__(self, "snippet_start", snippet_start)
        object.__setattr__(self, "snippet_end", end)
        object.__setattr__(self, "snippet_match_ranges", relative)
        object.__setattr__(self, "_verse_snapshot", _verse_value_key(verse))

    @classmethod
    def new(
        cls,
        verse: object,
        book: object,
        reference: str | None,
        match_ranges: Iterable[TextRange | range | tuple[int, int]],
        snippet_start: int,
        snippet_end: int,
    ) -> SearchHit:
        """Rust-compatible named constructor for explicit bounds."""

        return cls(verse, book, reference, match_ranges, snippet_start, snippet_end)

    @classmethod
    def with_context(
        cls,
        verse: object,
        book: object,
        match_ranges: Iterable[TextRange | range | tuple[int, int]],
        max_snippet_length: int = 160,
        *,
        reference: str | None = None,
    ) -> SearchHit:
        """Create a hit with a grapheme-safe context around its first match."""

        _validate_positive_int(max_snippet_length, "max_snippet_length")
        text = _verse_text(verse)
        ranges = _coerce_ranges(match_ranges)
        _validate_match_ranges(ranges, len(text))
        start, end = _context_bounds(
            text,
            ranges[0] if ranges else None,
            max_snippet_length,
        )
        return cls(verse, book, reference, ranges, start, end)

    @property
    def snippet_bounds(self) -> TextRange:
        """Return the snippet's bounds in the full verse text."""

        return TextRange(self.snippet_start, self.snippet_end)

    @property
    def has_leading_omission(self) -> bool:
        """Return whether content was omitted before the snippet."""

        return self.snippet_start > 0

    @property
    def has_trailing_omission(self) -> bool:
        """Return whether content was omitted after the snippet."""

        return self.snippet_end < len(_verse_text(self.verse))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SearchHit):
            return NotImplemented
        return self._value_key() == other._value_key()

    def __hash__(self) -> int:
        return hash(self._value_key())

    def _value_key(self) -> tuple[object, ...]:
        return (
            self._verse_snapshot,
            self.book_name,
            self.reference,
            self.match_ranges,
            self.snippet,
            self.snippet_start,
            self.snippet_end,
            self.snippet_match_ranges,
        )


@dataclass(frozen=True, slots=True, eq=False)
class SearchResults:
    """A validated, immutable page of verses and optional hit metadata."""

    query: str
    verses: tuple[object, ...] = ()
    hits: tuple[SearchHit, ...] = ()
    offset: int = 0
    limit: int | None = None
    total_count: int | None = None
    has_more: bool = False
    _verse_snapshots: tuple[tuple[object, ...], ...] = field(
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.query, str):
            raise TypeError("query must be a string")
        object.__setattr__(self, "verses", tuple(self.verses))
        object.__setattr__(self, "hits", tuple(self.hits))
        object.__setattr__(
            self,
            "_verse_snapshots",
            tuple(_verse_value_key(verse) for verse in self.verses),
        )
        _validate_nonnegative_int(self.offset, "offset")
        _validate_optional_nonnegative_int(self.limit, "limit")
        _validate_optional_nonnegative_int(self.total_count, "total_count")
        _require_bool(self.has_more, "has_more")
        _validate_result_page(
            self.verses,
            self.offset,
            self.limit,
            self.total_count,
            self.has_more,
        )
        if self.hits:
            if len(self.hits) != len(self.verses):
                raise ValueError("hits and verses must have equal lengths")
            if any(
                hit._verse_snapshot != verse_snapshot
                for hit, verse_snapshot in zip(
                    self.hits,
                    self._verse_snapshots,
                )
            ):
                raise ValueError("hits must describe the corresponding verses")

    @classmethod
    def from_verses(
        cls,
        query: str,
        verses: Iterable[object],
        offset: int = 0,
        limit: int | None = None,
        total_count: int | None = None,
        has_more: bool = False,
    ) -> SearchResults:
        """Construct a page without display-ready hit values."""

        return cls(query, tuple(verses), (), offset, limit, total_count, has_more)

    @classmethod
    def from_hits(
        cls,
        query: str,
        hits: Iterable[SearchHit],
        offset: int = 0,
        limit: int | None = None,
        total_count: int | None = None,
        has_more: bool = False,
    ) -> SearchResults:
        """Construct a page and derive its verses from the supplied hits."""

        hit_values = tuple(hits)
        return cls(
            query,
            tuple(hit.verse for hit in hit_values),
            hit_values,
            offset,
            limit,
            total_count,
            has_more,
        )

    def __len__(self) -> int:
        return len(self.verses)

    def __bool__(self) -> bool:
        return bool(self.verses)

    def __iter__(self) -> Iterator[object]:
        return iter(self.verses)

    @property
    def count(self) -> int:
        """Return the number of verses on this page."""

        return len(self)

    @property
    def is_empty(self) -> bool:
        """Return whether the page contains no verses."""

        return not self.verses

    @property
    def is_not_empty(self) -> bool:
        """Return whether the page contains at least one verse."""

        return bool(self.verses)

    @property
    def has_previous(self) -> bool:
        """Return whether the requested offset can have an earlier page."""

        return self.offset > 0 and self.total_count != 0

    @property
    def next_offset(self) -> int | None:
        """Return the next offset when a nonempty later page is known."""

        if not self.has_more or not self.verses:
            return None
        return self.offset + len(self.verses)

    def by_book(self) -> Mapping[object, tuple[object, ...]]:
        """Group this page by book identifier, preserving page order."""

        grouped: dict[object, list[object]] = {}
        for verse in self.verses:
            grouped.setdefault(_verse_book(verse), []).append(verse)
        return MappingProxyType(
            {book: tuple(values) for book, values in grouped.items()}
        )

    def by_chapter(self) -> Mapping[str, tuple[object, ...]]:
        """Group by canonical English chapter label."""

        grouped: dict[str, list[object]] = {}
        for verse in self.verses:
            label = f"{_canonical_book_name(_verse_book(verse))} {_verse_chapter(verse)}"
            grouped.setdefault(label, []).append(verse)
        return MappingProxyType(
            {label: tuple(values) for label, values in grouped.items()}
        )

    def by_chapter_location(self) -> Mapping[tuple[object, int], tuple[object, ...]]:
        """Group by stable, language-neutral book/chapter coordinates."""

        grouped: dict[tuple[object, int], list[object]] = {}
        for verse in self.verses:
            key = (_verse_book(verse), _verse_chapter(verse))
            grouped.setdefault(key, []).append(verse)
        return MappingProxyType(
            {location: tuple(values) for location, values in grouped.items()}
        )

    def by_display_chapter(self) -> Mapping[str, tuple[object, ...]]:
        """Group by loaded display book name when hit metadata is present."""

        display_names = {
            _verse_book(hit.verse): hit.book_name
            for hit in self.hits
        }
        grouped: dict[str, list[object]] = {}
        for verse in self.verses:
            book = _verse_book(verse)
            name = display_names.get(book, _canonical_book_name(book))
            label = f"{name} {_verse_chapter(verse)}"
            grouped.setdefault(label, []).append(verse)
        return MappingProxyType(
            {label: tuple(values) for label, values in grouped.items()}
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SearchResults):
            return NotImplemented
        return self._value_key() == other._value_key()

    def __hash__(self) -> int:
        return hash(self._value_key())

    def _value_key(self) -> tuple[object, ...]:
        return (
            self.query,
            self._verse_snapshots,
            self.hits,
            self.offset,
            self.limit,
            self.total_count,
            self.has_more,
        )


def matches_search_text(text: str, query: str, options: SearchOptions) -> bool:
    """Return whether text satisfies the selected exact/all/any policy."""

    _require_search_inputs(text, query, options)
    if options.mode is SearchMode.EXACT and not options.whole_words:
        return contains_normalized_text(
            text,
            query,
            options.case_sensitive,
            options.normalize_unicode,
            options.ignore_diacritics,
        )

    content = tokenize_search_text(
        text,
        options.case_sensitive,
        options.normalize_unicode,
        options.ignore_diacritics,
    )
    query_tokens = tokenize_search_text(
        query,
        options.case_sensitive,
        options.normalize_unicode,
        options.ignore_diacritics,
    )
    if not query_tokens:
        return False
    if options.mode is SearchMode.EXACT:
        return any(
            content[start : start + len(query_tokens)] == query_tokens
            for start in range(0, len(content) - len(query_tokens) + 1)
        )

    distinct_query = _unique(query_tokens)

    def token_matches(query_token: str) -> bool:
        return any(
            content_token == query_token
            or (
                not options.whole_words
                and uses_unspaced_word_boundaries(query_token)
                and query_token in content_token
            )
            for content_token in content
        )

    if options.mode is SearchMode.ALL:
        return all(token_matches(token) for token in distinct_query)
    return any(token_matches(token) for token in distinct_query)


def find_match_ranges(
    text: str,
    query: str,
    options: SearchOptions,
) -> tuple[TextRange, ...]:
    """Return all ordered source ranges contributing to a normal match."""

    _require_search_inputs(text, query, options)
    if options.mode is SearchMode.EXACT and not options.whole_words:
        return tuple(
            TextRange(value.start, value.stop)
            for value in find_normalized_substring_ranges(
                text,
                query,
                options.case_sensitive,
                options.normalize_unicode,
                options.ignore_diacritics,
            )
        )

    query_tokens = tokenize_search_text(
        query,
        options.case_sensitive,
        options.normalize_unicode,
        options.ignore_diacritics,
    )
    if not query_tokens:
        return ()
    content = tokenize_search_text_with_ranges(
        text,
        options.case_sensitive,
        options.normalize_unicode,
        options.ignore_diacritics,
    )
    if options.mode is SearchMode.EXACT:
        ranges: list[TextRange] = []
        for start in range(0, len(content) - len(query_tokens) + 1):
            window = content[start : start + len(query_tokens)]
            if tuple(token.normalized for token in window) == query_tokens:
                ranges.append(TextRange(window[0].start, window[-1].end))
        return tuple(ranges)

    ranges = []
    for content_token in content:
        for query_token in _unique(query_tokens):
            if content_token.normalized == query_token:
                ranges.append(TextRange(content_token.start, content_token.end))
            elif (
                not options.whole_words
                and uses_unspaced_word_boundaries(query_token)
                and query_token in content_token.normalized
            ):
                ranges.extend(
                    TextRange(
                        content_token.start + value.start,
                        content_token.start + value.stop,
                    )
                    for value in find_normalized_substring_ranges(
                        content_token.raw,
                        query_token,
                        options.case_sensitive,
                        options.normalize_unicode,
                        options.ignore_diacritics,
                    )
                )
    return _merge_ranges(ranges)


# Compatibility spelling used by the Bible integration layer.
find_search_match_ranges = find_match_ranges


def fuzzy_matches(
    text: str,
    query: str,
    options: SearchOptions,
    max_distance: int,
) -> bool:
    """Return whether text satisfies a bounded fuzzy query."""

    return fuzzy_match_ranges(text, query, options, max_distance) is not None


def fuzzy_match_ranges(
    text: str,
    query: str,
    options: SearchOptions,
    max_distance: int,
) -> tuple[TextRange, ...] | None:
    """Return source ranges for a fuzzy match, or ``None`` when unmatched."""

    _require_search_inputs(text, query, options)
    _validate_nonnegative_int(max_distance, "max_distance")
    content = tokenize_search_text_with_ranges(
        text,
        options.case_sensitive,
        options.normalize_unicode,
        options.ignore_diacritics,
    )
    query_tokens = tokenize_search_text(
        query,
        options.case_sensitive,
        options.normalize_unicode,
        options.ignore_diacritics,
    )
    if not content or not query_tokens:
        return None

    if options.mode is SearchMode.ANY:
        ranges = [
            matched
            for content_token in content
            for query_token in query_tokens
            if (
                matched := _fuzzy_token_match_range(
                    content_token,
                    query_token,
                    max_distance,
                    options,
                )
            )
            is not None
        ]
        return _merge_ranges(ranges) if ranges else None

    if options.mode is SearchMode.ALL:
        ranges = []
        for query_token in _unique(query_tokens):
            matched = next(
                (
                    value
                    for content_token in content
                    if (
                        value := _fuzzy_token_match_range(
                            content_token,
                            query_token,
                            max_distance,
                            options,
                        )
                    )
                    is not None
                ),
                None,
            )
            if matched is None:
                return None
            ranges.append(matched)
        return _merge_ranges(ranges)

    ranges = []
    for start in range(0, len(content) - len(query_tokens) + 1):
        window = content[start : start + len(query_tokens)]
        matched_window: list[TextRange] = []
        for content_token, query_token in zip(window, query_tokens):
            matched = _fuzzy_token_match_range(
                content_token,
                query_token,
                max_distance,
                options,
            )
            if matched is None:
                break
            matched_window.append(matched)
        else:
            ranges.append(TextRange(matched_window[0].start, matched_window[-1].end))
    return _merge_ranges(ranges) if ranges else None


BookResolver = Callable[[object], object] | Mapping[Any, object]


def search_verses(
    verses: Iterable[object],
    query: str,
    options: SearchOptions | Mapping[str, object] | None = None,
    *,
    fuzzy_max_distance: int | None = None,
    book_resolver: BookResolver | None = None,
    max_snippet_length: int = 160,
) -> SearchResults:
    """Search an edition-ordered verse iterable and build one result page.

    ``book_resolver`` may be a callable or mapping keyed by a verse's book
    identifier.  When supplied, results include :class:`SearchHit` values;
    otherwise the page contains verse values only.  A blank normal query
    matches every verse in scope, while a blank fuzzy query matches none.
    """

    if not isinstance(query, str):
        raise TypeError("query must be a string")
    if options is None:
        resolved_options = SearchOptions()
    elif isinstance(options, SearchOptions):
        resolved_options = options
    elif isinstance(options, Mapping):
        resolved_options = SearchOptions(**cast(dict[str, Any], dict(options)))
    else:
        raise TypeError("options must be SearchOptions, a mapping, or None")
    if fuzzy_max_distance is not None:
        _validate_nonnegative_int(fuzzy_max_distance, "fuzzy_max_distance")
    _validate_positive_int(max_snippet_length, "max_snippet_length")

    has_text = bool(query.strip())
    limit = resolved_options.max_results
    matched_count = 0
    page: list[object] = []
    has_more = False
    for verse in verses:
        if not _matches_scope(verse, resolved_options):
            continue
        if not has_text:
            matched = fuzzy_max_distance is None
        elif fuzzy_max_distance is None:
            matched = matches_search_text(_verse_text(verse), query, resolved_options)
        else:
            matched = fuzzy_matches(
                _verse_text(verse),
                query,
                resolved_options,
                fuzzy_max_distance,
            )
        if not matched:
            continue
        if matched_count < resolved_options.offset:
            matched_count += 1
            continue
        if limit is not None and len(page) == limit:
            has_more = True
            break
        page.append(verse)
        matched_count += 1

    total_count = None if has_more else matched_count
    if book_resolver is None:
        return SearchResults.from_verses(
            query,
            page,
            resolved_options.offset,
            resolved_options.max_results,
            total_count,
            has_more,
        )

    hits: list[SearchHit] = []
    for verse in page:
        text = _verse_text(verse)
        ranges = (
            find_match_ranges(text, query, resolved_options)
            if fuzzy_max_distance is None
            else fuzzy_match_ranges(
                text,
                query,
                resolved_options,
                fuzzy_max_distance,
            )
            or ()
        )
        hits.append(
            SearchHit.with_context(
                verse,
                _resolve_book(book_resolver, _verse_book(verse)),
                ranges,
                max_snippet_length,
            )
        )
    return SearchResults.from_hits(
        query,
        hits,
        resolved_options.offset,
        resolved_options.max_results,
        total_count,
        has_more,
    )


def _fuzzy_token_match_range(
    content: SearchTextToken,
    query: str,
    max_distance: int,
    options: SearchOptions,
) -> TextRange | None:
    if not options.whole_words and uses_unspaced_word_boundaries(query):
        return _fuzzy_unspaced_substring_range(
            content,
            query,
            max_distance,
            options,
        )
    if is_within_levenshtein_distance(content.normalized, query, max_distance):
        return TextRange(content.start, content.end)
    return None


def _fuzzy_unspaced_substring_range(
    content: SearchTextToken,
    query: str,
    max_distance: int,
    options: SearchOptions,
) -> TextRange | None:
    query_length = len(query)
    minimum = max(1, query_length - max_distance)
    maximum = min(len(content.normalized), query_length + max_distance)
    if minimum > maximum:
        return None

    best: tuple[int, int, int, int] | None = None
    for length in range(minimum, maximum + 1):
        for start in range(0, len(content.normalized) - length + 1):
            end = start + length
            candidate = content.normalized[start:end]
            if not is_within_levenshtein_distance(candidate, query, max_distance):
                continue
            distance = _levenshtein_distance_with_limit(
                candidate,
                query,
                max_distance,
            )
            score = (distance, abs(length - query_length), start, end)
            if best is None or score < best:
                best = score
    if best is None:
        return None
    _, _, start, end = best
    source_range = normalized_range_to_source(
        content.raw,
        start,
        end,
        options.case_sensitive,
        options.normalize_unicode,
        options.ignore_diacritics,
    )
    if source_range is None:
        return None
    return TextRange(
        content.start + source_range.start,
        content.start + source_range.stop,
    )


def _levenshtein_distance_with_limit(first: str, second: str, limit: int) -> int:
    previous = list(range(len(second) + 1))
    for row, first_character in enumerate(first, start=1):
        current = [row]
        for column, second_character in enumerate(second, start=1):
            current.append(
                min(
                    previous[column] + 1,
                    current[column - 1] + 1,
                    previous[column - 1] + (first_character != second_character),
                )
            )
        previous = current
    return min(previous[-1], limit + 1)


def _relative_match_ranges(
    ranges: tuple[TextRange, ...],
    snippet_start: int,
    snippet_end: int,
) -> tuple[TextRange, ...]:
    relative: list[TextRange] = []
    for value in ranges:
        start = max(value.start, snippet_start)
        end = min(value.end, snippet_end)
        if start < end:
            relative.append(TextRange(start - snippet_start, end - snippet_start))
    return tuple(relative)


def _context_bounds(
    text: str,
    first_match: TextRange | None,
    maximum: int,
) -> tuple[int, int]:
    if len(text) <= maximum:
        return 0, len(text)
    match_length = len(first_match) if first_match is not None else 0
    desired_length = min(len(text), max(maximum, match_length))
    center = (
        (first_match.start + first_match.end) // 2
        if first_match is not None
        else 0
    )
    desired_start = min(
        max(0, center - desired_length // 2),
        len(text) - desired_length,
    )
    desired_end = desired_start + desired_length
    boundaries = [0]
    boundaries.extend(end for _, end in _grapheme_spans(text))
    start = max(value for value in boundaries if value <= desired_start)
    end = next(
        (value for value in boundaries if value >= desired_end),
        len(text),
    )
    return start, end


def _coerce_ranges(
    values: Iterable[TextRange | range | tuple[int, int]],
) -> tuple[TextRange, ...]:
    ranges: list[TextRange] = []
    for value in values:
        if isinstance(value, TextRange):
            ranges.append(value)
        elif isinstance(value, range):
            if value.step != 1:
                raise ValueError("source ranges must use a step of one")
            ranges.append(TextRange(value.start, value.stop))
        elif (
            isinstance(value, Sequence)
            and not isinstance(value, (str, bytes, bytearray))
            and len(value) == 2
        ):
            ranges.append(TextRange(value[0], value[1]))
        else:
            raise TypeError("match ranges must be TextRange or two-integer pairs")
    return tuple(ranges)


def _merge_ranges(values: Iterable[TextRange]) -> tuple[TextRange, ...]:
    ranges = sorted(values)
    if not ranges:
        return ()
    merged: list[TextRange] = []
    current = ranges[0]
    for following in ranges[1:]:
        if following.start <= current.end:
            current = TextRange(current.start, max(current.end, following.end))
        else:
            merged.append(current)
            current = following
    merged.append(current)
    return tuple(merged)


def _validate_match_ranges(ranges: tuple[TextRange, ...], text_length: int) -> None:
    previous_end = 0
    for value in ranges:
        if value.is_empty or value.end > text_length or value.start < previous_end:
            raise ValueError(
                "match ranges must be sorted, nonempty, nonoverlapping, and inside the verse"
            )
        previous_end = value.end


def _validate_result_page(
    verses: tuple[object, ...],
    offset: int,
    limit: int | None,
    total_count: int | None,
    has_more: bool,
) -> None:
    if limit is not None and len(verses) > limit:
        raise ValueError("page exceeds its result limit")
    page_end = offset + len(verses)
    if total_count is not None:
        if total_count < len(verses) or (verses and page_end > total_count):
            raise ValueError("total_count must include the returned page")
        if has_more != (page_end < total_count):
            raise ValueError("has_more must agree with offset, count, and total_count")
    seen: set[tuple[object, int, int]] = set()
    for verse in verses:
        location = _verse_location_key(verse)
        if location in seen:
            raise ValueError("results must not contain duplicate verse locations")
        seen.add(location)


def _matches_scope(verse: object, options: SearchOptions) -> bool:
    return (
        (options.book is None or options.book == _verse_book(verse))
        and (options.chapter is None or options.chapter == _verse_chapter(verse))
        and (options.verse is None or options.verse == _verse_number(verse))
    )


def _resolve_book(resolver: BookResolver, book: object) -> object:
    return resolver(book) if callable(resolver) else resolver[book]


def _validate_book_membership(verse: object, book: object) -> None:
    if _book_identifier(book) != _verse_book(verse):
        raise ValueError("book must contain the matched verse")
    getter = getattr(book, "get_verse", None)
    if not callable(getter):
        return
    try:
        loaded = getter(_verse_chapter(verse), _verse_number(verse))
    except Exception as error:
        raise ValueError("book must contain the matched verse") from error
    if _verse_value_key(loaded) != _verse_value_key(verse):
        raise ValueError("book must contain the matched verse value")


def _verse_book(verse: object) -> object:
    return _member(verse, ("book", "book_enum"), "verse book")


def _verse_chapter(verse: object) -> int:
    value = _member(verse, ("chapter_number", "chapter"), "verse chapter")
    _validate_positive_int(value, "verse chapter")
    return cast(int, value)


def _verse_number(verse: object) -> int:
    value = _member(verse, ("verse_number", "number"), "verse number")
    _validate_positive_int(value, "verse number")
    return cast(int, value)


def _verse_text(verse: object) -> str:
    value = _member(verse, ("text", "verse_text"), "verse text")
    if not isinstance(value, str):
        raise TypeError("verse text must be a string")
    return value


def _verse_location_key(verse: object) -> tuple[object, int, int]:
    return _verse_book(verse), _verse_chapter(verse), _verse_number(verse)


def _verse_value_key(verse: object) -> tuple[object, ...]:
    annotations = _optional_member(verse, ("annotations",), None)
    return (
        *_verse_location_key(verse),
        _verse_text(verse),
        _freeze_for_hash(annotations),
    )


def _book_identifier(book: object) -> object:
    return _member(book, ("book_enum", "book"), "book identifier")


def _book_title(book: object) -> str:
    value = _member(book, ("title", "name"), "book title")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("book title must be a nonblank string")
    return value


def _canonical_book_name(book: object) -> str:
    value = _optional_member(book, ("full_name",), None)
    if isinstance(value, str):
        return value
    return str(book)


def _member(value: object, names: tuple[str, ...], description: str) -> Any:
    missing = object()
    result = _optional_member(value, names, missing)
    if result is missing:
        raise TypeError(f"object does not expose {description}")
    return result


def _optional_member(value: object, names: tuple[str, ...], default: Any) -> Any:
    for name in names:
        if hasattr(value, name):
            result = getattr(value, name)
            return result() if callable(result) else result
    return default


def _freeze_for_hash(value: object) -> object:
    if isinstance(value, bool):
        # Python considers True equal to 1; JSON does not.
        return ("__json_bool__", value)
    if isinstance(value, Mapping):
        return tuple(
            sorted(
                (
                    (_freeze_for_hash(key), _freeze_for_hash(item))
                    for key, item in value.items()
                ),
                key=repr,
            )
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_for_hash(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_for_hash(item) for item in value)
    try:
        hash(value)
    except TypeError:
        return repr(value)
    return value


T = TypeVar("T", bound=Hashable)


def _unique(values: Iterable[T]) -> tuple[T, ...]:
    return tuple(dict.fromkeys(values))


def _require_search_inputs(text: str, query: str, options: SearchOptions) -> None:
    if not isinstance(text, str) or not isinstance(query, str):
        raise TypeError("text and query must be strings")
    if not isinstance(options, SearchOptions):
        raise TypeError("options must be SearchOptions")


def _require_bool(value: bool, name: str) -> None:
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a bool")


def _validate_nonnegative_int(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must not be negative")


def _validate_positive_int(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value <= 0:
        raise ValueError(f"{name} must be positive")


def _validate_optional_nonnegative_int(value: int | None, name: str) -> None:
    if value is not None:
        _validate_nonnegative_int(value, name)


def _validate_optional_positive_int(value: int | None, name: str) -> None:
    if value is not None:
        _validate_positive_int(value, name)


__all__ = [
    "BookResolver",
    "SearchHit",
    "SearchIndexMode",
    "SearchMode",
    "SearchOptions",
    "SearchResults",
    "TextRange",
    "build_search_index_terms",
    "find_match_ranges",
    "find_search_match_ranges",
    "fuzzy_match_ranges",
    "fuzzy_matches",
    "matches_search_text",
    "search_index_lookup_key",
    "search_verses",
    "tokenize_search_text",
]
