"""Focused v1 search contracts that do not require loading a Bible file."""

from __future__ import annotations

from types import MappingProxyType

import pytest
from bible_io_references import BibleBookEnum

from bible_io.book import Book
from bible_io.chapter import Chapter
from bible_io.search import (
    SearchHit,
    SearchMode,
    SearchOptions,
    SearchResults,
    TextRange,
    find_match_ranges,
    fuzzy_match_ranges,
    matches_search_text,
    search_verses,
)
from bible_io.search_index import SearchIndex
from bible_io.text_search import (
    build_search_index_terms,
    contains_normalized_text,
    extract_unicode_words,
    find_normalized_substring_ranges,
    is_within_levenshtein_distance,
    normalize_search_text,
    search_index_lookup_key,
    tokenize_search_text,
    tokenize_search_text_with_ranges,
    uses_unspaced_word_boundaries,
)
from bible_io.verse import Verse


@pytest.fixture()
def small_models() -> tuple[tuple[Verse, ...], dict[BibleBookEnum, Book]]:
    genesis_verses = (
        Verse(
            BibleBookEnum.Genesis,
            1,
            1,
            "Café alpha beta Straße.",
        ),
        Verse(
            BibleBookEnum.Genesis,
            1,
            2,
            "beta ALPHA; in the beginning",
        ),
        Verse(BibleBookEnum.Genesis, 1, 3, "起初神创造天地"),
    )
    exodus_verses = (
        Verse(BibleBookEnum.Exodus, 1, 1, "gamma κόσμος"),
    )
    genesis = Book(
        BibleBookEnum.Genesis,
        (Chapter(BibleBookEnum.Genesis, 1, genesis_verses),),
        "Genesis Local",
    )
    exodus = Book(
        BibleBookEnum.Exodus,
        (Chapter(BibleBookEnum.Exodus, 1, exodus_verses),),
        "Exodus Local",
    )
    verses = genesis_verses + exodus_verses
    return verses, {
        BibleBookEnum.Genesis: genesis,
        BibleBookEnum.Exodus: exodus,
    }


def test_normalization_casefold_and_opt_in_diacritic_folding() -> None:
    assert normalize_search_text("Straße") == "strasse"
    assert normalize_search_text("Cafe\u0301") == "café"
    assert normalize_search_text("CAFÉ", ignore_diacritics=True) == "cafe"
    assert contains_normalized_text("A Cafe\u0301 noir", "CAFÉ")
    assert not contains_normalized_text("A café noir", "cafe")
    assert contains_normalized_text(
        "A café noir",
        "cafe",
        ignore_diacritics=True,
    )
    assert normalize_search_text("MiXeD", case_sensitive=True) == "MiXeD"


def test_unicode_tokenization_words_and_source_range_mapping() -> None:
    text = "Cafe\u0301, שלום κόσμος 123"
    tokens = tokenize_search_text_with_ranges(text)

    assert tuple(token.normalized for token in tokens) == (
        "café",
        "שלום",
        "κόσμοσ",
        "123",
    )
    assert tokens[0].raw == "Cafe\u0301"
    assert (tokens[0].start, tokens[0].end) == (0, 5)
    assert tokenize_search_text(text) == tuple(token.normalized for token in tokens)
    assert extract_unicode_words(text) == (
        "Cafe\u0301",
        "שלום",
        "κόσμος",
        "123",
    )
    assert find_normalized_substring_ranges(text, "CAFÉ") == (range(0, 5),)
    assert text[0:5] == "Cafe\u0301"


def test_unspaced_script_terms_lookup_and_precise_ranges() -> None:
    text = "起初神创造天地"
    assert uses_unspaced_word_boundaries(text)
    terms = build_search_index_terms(text, 3)
    assert {"创", "创造", "创造天", text}.issubset(terms)
    assert search_index_lookup_key("创造天地", 3) == "创造天"

    options = SearchOptions(mode="all")
    assert matches_search_text(text, "创造", options)
    ranges = find_match_ranges(text, "创造", options)
    assert ranges == (TextRange(3, 5),)
    assert text[ranges[0].to_slice()] == "创造"


def test_search_options_validate_and_copy_can_clear_nullable_values() -> None:
    options = SearchOptions(
        mode="ALL",
        max_results=5,
        book=BibleBookEnum.Genesis,
        chapter=2,
        verse=3,
    )
    assert options.mode is SearchMode.ALL
    assert options.validate() is options

    cleared = options.copy_with(
        max_results=None,
        book=None,
        chapter=None,
        verse=None,
    )
    assert cleared.max_results is None
    assert cleared.book is None
    assert cleared.chapter is None
    assert cleared.verse is None
    assert options.max_results == 5

    with pytest.raises(ValueError, match="chapter must be positive"):
        SearchOptions(chapter=0)
    with pytest.raises(ValueError, match="offset must not be negative"):
        SearchOptions(offset=-1)
    with pytest.raises(ValueError):
        SearchOptions(mode="unsupported")


def test_exact_all_any_and_whole_word_semantics(
    small_models: tuple[tuple[Verse, ...], dict[BibleBookEnum, Book]],
) -> None:
    verses, _ = small_models
    exact = SearchOptions(mode="exact")
    all_terms = SearchOptions(mode="all")
    any_term = SearchOptions(mode="any")

    assert tuple(search_verses(verses, "alpha beta", exact)) == (verses[0],)
    assert tuple(search_verses(verses, "alpha beta", all_terms)) == verses[:2]
    assert tuple(search_verses(verses, "gamma alpha", any_term)) == (
        verses[0],
        verses[1],
        verses[3],
    )
    assert matches_search_text("faithful", "faith", exact)
    assert not matches_search_text(
        "faithful",
        "faith",
        exact.copy_with(whole_words=True),
    )
    assert tuple(search_verses(verses, "", SearchOptions(book=BibleBookEnum.Exodus))) == (
        verses[3],
    )


