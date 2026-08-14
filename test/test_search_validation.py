"""Adversarial validation and grapheme tests for the public search API."""

from __future__ import annotations

from collections.abc import Hashable

import pytest

from bible_io import (
    BibleBookEnum,
    Book,
    Chapter,
    SearchHit,
    SearchIndex,
    SearchMode,
    SearchOptions,
    SearchResults,
    TextRange,
    Verse,
    build_search_index,
    find_match_ranges,
    fuzzy_matches,
    matches_search_text,
    search_verses,
)


def _models() -> tuple[Verse, Book]:
    verse = Verse(BibleBookEnum.Genesis, 1, 1, "alpha beta")
    book = Book(
        BibleBookEnum.Genesis,
        (Chapter(BibleBookEnum.Genesis, 1, (verse,)),),
        "Genesis Local",
    )
    return verse, book


def test_search_mode_options_and_range_validation_matrix() -> None:
    assert SearchMode.coerce(SearchMode.ALL) is SearchMode.ALL
    assert SearchMode.coerce(" ANY ") is SearchMode.ANY
    assert SearchMode.any is SearchMode.ANY
    assert str(SearchMode.EXACT) == "exact"
    with pytest.raises(TypeError, match="SearchMode or string"):
        SearchMode.coerce(1)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        SearchMode.coerce("missing")

    for name in (
        "case_sensitive",
        "whole_words",
        "normalize_unicode",
        "ignore_diacritics",
    ):
        with pytest.raises(TypeError, match=name):
            SearchOptions(**{name: 1})  # type: ignore[arg-type]
    for values in (
        {"max_results": True},
        {"max_results": -1},
        {"offset": True},
        {"offset": -1},
        {"chapter": True},
        {"chapter": 0},
        {"verse": -1},
    ):
        with pytest.raises((TypeError, ValueError)):
            SearchOptions(**values)
    with pytest.raises(TypeError, match="hashable"):
        SearchOptions(book=[])  # type: ignore[arg-type]

    empty = TextRange(2, 2)
    assert empty.is_empty and empty.length == 0
    assert empty.to_slice() == slice(2, 2)
    assert 2 not in empty and True not in empty
    with pytest.raises(TypeError):
        TextRange(True, 2)
    with pytest.raises(ValueError):
        TextRange(-1, 2)
    with pytest.raises(ValueError):
        empty.contains(-1)


def test_search_hit_named_constructor_and_validation_matrix() -> None:
    verse, book = _models()
    hit = SearchHit.new(
        verse,
        book,
        "Custom 1:1",
        ((0, 5), range(6, 10)),
        0,
        len(verse.text),
    )
    assert hit.reference == "Custom 1:1"
    assert hit.match_ranges == (TextRange(0, 5), TextRange(6, 10))
    assert not hit.has_leading_omission and not hit.has_trailing_omission
    assert hit != object()

    wrong_book = Book(
        BibleBookEnum.Exodus,
        (
            Chapter(
                BibleBookEnum.Exodus,
                1,
                (Verse(BibleBookEnum.Exodus, 1, 1, "alpha beta"),),
            ),
        ),
    )
    with pytest.raises(ValueError, match="contain the matched verse"):
        SearchHit(verse, wrong_book)
    with pytest.raises(TypeError, match="reference"):
        SearchHit(verse, book, reference=1)  # type: ignore[arg-type]
    with pytest.raises((TypeError, ValueError)):
        SearchHit(verse, book, match_ranges=(object(),))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="snippet bounds"):
        SearchHit(verse, book, snippet_start=5, snippet_end=4)
    with pytest.raises(TypeError, match="snippet_start"):
        SearchHit(verse, book, snippet_start=True)
    with pytest.raises(ValueError, match="positive"):
        SearchHit.with_context(verse, book, (), 0)


@pytest.mark.parametrize(
    "cluster",
    (
        "\U0001f469\u200d\U0001f469\u200d\U0001f467\u200d\U0001f466",
        "\U0001f1ee\U0001f1f1",
        "\U0001f44d\U0001f3fd",
        "\u1100\u1161",
    ),
)
def test_context_snippets_never_split_extended_graphemes(cluster: str) -> None:
    text = f"x{cluster}y"
    verse = Verse(BibleBookEnum.Genesis, 1, 1, text)
    book = Book(
        BibleBookEnum.Genesis,
        (Chapter(BibleBookEnum.Genesis, 1, (verse,)),),
    )
    hit = SearchHit.with_context(
        verse,
        book,
        (TextRange(1, 1 + len(cluster)),),
        1,
    )

    assert hit.snippet == cluster
    assert hit.snippet_match_ranges == (TextRange(0, len(cluster)),)


