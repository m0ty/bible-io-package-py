"""Immutable inverted index for default all-term Bible search."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Hashable

from .search import (
    SearchMode,
    SearchOptions,
    _verse_book,
    _verse_chapter,
    _verse_number,
    _verse_text,
    matches_search_text,
)
from .text_search import (
    build_search_index_terms,
    search_index_lookup_key,
    tokenize_search_text,
    uses_unspaced_word_boundaries,
)


VerseLocationTuple = tuple[Hashable, int, int]


@dataclass(frozen=True, slots=True, init=False, eq=False)
class SearchIndex:
    """Map normalized terms to immutable, edition-ordered verse locations.

    :meth:`from_verses` retains source text so long unspaced-script substring
    candidates can be verified. Manual indexes may supply the same ``texts``
    mapping; without it, long unspaced queries conservatively require a full
    token key instead of returning possible false positives.
    """

    _index: Mapping[str, tuple[VerseLocationTuple, ...]]
    _texts: Mapping[VerseLocationTuple, str]

    def __init__(
        self,
        index: Mapping[str, Iterable[VerseLocationTuple]] | None = None,
        *,
        texts: Mapping[VerseLocationTuple, str] | None = None,
    ) -> None:
        normalized: dict[str, tuple[VerseLocationTuple, ...]] = {}
        for term, postings in (index or {}).items():
            if not isinstance(term, str) or not term:
                raise ValueError("search-index terms must be nonempty strings")
            values = tuple(_coerce_location(value) for value in postings)
            if len(set(values)) != len(values):
                raise ValueError(
                    f"search-index postings for {term!r} contain duplicates"
                )
            normalized[term] = values
        normalized_texts: dict[VerseLocationTuple, str] = {}
        for location, text in (texts.items() if texts is not None else ()):
            normalized_location = _coerce_location(location)
            if not isinstance(text, str):
                raise TypeError("search-index verse texts must be strings")
            normalized_texts[normalized_location] = text
        if texts is not None:
            missing_texts = {
                location
                for postings in normalized.values()
                for location in postings
                if location not in normalized_texts
            }
            if missing_texts:
                raise ValueError(
                    "texts must include every location in the search index"
                )
        object.__setattr__(self, "_index", MappingProxyType(normalized))
        object.__setattr__(self, "_texts", MappingProxyType(normalized_texts))

    @classmethod
    def from_verses(cls, verses: Iterable[object]) -> SearchIndex:
        """Build an index from verses already ordered by their edition."""

        postings: dict[str, list[VerseLocationTuple]] = {}
        texts: dict[VerseLocationTuple, str] = {}
        for verse in verses:
            book = _verse_book(verse)
            try:
                hash(book)
            except TypeError as error:
                raise TypeError("verse book identifiers must be hashable") from error
            location = (book, _verse_chapter(verse), _verse_number(verse))
            text = _verse_text(verse)
            if location in texts:
                raise ValueError(f"duplicate verse location: {location!r}")
            texts[location] = text
            for term in build_search_index_terms(text, 3):
                postings.setdefault(term, []).append(location)
        return cls(postings, texts=texts)

    @property
    def index(self) -> Mapping[str, tuple[VerseLocationTuple, ...]]:
        """Return a read-only view of the posting map."""

        return self._index

    def __len__(self) -> int:
        return len(self._index)

    def __bool__(self) -> bool:
        return bool(self._index)

    @property
    def posting_count(self) -> int:
        """Return the total number of verse postings."""

        return sum(len(postings) for postings in self._index.values())

    def search(self, query: str) -> tuple[VerseLocationTuple, ...]:
        """Return locations containing every distinct normalized query term."""

        if not isinstance(query, str):
            raise TypeError("query must be a string")
        query_tokens = tuple(dict.fromkeys(tokenize_search_text(query)))
        if not query_tokens:
            return ()
        lookup_terms = tuple(
            dict.fromkeys(
                (
                    token
                    if (
                        not self._texts
                        and len(token) > 3
                        and uses_unspaced_word_boundaries(token)
                    )
                    else search_index_lookup_key(token, 3)
                )
                for token in query_tokens
            )
        )
        posting_lists: list[tuple[VerseLocationTuple, ...]] = []
        for term in lookup_terms:
            postings = self._index.get(term)
            if postings is None:
                return ()
            posting_lists.append(postings)
        posting_lists.sort(key=len)
        others = [set(postings) for postings in posting_lists[1:]]
        candidates = tuple(
            location
            for location in posting_lists[0]
            if all(location in postings for postings in others)
        )
        if not self._texts:
            return candidates
        options = SearchOptions(mode=SearchMode.ALL)
        return tuple(
            location
            for location in candidates
            if (
                (text := self._texts.get(location)) is not None
                and matches_search_text(text, query, options)
            )
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SearchIndex):
            return NotImplemented
        return (
            dict(self._index) == dict(other._index)
            and dict(self._texts) == dict(other._texts)
        )

    def __hash__(self) -> int:
        return hash(
            (
                tuple(sorted(self._index.items(), key=lambda item: item[0])),
                frozenset(self._texts.items()),
            )
        )


def build_search_index(verses: Iterable[object]) -> SearchIndex:
    """Convenience wrapper around :meth:`SearchIndex.from_verses`."""

    return SearchIndex.from_verses(verses)


def _coerce_location(value: object) -> VerseLocationTuple:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError("a verse location must be a three-item sequence")
    if len(value) != 3:
        raise ValueError("a verse location must contain book, chapter, and verse")
    book, chapter, verse = value
    try:
        hash(book)
    except TypeError as error:
        raise TypeError("location book identifiers must be hashable") from error
    _validate_positive_int(chapter, "chapter")
    _validate_positive_int(verse, "verse")
    return book, chapter, verse


def _validate_positive_int(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value <= 0:
        raise ValueError(f"{name} must be positive")


__all__ = ["SearchIndex", "VerseLocationTuple", "build_search_index"]
