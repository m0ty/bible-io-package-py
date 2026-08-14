"""High-value behavioral parity checks ported from the Rust package.

These tests intentionally use tiny in-memory editions.  They complement the
existing Python tests with the adversarial schema, value-semantics, navigation,
pagination, and index-lifecycle matrices exercised by the Rust 1.1 suite.
"""

from __future__ import annotations

from collections.abc import Mapping
from itertools import permutations, product
from typing import Any

import pytest

from bible_io import (
    Bible,
    BibleBookEnum,
    BibleDataFormatError,
    BibleDataFormatErrorCode,
    BibleDataValidationOptions,
    BibleLoadOptions,
    BibleLocation,
    Book,
    BookNotFoundError,
    Chapter,
    ChapterNotFoundError,
    EditionVerseRange,
    SearchHit,
    SearchIndexMode,
    SearchOptions,
    SearchResults,
    TextRange,
    Verse,
    VerseNotFoundError,
    VerseRef,
    is_within_levenshtein_distance,
    reference_from_osis_identifier,
    reference_from_usfm_identifier,
)


def _load(
    document: object,
    *,
    validation: BibleDataValidationOptions = BibleDataValidationOptions.STRICT,
    mode: SearchIndexMode = SearchIndexMode.DISABLED,
) -> Bible:
    return Bible.from_decoded_json(
        document,
        options=BibleLoadOptions(
            validation=validation,
            search_index_mode=mode,
        ),
    )


def _one_verse_book(text: str) -> dict[str, object]:
    return {"chapters": {"1": {"1": text}}}


def _three_book_document(order: tuple[str, ...]) -> dict[str, object]:
    return {
        "language": "English",
        "bookOrder": list(order),
        "books": {
            "gn": {"chapters": {"3": {"5": "gn"}}},
            "ex": {"chapters": {"2": {"4": "ex"}}},
            "jo": {"chapters": {"7": {"9": "jo"}}},
        },
    }


_COORDINATES = {
    "gn": (BibleBookEnum.Genesis, 3, 5),
    "ex": (BibleBookEnum.Exodus, 2, 4),
    "jo": (BibleBookEnum.John, 7, 9),
}


def _reference(identifier: str) -> VerseRef:
    return VerseRef(*_COORDINATES[identifier])


def _location(identifier: str) -> BibleLocation:
    return BibleLocation(*_COORDINATES[identifier])


def _texts(values: object) -> tuple[str, ...]:
    return tuple(verse.text for verse in values)  # type: ignore[attr-defined]


def _endpoint_bible() -> Bible:
    return _load(
        {
            "language": "English",
            "bookOrder": ["ex", "gn"],
            "books": {
                "ex": {"chapters": {"2": {"2": "e22", "5": "e25"}}},
                "gn": {
                    "chapters": {
                        "1": {"1": "g11", "4": "g14"},
                        "3": {"2": "g32"},
                    }
                },
            },
        }
    )


def test_numeric_map_keys_follow_dart_integer_parsing_and_canonicalize() -> None:
    bible = _load(
        {
            "books": {
                "gn": {
                    "chapters": {
                        " +1 ": {" 3 ": "one-three", "+1": "one-one"},
                        " 2 ": {"01": "two-one"},
                    }
                }
            }
        }
    )

    genesis = bible.get_book(BibleBookEnum.Genesis)
    assert tuple(chapter.number for chapter in genesis.chapters) == (1, 2)
    assert tuple(verse.number for verse in genesis.get_verses(1)) == (1, 3)
    assert bible.to_dict()["books"]["gn"]["chapters"] == {
        "1": {"1": "one-one", "3": "one-three"},
        "2": {"1": "two-one"},
    }