def test_fuzzy_unicode_distance_normalization_and_ranges() -> None:
    assert is_within_levenshtein_distance("κόσμος", "κόσμοσ", 1)
    assert not is_within_levenshtein_distance("beginning", "ending", 1)

    options = SearchOptions(ignore_diacritics=True)
    exact_folded = fuzzy_match_ranges("In the beginníng", "beginning", options, 0)
    assert exact_folded == (TextRange(7, 16),)
    typo = fuzzy_match_ranges("In the beginning", "beginnig", options, 1)
    assert typo == (TextRange(7, 16),)
    assert fuzzy_match_ranges("In the beginning", "beginnig", options, 0) is None

    chinese = fuzzy_match_ranges(
        "起初神创造天地",
        "创迼",
        SearchOptions(mode="all"),
        1,
    )
    assert chinese == (TextRange(3, 5),)


def test_text_range_and_search_hit_snippets_are_exact_and_relative() -> None:
    text = "prefix alpha suffix"
    verse = Verse(BibleBookEnum.Genesis, 1, 1, text)
    chapter = Chapter(BibleBookEnum.Genesis, 1, (verse,))
    book = Book(BibleBookEnum.Genesis, (chapter,), "Genesis Local")
    matched = TextRange(7, 12)

    assert len(matched) == 5
    assert matched.contains(8)
    assert 12 not in matched
    with pytest.raises(ValueError):
        TextRange(2, 1)

    hit = SearchHit(verse, book, None, (matched,), 4, 15)
    assert hit.reference == "Genesis Local 1:1"
    assert hit.snippet == text[4:15]
    assert hit.snippet_bounds == TextRange(4, 15)
    assert hit.snippet_match_ranges == (TextRange(3, 8),)
    assert hit.has_leading_omission
    assert hit.has_trailing_omission

    decomposed = "xxxxCafe\u0301yyyy"
    decomposed_verse = Verse(BibleBookEnum.Genesis, 1, 2, decomposed)
    decomposed_chapter = Chapter(
        BibleBookEnum.Genesis,
        1,
        (verse, decomposed_verse),
    )
    decomposed_book = Book(
        BibleBookEnum.Genesis,
        (decomposed_chapter,),
        "Genesis Local",
    )
    context = SearchHit.with_context(
        decomposed_verse,
        decomposed_book,
        (TextRange(4, 9),),
        5,
    )
    assert context.snippet == "Cafe\u0301"
    assert context.snippet_match_ranges == (TextRange(0, 5),)


def test_search_results_pagination_hits_and_grouping(
    small_models: tuple[tuple[Verse, ...], dict[BibleBookEnum, Book]],
) -> None:
    verses, books = small_models
    first = search_verses(
        verses,
        "alpha beta",
        SearchOptions(mode="all", max_results=1),
        book_resolver=books,
    )
    assert first.count == 1
    assert first.has_more
    assert first.total_count is None
    assert first.next_offset == 1
    assert first.hits[0].book_name == "Genesis Local"
    assert first.by_book()[BibleBookEnum.Genesis] == (verses[0],)
    assert first.by_chapter()["Genesis 1"] == (verses[0],)
    assert first.by_display_chapter()["Genesis Local 1"] == (verses[0],)
    assert isinstance(first.by_book(), MappingProxyType)

    final = search_verses(
        verses,
        "alpha beta",
        SearchOptions(mode="all", max_results=1, offset=1),
        book_resolver=books,
    )
    assert final.total_count == 2
    assert not final.has_more
    assert final.has_previous
    assert final.next_offset is None

    with pytest.raises(ValueError, match="duplicate verse locations"):
        SearchResults.from_verses("alpha", (verses[0], verses[0]))


def test_search_index_is_immutable_and_matches_all_distinct_terms(
    small_models: tuple[tuple[Verse, ...], dict[BibleBookEnum, Book]],
) -> None:
    verses, _ = small_models
    index = SearchIndex.from_verses(verses)

    assert len(index) > 0
    assert index.posting_count >= len(verses)
    assert index.search("alpha beta") == (
        (BibleBookEnum.Genesis, 1, 1),
        (BibleBookEnum.Genesis, 1, 2),
    )
    assert index.search("alpha ALPHA") == (
        (BibleBookEnum.Genesis, 1, 1),
        (BibleBookEnum.Genesis, 1, 2),
    )
    assert index.search("创造") == ((BibleBookEnum.Genesis, 1, 3),)
    assert index.search("not-present") == ()
    assert index.search("") == ()
    with pytest.raises(TypeError):
        index.index["new"] = ()  # type: ignore[index]


def test_search_index_verifies_long_unspaced_candidates() -> None:
    location = (BibleBookEnum.Genesis, 1, 1)
    verse = Verse(BibleBookEnum.Genesis, 1, 1, "\u521b\u9020\u5929\u7532")
    index = SearchIndex.from_verses((verse,))

    assert index.search("\u521b\u9020\u5929\u7532") == (location,)
    assert index.search("\u521b\u9020\u5929\u5730") == ()

    manually_built = SearchIndex(
        {
            term: (location,)
            for term in build_search_index_terms(verse.text)
        }
    )
    assert manually_built.search("\u521b\u9020\u5929\u5730") == ()

    with pytest.raises(ValueError, match="contain duplicates"):
        SearchIndex({"term": (location, location)})
