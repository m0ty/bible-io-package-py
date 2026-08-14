"""Unicode-aware primitives used by Bible text search.

The functions in this module deliberately operate on Python string indices.
Those indices count Unicode code points and can therefore be used directly in
normal Python slices.  This is the Python equivalent of the source-safe byte
ranges exposed by the Rust package and the code-unit ranges exposed by Dart.

Only the standard library is used.  Tokenization treats Unicode letters,
marks, and numbers as searchable characters, while punctuation and whitespace
separate tokens.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Iterable, Iterator, Sequence


_ASCII_TERM_RE = re.compile(r"[A-Za-z0-9]+")


@dataclass(frozen=True, slots=True)
class SearchTextToken:
    """A normalized token and its half-open range in the original text."""

    raw: str
    normalized: str
    start: int
    end: int

    def __post_init__(self) -> None:
        if not isinstance(self.raw, str) or not isinstance(self.normalized, str):
            raise TypeError("raw and normalized must be strings")
        _validate_index(self.start, "start")
        _validate_index(self.end, "end")
        if self.end < self.start:
            raise ValueError("token end must not precede start")
        if self.end - self.start != len(self.raw):
            raise ValueError("token range length must match its raw text")
        if not self.raw or not self.normalized:
            raise ValueError("search tokens must not be empty")


@dataclass(frozen=True, slots=True)
class _MappedSearchText:
    text: str
    starts: tuple[int, ...]
    ends: tuple[int, ...]

    def source_range(self, start: int, end: int) -> range | None:
        if start < 0 or end <= start or end > len(self.text):
            return None
        return range(self.starts[start], self.ends[end - 1])


def normalize_search_text(
    text: str,
    case_sensitive: bool = False,
    normalize_unicode: bool = True,
    ignore_diacritics: bool = False,
) -> str:
    """Return the normalized representation used for matching.

    Case-insensitive matching uses :meth:`str.casefold`, which supplies the
    expected Unicode-aware behavior (including such expansions as ``ß`` to
    ``ss``).  Canonical NFC normalization is enabled by default.  Diacritic
    folding is opt-in and removes Unicode mark characters after NFD
    decomposition.
    """

    _require_text(text, "text")
    _require_bool(case_sensitive, "case_sensitive")
    _require_bool(normalize_unicode, "normalize_unicode")
    _require_bool(ignore_diacritics, "ignore_diacritics")
    if text.isascii():
        return text if case_sensitive else text.lower()
    return _normalize_piece(
        text,
        case_sensitive=case_sensitive,
        normalize_unicode=normalize_unicode,
        ignore_diacritics=ignore_diacritics,
    )


def tokenize_search_text(
    text: str,
    case_sensitive: bool = False,
    normalize_unicode: bool = True,
    ignore_diacritics: bool = False,
) -> tuple[str, ...]:
    """Split text into immutable normalized Unicode search tokens."""

    _require_text(text, "text")
    _require_bool(case_sensitive, "case_sensitive")
    _require_bool(normalize_unicode, "normalize_unicode")
    _require_bool(ignore_diacritics, "ignore_diacritics")
    if text.isascii():
        if case_sensitive:
            return tuple(match.group(0) for match in _ASCII_TERM_RE.finditer(text))
        return tuple(match.group(0).lower() for match in _ASCII_TERM_RE.finditer(text))
    return tuple(
        token.normalized
        for token in tokenize_search_text_with_ranges(
            text,
            case_sensitive=case_sensitive,
            normalize_unicode=normalize_unicode,
            ignore_diacritics=ignore_diacritics,
        )
    )


def tokenize_search_text_with_ranges(
    text: str,
    case_sensitive: bool = False,
    normalize_unicode: bool = True,
    ignore_diacritics: bool = False,
) -> tuple[SearchTextToken, ...]:
    """Tokenize text while retaining Python source-string ranges."""

    _require_text(text, "text")
    _require_bool(case_sensitive, "case_sensitive")
    _require_bool(normalize_unicode, "normalize_unicode")
    _require_bool(ignore_diacritics, "ignore_diacritics")

    tokens: list[SearchTextToken] = []
    token_start: int | None = None
    for index, character in enumerate(text):
        if _is_search_character(character):
            if token_start is None:
                token_start = index
        elif token_start is not None:
            _append_token(
                tokens,
                text,
                token_start,
                index,
                case_sensitive,
                normalize_unicode,
                ignore_diacritics,
            )
            token_start = None
    if token_start is not None:
        _append_token(
            tokens,
            text,
            token_start,
            len(text),
            case_sensitive,
            normalize_unicode,
            ignore_diacritics,
        )
    return tuple(tokens)


def extract_unicode_words(text: str) -> tuple[str, ...]:
    """Return original Unicode word tokens in source order."""

    _require_text(text, "text")
    words: list[str] = []
    start: int | None = None
    for index, character in enumerate(text):
        if _is_search_character(character):
            if start is None:
                start = index
        elif start is not None:
            words.append(text[start:index])
            start = None
    if start is not None:
        words.append(text[start:])
    return tuple(words)


def contains_normalized_text(
    text: str,
    query: str,
    case_sensitive: bool = False,
    normalize_unicode: bool = True,
    ignore_diacritics: bool = False,
) -> bool:
    """Return whether normalized ``text`` contains a nonempty query."""

    _require_text(text, "text")
    _require_text(query, "query")
    normalized_query = normalize_search_text(
        query,
        case_sensitive=case_sensitive,
        normalize_unicode=normalize_unicode,
        ignore_diacritics=ignore_diacritics,
    )
    if not normalized_query:
        return False
    return normalized_query in normalize_search_text(
        text,
        case_sensitive=case_sensitive,
        normalize_unicode=normalize_unicode,
        ignore_diacritics=ignore_diacritics,
    )


def uses_unspaced_word_boundaries(token: str) -> bool:
    """Return whether ``token`` contains a commonly unspaced script."""

    _require_text(token, "token")
    if token.isascii():
        return False
    return any(
        _in_ranges(
            ord(character),
            (
                (0x3400, 0x4DBF),  # CJK Extension A
                (0x4E00, 0x9FFF),  # CJK Unified Ideographs
                (0xF900, 0xFAFF),  # CJK Compatibility Ideographs
                (0x20000, 0x323AF),  # CJK supplementary extensions
                (0x3040, 0x309F),  # Hiragana
                (0x30A0, 0x30FF),  # Katakana
                (0x31F0, 0x31FF),  # Katakana extensions
                (0xFF66, 0xFF9D),  # Half-width Katakana
                (0x0E00, 0x0E7F),  # Thai
                (0x0E80, 0x0EFF),  # Lao
                (0x1000, 0x109F),  # Myanmar
                (0xA9E0, 0xA9FF),
                (0xAA60, 0xAA7F),
                (0x1780, 0x17FF),  # Khmer
            ),
        )
        for character in token
    )


def build_search_index_terms(text: str, max_ngram_length: int = 3) -> frozenset[str]:
    """Build full-token and short n-gram terms for an inverted index."""

    _validate_positive_int(max_ngram_length, "max_ngram_length")
    tokens = tokenize_search_text(text)
    if text.isascii():
        return frozenset(tokens)
    terms: set[str] = set()
    for token in tokens:
        terms.add(token)
        if not uses_unspaced_word_boundaries(token):
            continue
        maximum = min(max_ngram_length, len(token))
        for length in range(1, maximum + 1):
            for start in range(0, len(token) - length + 1):
                terms.add(token[start : start + length])
    return frozenset(terms)


def search_index_lookup_key(token: str, max_ngram_length: int = 3) -> str:
    """Return an index key guaranteed for an unspaced-script substring."""

    _require_text(token, "token")
    _validate_positive_int(max_ngram_length, "max_ngram_length")
    if not uses_unspaced_word_boundaries(token):
        return token
    return token[:max_ngram_length]


def find_normalized_substring_ranges(
    text: str,
    query: str,
    case_sensitive: bool = False,
    normalize_unicode: bool = True,
    ignore_diacritics: bool = False,
) -> tuple[range, ...]:
    """Find non-overlapping normalized matches as Python source ranges."""

    _require_text(text, "text")
    _require_text(query, "query")
    normalized_query = normalize_search_text(
        query,
        case_sensitive=case_sensitive,
        normalize_unicode=normalize_unicode,
        ignore_diacritics=ignore_diacritics,
    )
    if not normalized_query:
        return ()
    mapped = _normalize_with_source_mapping(
        text,
        case_sensitive=case_sensitive,
        normalize_unicode=normalize_unicode,
        ignore_diacritics=ignore_diacritics,
    )
    ranges: list[range] = []
    search_from = 0
    while search_from <= len(mapped.text) - len(normalized_query):
        start = mapped.text.find(normalized_query, search_from)
        if start < 0:
            break
        end = start + len(normalized_query)
        source_range = mapped.source_range(start, end)
        if source_range is not None and (not ranges or ranges[-1] != source_range):
            ranges.append(source_range)
        search_from = end
    return tuple(ranges)


def normalized_range_to_source(
    source: str,
    normalized_start: int,
    normalized_end: int,
    case_sensitive: bool = False,
    normalize_unicode: bool = True,
    ignore_diacritics: bool = False,
) -> range | None:
    """Map a normalized half-open range back to the original Python string."""

    _require_text(source, "source")
    _validate_index(normalized_start, "normalized_start")
    _validate_index(normalized_end, "normalized_end")
    return _normalize_with_source_mapping(
        source,
        case_sensitive=case_sensitive,
        normalize_unicode=normalize_unicode,
        ignore_diacritics=ignore_diacritics,
    ).source_range(normalized_start, normalized_end)


def is_within_levenshtein_distance(
    first: str,
    second: str,
    max_distance: int,
) -> bool:
    """Return whether two strings differ by at most ``max_distance`` edits."""

    _require_text(first, "first")
    _require_text(second, "second")
    _validate_index(max_distance, "max_distance")
    if abs(len(first) - len(second)) > max_distance:
        return False
    rows, columns = (first, second) if len(first) >= len(second) else (second, first)
    previous = list(range(len(columns) + 1))
    for row_number, row_character in enumerate(rows, start=1):
        current = [row_number]
        minimum = row_number
        for column_number, column_character in enumerate(columns, start=1):
            value = min(
                previous[column_number] + 1,
                current[column_number - 1] + 1,
                previous[column_number - 1]
                + (row_character != column_character),
            )
            current.append(value)
            minimum = min(minimum, value)
        if minimum > max_distance:
            return False
        previous = current
    return previous[-1] <= max_distance


def _append_token(
    output: list[SearchTextToken],
    text: str,
    start: int,
    end: int,
    case_sensitive: bool,
    normalize_unicode: bool,
    ignore_diacritics: bool,
) -> None:
    raw = text[start:end]
    normalized = normalize_search_text(
        raw,
        case_sensitive=case_sensitive,
        normalize_unicode=normalize_unicode,
        ignore_diacritics=ignore_diacritics,
    )
    if normalized:
        output.append(SearchTextToken(raw, normalized, start, end))


def _normalize_piece(
    text: str,
    *,
    case_sensitive: bool,
    normalize_unicode: bool,
    ignore_diacritics: bool,
) -> str:
    normalized = (
        unicodedata.normalize("NFC", text)
        if normalize_unicode or ignore_diacritics
        else text
    )
    if not case_sensitive:
        normalized = normalized.casefold()
    if ignore_diacritics:
        normalized = "".join(
            character
            for character in unicodedata.normalize("NFD", normalized)
            if not unicodedata.category(character).startswith("M")
        )
        return unicodedata.normalize("NFC", normalized)
    if normalize_unicode:
        return unicodedata.normalize("NFC", normalized)
    return normalized


def _normalize_with_source_mapping(
    source: str,
    *,
    case_sensitive: bool,
    normalize_unicode: bool,
    ignore_diacritics: bool,
) -> _MappedSearchText:
    normalized_parts: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    for start, end in _grapheme_spans(source):
        normalized = _normalize_piece(
            source[start:end],
            case_sensitive=case_sensitive,
            normalize_unicode=normalize_unicode,
            ignore_diacritics=ignore_diacritics,
        )
        normalized_parts.append(normalized)
        starts.extend(start for _ in normalized)
        ends.extend(end for _ in normalized)
    return _MappedSearchText("".join(normalized_parts), tuple(starts), tuple(ends))


def _grapheme_spans(text: str) -> Iterator[tuple[int, int]]:
    """Yield practical extended-grapheme spans without a third-party regex.

    This covers canonical combining sequences, Hangul composition, emoji ZWJ
    sequences, emoji modifiers, variation selectors, and regional-indicator
    pairs—the cases that affect normalization and safe snippets here.
    """

    if not text:
        return
    start = 0
    regional_count = 1 if _is_regional_indicator(text[0]) else 0
    for index in range(1, len(text)):
        previous = text[index - 1]
        current = text[index]
        join = _joins_previous(previous, current, regional_count)
        if not join:
            yield start, index
            start = index
            regional_count = 1 if _is_regional_indicator(current) else 0
        elif _is_regional_indicator(current):
            regional_count += 1
        elif not _is_extend(current):
            regional_count = 0
    yield start, len(text)


def _joins_previous(previous: str, current: str, regional_count: int) -> bool:
    if previous == "\r" and current == "\n":
        return True
    if _is_extend(current) or current == "\u200d" or previous == "\u200d":
        return True
    previous_hangul = _hangul_class(previous)
    current_hangul = _hangul_class(current)
    if previous_hangul == "L" and current_hangul in {"L", "V", "LV", "LVT"}:
        return True
    if previous_hangul in {"LV", "V"} and current_hangul in {"V", "T"}:
        return True
    if previous_hangul in {"LVT", "T"} and current_hangul == "T":
        return True
    return (
        _is_regional_indicator(previous)
        and _is_regional_indicator(current)
        and regional_count % 2 == 1
    )


def _hangul_class(character: str) -> str | None:
    value = ord(character)
    if _in_ranges(value, ((0x1100, 0x115F), (0xA960, 0xA97C))):
        return "L"
    if _in_ranges(value, ((0x1160, 0x11A7), (0xD7B0, 0xD7C6))):
        return "V"
    if _in_ranges(value, ((0x11A8, 0x11FF), (0xD7CB, 0xD7FB))):
        return "T"
    if 0xAC00 <= value <= 0xD7A3:
        return "LV" if (value - 0xAC00) % 28 == 0 else "LVT"
    return None


def _is_extend(character: str) -> bool:
    value = ord(character)
    return (
        unicodedata.category(character).startswith("M")
        or 0xFE00 <= value <= 0xFE0F
        or 0xE0100 <= value <= 0xE01EF
        or 0x1F3FB <= value <= 0x1F3FF
    )


def _is_regional_indicator(character: str) -> bool:
    return 0x1F1E6 <= ord(character) <= 0x1F1FF


def _is_search_character(character: str) -> bool:
    return unicodedata.category(character)[0] in {"L", "M", "N"}


def _in_ranges(value: int, ranges: Sequence[tuple[int, int]]) -> bool:
    return any(start <= value <= end for start, end in ranges)


def _validate_index(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must not be negative")


def _validate_positive_int(value: int, name: str) -> None:
    _validate_index(value, name)
    if value == 0:
        raise ValueError(f"{name} must be positive")


def _require_text(value: str, name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")


def _require_bool(value: bool, name: str) -> None:
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a bool")


__all__ = [
    "SearchTextToken",
    "build_search_index_terms",
    "contains_normalized_text",
    "extract_unicode_words",
    "find_normalized_substring_ranges",
    "is_within_levenshtein_distance",
    "normalize_search_text",
    "normalized_range_to_source",
    "search_index_lookup_key",
    "tokenize_search_text",
    "tokenize_search_text_with_ranges",
    "uses_unspaced_word_boundaries",
]