@pytest.mark.parametrize(
    "invalid",
    ("", "0", "-1", "1.0", "9223372036854775808"),
)
def test_invalid_numeric_keys_retain_code_path_and_value(invalid: str) -> None:
    with pytest.raises(BibleDataFormatError) as caught:
        _load(
            {
                "books": {
                    "gn": {"chapters": {invalid: {"1": "text"}}},
                }
            }
        )

    assert caught.value.code is BibleDataFormatErrorCode.INVALID_VALUE
    assert caught.value.path == f'$.books.gn.chapters["{invalid}"]'
    assert caught.value.has_value
    assert caught.value.value == invalid


def test_duplicate_numeric_and_book_aliases_report_the_offending_key() -> None:
    with pytest.raises(BibleDataFormatError) as duplicate_chapter:
        _load(
            {
                "books": {
                    "gn": {
                        "chapters": {
                            "1": {"1": "first"},
                            "01": {"1": "duplicate"},
                        }
                    }
                }
            }
        )
    assert duplicate_chapter.value.code is BibleDataFormatErrorCode.INVALID_VALUE
    assert duplicate_chapter.value.path == '$.books.gn.chapters["01"]'
    assert duplicate_chapter.value.value == "01"

    with pytest.raises(BibleDataFormatError) as duplicate_book:
        _load(
            {
                "books": {
                    "gn": _one_verse_book("first"),
                    "GEN": _one_verse_book("duplicate"),
                }
            }
        )
    assert duplicate_book.value.code is BibleDataFormatErrorCode.INVALID_VALUE
    assert duplicate_book.value.path == "$.books.GEN"
    assert duplicate_book.value.value == "GEN"


def test_book_order_errors_preserve_exact_code_path_and_value() -> None:
    books = {
        "gn": _one_verse_book("gn"),
        "ex": _one_verse_book("ex"),
        "jo": _one_verse_book("jo"),
    }
    cases = (
        (["gn", 7, "ex"], BibleDataFormatErrorCode.INVALID_TYPE, 7),
        (["gn", " ", "ex"], BibleDataFormatErrorCode.INVALID_VALUE, " "),
        (["gn", "GEN", "ex"], BibleDataFormatErrorCode.INVALID_VALUE, "GEN"),
        (["gn", "mt", "ex"], BibleDataFormatErrorCode.INVALID_VALUE, "mt"),
    )

    for order, code, value in cases:
        with pytest.raises(BibleDataFormatError) as caught:
            _load({"bookOrder": order, "books": books})
        assert caught.value.code is code
        assert caught.value.path == "$.bookOrder[1]"
        assert caught.value.value == value

    with pytest.raises(BibleDataFormatError) as incomplete:
        _load({"bookOrder": ["gn", "ex"], "books": books})
    assert incomplete.value.code is BibleDataFormatErrorCode.INVALID_VALUE
    assert incomplete.value.path == "$.bookOrder"
    assert incomplete.value.value == ["jo"]


def test_permissive_validation_only_relaxes_skeletal_content() -> None:
    with pytest.raises(BibleDataFormatError) as strict:
        _load({"books": {}})
    assert strict.value.code is BibleDataFormatErrorCode.INVALID_VALUE
    assert strict.value.path == "$.books"
    assert strict.value.value == {}

    empty = _load(
        {"books": {}},
        validation=BibleDataValidationOptions.PERMISSIVE,
    )
    assert empty.books == ()
    assert empty.search("anything") == []
    assert not empty.has_search_index

    empty_book = _load(
        {"books": {"gn": {"chapters": {}}}},
        validation=BibleDataValidationOptions.PERMISSIVE,
    )
    assert empty_book.stats.verses_per_book[BibleBookEnum.Genesis] == 0

    invalid_documents: tuple[tuple[object, str], ...] = (
        ({"schemaVersion": None, "books": {}}, "$.schemaVersion"),
        ({"schemaVersion": 2, "books": {}}, "$.schemaVersion"),
        ({"books": None}, "$.books"),
        ({"books": []}, "$.books"),
        ({"books": {"gn": {"chapters": None}}}, "$.books.gn.chapters"),
        (
            {"books": {"gn": {"chapters": {"1": {"verses": None}}}}},
            '$.books.gn.chapters["1"].verses',
        ),
    )
    for document, path in invalid_documents:
        with pytest.raises(BibleDataFormatError) as caught:
            _load(
                document,
                validation=BibleDataValidationOptions.PERMISSIVE,
            )
        assert caught.value.path == path
        assert caught.value.code in {
            BibleDataFormatErrorCode.INVALID_TYPE,
            BibleDataFormatErrorCode.INVALID_VALUE,
        }