def test_search_results_collection_and_validation_matrix() -> None:
    verse, book = _models()
    hit = SearchHit(verse, book, match_ranges=((0, 5),))
    results = SearchResults.from_hits("alpha", (hit,), total_count=1)

    assert results and not results.is_empty and results.is_not_empty
    assert len(results) == results.count == 1
    assert tuple(results) == (verse,)
    assert results.by_chapter_location() == {
        (BibleBookEnum.Genesis, 1): (verse,)
    }
    assert results != object()

    with pytest.raises(TypeError, match="query"):
        SearchResults(1)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="has_more"):
        SearchResults("q", has_more=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="equal lengths"):
        SearchResults("q", (verse,), (hit, hit))
    other = verse.with_text("different")
    with pytest.raises(ValueError, match="corresponding verses"):
        SearchResults("q", (other,), (hit,))
    with pytest.raises(ValueError, match="has_more"):
        SearchResults.from_verses("q", (), total_count=0, has_more=True)
    with pytest.raises(ValueError, match="returned page"):
        SearchResults.from_verses("q", (verse,), offset=1, total_count=1)


def test_search_index_constructor_and_value_validation_matrix() -> None:
    verse, _ = _models()
    location = (BibleBookEnum.Genesis, 1, 1)
    index = build_search_index((verse,))

    assert index == SearchIndex.from_verses((verse,))
    assert hash(index) == hash(SearchIndex.from_verses((verse,)))
    assert index != object()
    assert bool(index) and index.posting_count > 0
    assert SearchIndex().posting_count == 0 and not SearchIndex()
    with pytest.raises(TypeError, match="query"):
        index.search(1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="nonempty"):
        SearchIndex({"": (location,)})
    with pytest.raises(TypeError, match="three-item sequence"):
        SearchIndex({"alpha": (1,)})  # type: ignore[dict-item]
    with pytest.raises(ValueError, match="contain book, chapter, and verse"):
        SearchIndex({"alpha": ((BibleBookEnum.Genesis, 1),)})  # type: ignore[dict-item]
    with pytest.raises(TypeError, match="hashable"):
        SearchIndex({"alpha": (([], 1, 1),)})  # type: ignore[dict-item]
    with pytest.raises(TypeError, match="chapter"):
        SearchIndex({"alpha": ((BibleBookEnum.Genesis, True, 1),)})
    with pytest.raises(ValueError, match="verse must be positive"):
        SearchIndex({"alpha": ((BibleBookEnum.Genesis, 1, 0),)})
    with pytest.raises(TypeError, match="verse texts"):
        SearchIndex({"alpha": (location,)}, texts={location: 1})  # type: ignore[dict-item]
    with pytest.raises(ValueError, match="every location"):
        SearchIndex({"alpha": (location,)}, texts={})

    duplicate = verse.copy_with()
    with pytest.raises(ValueError, match="duplicate verse location"):
        SearchIndex.from_verses((verse, duplicate))

    class UnhashableBookVerse:
        book: Hashable = []  # type: ignore[assignment]
        chapter_number = 1
        verse_number = 1
        text = "alpha"

    with pytest.raises(TypeError, match="book identifiers must be hashable"):
        SearchIndex.from_verses((UnhashableBookVerse(),))


def test_public_search_wrappers_reject_bad_inputs_and_agree() -> None:
    verse, book = _models()
    options = SearchOptions(mode=SearchMode.ALL)

    assert matches_search_text(verse.text, "alpha beta", options)
    assert fuzzy_matches(verse.text, "alpha betx", options, 1)
    assert find_match_ranges(verse.text, "alpha", options) == (TextRange(0, 5),)
    assert search_verses((verse,), "alpha", options, book_resolver={verse.book: book})

    with pytest.raises(TypeError, match="text"):
        matches_search_text(1, "q", options)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="query"):
        matches_search_text("text", 1, options)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="options"):
        matches_search_text("text", "q", object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="max_distance"):
        fuzzy_matches("text", "q", options, True)
    with pytest.raises(ValueError, match="must not be negative"):
        fuzzy_matches("text", "q", options, -1)