def test_legacy_arrays_load_and_serialize_as_canonical_maps() -> None:
    bible = _load(
        {
            "books": {
                "gn": {
                    "name": "Genesis",
                    "chapters": [["one", "two"], ["three"]],
                }
            }
        }
    )

    assert bible.get_verse(BibleBookEnum.Genesis, 2, 1).text == "three"
    assert bible.to_dict()["books"]["gn"]["chapters"] == {
        "1": {"1": "one", "2": "two"},
        "2": {"1": "three"},
    }


def test_models_defensively_own_inputs_and_hash_nested_values() -> None:
    annotations: dict[str, Any] = {
        "z": {"nested": [1, 2]},
        "a": True,
    }
    first = Verse(
        BibleBookEnum.Genesis,
        1,
        1,
        "kósmos",
        annotations=annotations,
    )
    equal = Verse(
        BibleBookEnum.Genesis,
        1,
        1,
        "kósmos",
        annotations={"a": True, "z": {"nested": [1, 2]}},
    )
    annotations["z"]["nested"].append(3)
    assert first == equal
    assert hash(first) == hash(equal)
    nested = first.annotations["z"]
    assert isinstance(nested, Mapping)
    assert nested["nested"] == (1, 2)
    assert first.with_annotations({}).annotations == {}

    verse_nine = Verse(BibleBookEnum.Genesis, 4, 9, "ninth")
    verse_two = Verse(BibleBookEnum.Genesis, 4, 2, "second")
    input_verses = [verse_two, verse_nine]
    chapter_four = Chapter(BibleBookEnum.Genesis, 4, input_verses)
    input_verses.clear()
    assert chapter_four.verses == (verse_two, verse_nine)

    chapter_seven = Chapter(
        BibleBookEnum.Genesis,
        7,
        (Verse(BibleBookEnum.Genesis, 7, 11, "eleventh"),),
    )
    input_chapters = [chapter_four, chapter_seven]
    genesis = Book(BibleBookEnum.Genesis, input_chapters, "Genesis Local")
    input_chapters.clear()
    assert genesis.chapters == (chapter_four, chapter_seven)

    input_books = [genesis]
    bible = Bible.from_books(
        input_books,
        search_index_mode=SearchIndexMode.DISABLED,
    )
    input_books.clear()
    assert bible.books == (genesis,)
    assert bible == bible.copy_with()
    assert hash(bible) == hash(bible.copy_with())
    with pytest.raises(ValueError, match="unique book identifiers"):
        Bible.from_books(
            (genesis, genesis),
            search_index_mode=SearchIndexMode.DISABLED,
        )


def test_every_book_order_permutation_drives_navigation_and_ranges() -> None:
    for raw_order in permutations(("gn", "ex", "jo")):
        order = tuple(raw_order)
        bible = _load(_three_book_document(order))
        locations = tuple(_location(identifier) for identifier in order)

        assert _texts(bible.all_verses) == order
        assert bible.to_dict()["bookOrder"] == list(order)
        assert bible.previous_verse(locations[0]) is None
        assert bible.next_verse(locations[0]) == locations[1]
        assert bible.previous_verse(locations[1]) == locations[0]
        assert bible.next_verse(locations[1]) == locations[2]
        assert bible.next_verse(locations[2]) is None

        typed = EditionVerseRange(
            _reference(order[0]),
            _reference(order[2]),
        )
        assert _texts(bible.resolve_edition_range(typed)) == order

        first = locations[0]
        last = locations[2]
        textual = (
            f"{first.book.full_name} {first.chapter}:{first.verse}-"
            f"{last.book.full_name} {last.chapter}:{last.verse}"
        )
        assert _texts(bible.get_verse_range_by_ref(textual)) == order


def test_osis_and_usfm_ranges_resolve_through_loaded_edition_values() -> None:
    bible = _load(
        {
            "bookOrder": ["gn", "ex"],
            "books": {
                "gn": {
                    "chapters": {
                        "1": {"1": "g11", "2": "g12"},
                        "2": {"1": "g21"},
                    }
                },
                "ex": {"chapters": {"1": {"1": "e11", "2": "e12"}}},
            },
        }
    )

    osis = reference_from_osis_identifier("Gen.1.2-Exod.1.1")
    usfm = reference_from_usfm_identifier("GEN-EXO 1:2-1:1")
    assert _texts(bible.resolve_reference(osis)) == ("g12", "g21", "e11")
    assert _texts(bible.resolve_reference(usfm)) == ("g12", "g21", "e11")


def test_sparse_navigation_crosses_empty_chapters_and_books() -> None:
    genesis = Book(
        BibleBookEnum.Genesis,
        (
            Chapter(
                BibleBookEnum.Genesis,
                2,
                (
                    Verse(BibleBookEnum.Genesis, 2, 5, "five"),
                    Verse(BibleBookEnum.Genesis, 2, 2, "two"),
                ),
            ),
            Chapter(BibleBookEnum.Genesis, 7, ()),
        ),
    )
    exodus = Book(BibleBookEnum.Exodus, ())
    leviticus = Book(
        BibleBookEnum.Leviticus,
        (
            Chapter(
                BibleBookEnum.Leviticus,
                3,
                (Verse(BibleBookEnum.Leviticus, 3, 9, "nine"),),
            ),
        ),
    )
    bible = Bible.from_books(
        (genesis, exodus, leviticus),
        validation=BibleDataValidationOptions.PERMISSIVE,
        search_index_mode=SearchIndexMode.DISABLED,
    )

    genesis_two = BibleLocation(BibleBookEnum.Genesis, 2)
    genesis_seven = BibleLocation(BibleBookEnum.Genesis, 7)
    leviticus_three = BibleLocation(BibleBookEnum.Leviticus, 3)
    assert bible.next_chapter(genesis_two) == genesis_seven
    assert bible.next_chapter(genesis_seven) == leviticus_three
    assert bible.previous_chapter(leviticus_three) == genesis_seven

    genesis_two_two = BibleLocation(BibleBookEnum.Genesis, 2, 2)
    genesis_two_five = BibleLocation(BibleBookEnum.Genesis, 2, 5)
    leviticus_three_nine = BibleLocation(BibleBookEnum.Leviticus, 3, 9)
    assert bible.next_verse(genesis_two_two) == genesis_two_five
    assert bible.next_verse(genesis_two_five) == leviticus_three_nine
    assert bible.previous_verse(leviticus_three_nine) == genesis_two_five


def test_edition_ranges_validate_both_endpoints_before_collecting() -> None:
    bible = _endpoint_bible()
    start = VerseRef(BibleBookEnum.Exodus, 2, 2)
    end = VerseRef(BibleBookEnum.Genesis, 3, 2)

    assert _texts(
        bible.resolve_edition_range(EditionVerseRange(start, end))
    ) == ("e22", "e25", "g11", "g14", "g32")

    cases = (
        (
            EditionVerseRange(VerseRef(BibleBookEnum.John, 1, 1), end),
            BookNotFoundError,
        ),
        (
            EditionVerseRange(VerseRef(BibleBookEnum.Exodus, 9, 1), end),
            ChapterNotFoundError,
        ),
        (
            EditionVerseRange(VerseRef(BibleBookEnum.Exodus, 2, 1), end),
            VerseNotFoundError,
        ),
        (
            EditionVerseRange(start, VerseRef(BibleBookEnum.John, 1, 1)),
            BookNotFoundError,
        ),
        (
            EditionVerseRange(start, VerseRef(BibleBookEnum.Genesis, 2, 1)),
            ChapterNotFoundError,
        ),
        (
            EditionVerseRange(start, VerseRef(BibleBookEnum.Genesis, 3, 1)),
            VerseNotFoundError,
        ),
    )
    for verse_range, error_type in cases:
        with pytest.raises(error_type):
            bible.resolve_edition_range(verse_range)

    descending = (
        EditionVerseRange(
            VerseRef(BibleBookEnum.Genesis, 1, 1),
            VerseRef(BibleBookEnum.Exodus, 2, 5),
        ),
        EditionVerseRange(
            VerseRef(BibleBookEnum.Genesis, 3, 2),
            VerseRef(BibleBookEnum.Genesis, 1, 4),
        ),
        EditionVerseRange(
            VerseRef(BibleBookEnum.Genesis, 1, 4),
            VerseRef(BibleBookEnum.Genesis, 1, 1),
        ),
    )
    for verse_range in descending:
        with pytest.raises(ValueError, match="start must come before"):
            bible.resolve_edition_range(verse_range)


def test_edition_range_allows_an_identical_start_and_end() -> None:
    bible = _endpoint_bible()
    reference = VerseRef(BibleBookEnum.Exodus, 2, 2)

    assert _texts(
        bible.resolve_edition_range(EditionVerseRange(reference, reference))
    ) == ("e22",)


def test_chapter_passage_rejects_an_unloaded_intermediate_chapter() -> None:
    bible = _endpoint_bible()

    with pytest.raises(ChapterNotFoundError) as caught:
        bible.get_passage("Genesis 1-3")
    assert caught.value.context == {
        "book": BibleBookEnum.Genesis,
        "chapter": 2,
    }


def test_blank_query_pagination_matrix_has_exact_stable_metadata() -> None:
    bible = _load(
        {
            "books": {
                "gn": {
                    "chapters": {
                        "1": {
                            "1": "one",
                            "2": "two",
                            "3": "three",
                            "4": "four",
                            "5": "five",
                        }
                    }
                }
            }
        }
    )
    expected = (1, 2, 3, 4, 5)

    for offset in range(7):
        for limit in (None, 0, 1, 2, 5, 8):
            results = bible.search_with_options(
                "",
                SearchOptions(offset=offset, max_results=limit),
            )
            start = min(offset, len(expected))
            page_length = min(
                len(expected) - start,
                len(expected) if limit is None else limit,
            )
            end = start + page_length
            page = expected[start:end]

            assert tuple(getattr(verse, "number") for verse in results.verses) == page
            assert len(results.hits) == len(page)
            assert results.has_more is (end < len(expected))
            assert results.total_count == (
                None if results.has_more else len(expected)
            )
            assert results.next_offset == (
                offset + len(page) if results.has_more and page else None
            )
            assert results.has_previous is (offset > 0)


def test_search_hit_and_result_pages_have_deep_value_validation() -> None:
    verse = Verse(BibleBookEnum.Genesis, 1, 1, "alpha beta")
    equal_verse = Verse(BibleBookEnum.Genesis, 1, 1, "alpha beta")
    book = Book(
        BibleBookEnum.Genesis,
        (Chapter(BibleBookEnum.Genesis, 1, (verse,)),),
        "Genesis Local",
    )
    equal_book = Book(
        BibleBookEnum.Genesis,
        (Chapter(BibleBookEnum.Genesis, 1, (equal_verse,)),),
        "Genesis Local",
    )
    hit = SearchHit(verse, book, match_ranges=(TextRange(0, 5),))
    equal_hit = SearchHit(
        equal_verse,
        equal_book,
        match_ranges=(TextRange(0, 5),),
    )
    assert hit == equal_hit
    assert hash(hit) == hash(equal_hit)

    first_page = SearchResults.from_hits(
        "alpha",
        (hit,),
        total_count=1,
    )
    equal_page = SearchResults.from_hits(
        "alpha",
        (equal_hit,),
        total_count=1,
    )
    assert first_page == equal_page
    assert hash(first_page) == hash(equal_page)

    with pytest.raises(ValueError, match="nonoverlapping"):
        SearchHit(
            verse,
            book,
            match_ranges=(TextRange(0, 5), TextRange(4, 7)),
        )
    with pytest.raises(ValueError, match="inside the verse"):
        SearchHit(verse, book, match_ranges=(TextRange(0, 20),))
    with pytest.raises(ValueError, match="page exceeds"):
        SearchResults.from_verses("alpha", (verse,), limit=0)
    with pytest.raises(ValueError, match="must include"):
        SearchResults.from_verses("alpha", (verse,), total_count=0)
    with pytest.raises(ValueError, match="must agree"):
        SearchResults.from_verses(
            "alpha",
            (verse,),
            total_count=1,
            has_more=True,
        )


def test_index_metrics_follow_prewarm_clear_and_disabled_lifecycle() -> None:
    document = {
        "bookOrder": ["gn", "ex"],
        "books": {
            "gn": {"chapters": {"1": {"1": "alpha 😀"}}},
            "ex": {"chapters": {"1": {"1": "创造天地"}}},
        },
    }
    lazy = _load(document, mode=SearchIndexMode.LAZY)
    texts = tuple(verse.text for verse in lazy.all_verses)

    cold = lazy.performance_metrics
    assert not cold.search_index_built
    assert cold.search_index_size == 0
    assert cold.posting_count == 0
    assert cold.verse_count == 2
    assert cold.text_bytes == sum(len(text.encode("utf-8")) for text in texts)
    assert cold.text_characters == sum(len(text) for text in texts)
    assert cold.text_utf16_code_units == sum(
        len(text.encode("utf-16-le")) // 2 for text in texts
    )
    assert cold.memory_usage_kib > 0

    lazy.prewarm_search_index()
    warm = lazy.performance_metrics
    assert warm.search_index_built
    assert warm.search_index_size > 0
    assert warm.posting_count >= warm.verse_count

    lazy.clear_search_index()
    cleared = lazy.performance_metrics
    assert not cleared.search_index_built
    assert cleared.search_index_size == 0
    assert cleared.posting_count == 0
    assert cleared.text_bytes == cold.text_bytes
    assert lazy.search("alpha")[0].text == "alpha 😀"
    assert lazy.performance_metrics.search_index_built

    disabled = _load(document, mode=SearchIndexMode.DISABLED)
    disabled.prewarm_search_index()
    assert not disabled.performance_metrics.search_index_built


def test_bounded_levenshtein_matches_reference_dp_for_short_unicode() -> None:
    def reference_distance(first: str, second: str) -> int:
        previous = list(range(len(second) + 1))
        for row, left in enumerate(first, start=1):
            current = [row]
            for column, right in enumerate(second, start=1):
                current.append(
                    min(
                        previous[column] + 1,
                        current[column - 1] + 1,
                        previous[column - 1] + (left != right),
                    )
                )
            previous = current
        return previous[-1]

    alphabet = ("a", "é", "U00010400")
    values = ("",) + tuple(alphabet) + tuple(
        "".join(characters) for characters in product(alphabet, repeat=2)
    )
    for first in values:
        for second in values:
            distance = reference_distance(first, second)
            for maximum in range(4):
                assert is_within_levenshtein_distance(
                    first,
                    second,
                    maximum,
                ) is (distance <= maximum)
