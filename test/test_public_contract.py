"""Public value, loading, navigation, and error contracts.

These tests complement the schema/search parity suites with the smaller API
surfaces that are easy to regress while porting behavior between languages.
"""

from __future__ import annotations

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

import pytest

from bible_io import (
    Bible,
    BibleBookEnum,
    BibleDataFormatError,
    BibleDataFormatErrorCode,
    BibleDataValidationOptions,
    BibleLanguageEnum,
    BibleLoadOptions,
    BibleLoadPhase,
    BibleLoadProgress,
    BibleLocation,
    BibleMetadata,
    BibleReferenceResult,
    BibleSource,
    BibleVerseKey,
    Book,
    BookNameStyle,
    BookNotFoundError,
    Chapter,
    ChapterNotFoundError,
    ChapterPassage,
    EditionVerseRange,
    Failure,
    ParseFailure,
    ParseSuccess,
    Result,
    ResultException,
    SearchIndexMode,
    SearchMode,
    SearchOptions,
    Success,
    TextDirectionHint,
    Verse,
    VerseNotFoundError,
    VersePassage,
    VerseRef,
    VerseSelection,
)


def _document() -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "language": "English",
        "metadata": {
            "id": "tiny",
            "translationName": "Tiny Edition",
            "abbreviation": "TNY",
            "languageName": "English",
            "languageCode": "en",
            "direction": "ltr",
        },
        "bookOrder": ["ex", "gn"],
        "books": {
            "gn": {
                "name": "Genesis Local",
                "chapters": {
                    "1": {
                        "1": "Alpha beta",
                        "3": {"text": "Caf\u00e9 ending", "note": "n"},
                    },
                    "3": {"2": "Last genesis"},
                },
            },
            "ex": {
                "name": "Exodus Local",
                "chapters": {"2": {"2": "First exodus", "5": "Alpha only"}},
            },
        },
    }


def _bible(*, mode: SearchIndexMode = SearchIndexMode.DISABLED) -> Bible:
    return Bible.from_decoded_json(
        _document(),
        options=BibleLoadOptions(search_index_mode=mode),
    )


def test_verse_chapter_and_book_value_helpers() -> None:
    first = Verse(
        BibleBookEnum.Genesis,
        1,
        1,
        "Alpha, beta beta!",
        annotations={"note": {"kind": "study"}},
    )
    third = Verse(BibleBookEnum.Genesis, 1, 3, "Gamma")
    chapter = Chapter(
        BibleBookEnum.Genesis,
        1,
        (third, first),
        annotations={"heading": "Start"},
    )
    empty = Chapter(BibleBookEnum.Genesis, 3, ())
    book = Book(
        BibleBookEnum.Genesis,
        (empty, chapter),
        "Genesis Local",
        annotations={"section": "Torah"},
    )

    assert (first.chapter, first.number, first.length) == (1, 1, 17)
    assert first.location == BibleLocation(BibleBookEnum.Genesis, 1, 1)
    assert first.to_verse_ref() == VerseRef(BibleBookEnum.Genesis, 1, 1)
    assert first.reference == "Genesis 1:1"
    assert first.short_reference.endswith("1:1")
    assert first.words == ("Alpha", "beta", "beta")
    assert first.contains_word("ALPHA")
    assert not first.contains_word("alp")
    assert first.contains_text("alpha, beta")
    assert first.contains_any(("missing", "beta"))
    assert first.contains_all(("alpha", "beta"))
    assert first.stats.word_count == 3
    assert first.stats.average_word_length == pytest.approx(13 / 3)
    assert len(first) == first.length
    assert "Verse(" in repr(first)
    assert first.to_json_value() == {
        "text": "Alpha, beta beta!",
        "note": {"kind": "study"},
    }
    assert third.to_json_value() == "Gamma"
    assert first.with_text("Changed").text == "Changed"
    assert first.with_annotations({"flag": True}).annotations["flag"] is True
    assert first.copy_with(verse_number=2).verse_number == 2

    assert chapter.verses == (first, third)
    assert chapter.number == 1
    assert chapter.get_verses() == chapter.verses
    assert chapter.search("beta") == (first,)
    assert chapter.contains_word("gamma")
    assert chapter.verses_containing("missing") == ()
    assert chapter.reference == "Genesis 1"
    assert chapter.stats.verse_count == 2
    assert chapter.with_annotations({"x": 1}).annotations["x"] == 1
    assert tuple(chapter) == chapter.verses
    assert first in chapter and len(chapter) == 2
    assert "verses=2" in repr(chapter)

    assert book.book == book.book_enum == BibleBookEnum.Genesis
    assert book.name == book.title == "Genesis Local"
    assert book.abbrev == book.abbreviation
    assert book.chapters == (chapter, empty)
    assert book.get_chapters() == book.chapters
    assert book.get_verse(1, 3) is third
    assert book.all_verses == (first, third)
    assert book.verse_count == 2
    assert book.search("beta") == (first,)
    assert book.chapters_containing("gamma") == (chapter,)
    assert book.reference == "Genesis"
    assert book.stats.chapter_count == 2
    assert book.stats.average_verses_per_chapter == 1.0
    assert book.with_name("Renamed").name == "Renamed"
    assert book.with_title("Retitled").title == "Retitled"
    assert book.with_annotations({"x": 1}).annotations["x"] == 1
    assert tuple(book) == book.chapters
    assert chapter in book and len(book) == 2
    assert "Genesis Local" in repr(book)
    book_json = book.to_json_value()
    assert isinstance(book_json, dict)
    assert book_json["section"] == "Torah"


def test_empty_model_statistics_and_value_equality() -> None:
    blank = Verse(BibleBookEnum.Genesis, 1, 1, "")
    chapter = Chapter(BibleBookEnum.Genesis, 1, ())
    book = Book(BibleBookEnum.Genesis, ())

    assert blank.stats.average_word_length == 0.0
    assert chapter.stats.average_verse_length == 0
    assert book.stats.average_verses_per_chapter == 0.0
    assert blank == blank.copy_with()
    assert chapter == chapter.copy_with()
    assert book == book.copy_with()
    assert hash(blank) == hash(blank.copy_with())
    assert hash(chapter) == hash(chapter.copy_with())
    assert hash(book) == hash(book.copy_with())
    assert blank != object()
    assert chapter != object()
    assert book != object()


def test_model_construction_rejects_invalid_and_inconsistent_values() -> None:
    valid = Verse(BibleBookEnum.Genesis, 1, 1, "text")

    with pytest.raises(TypeError):
        Verse("gn", 1, 1, "text")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Verse(BibleBookEnum.Genesis, True, 1, "text")
    with pytest.raises(ValueError):
        Verse(BibleBookEnum.Genesis, 1, 0, "text")
    with pytest.raises(TypeError):
        Verse(BibleBookEnum.Genesis, 1, 1, 3)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        valid.contains_word(1)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        valid.contains_text(1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="structural key"):
        valid.with_annotations({"text": "shadow"})

    with pytest.raises(TypeError):
        Chapter(BibleBookEnum.Genesis, 1, None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Chapter(BibleBookEnum.Genesis, 1, (object(),))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="another book"):
        Chapter(
            BibleBookEnum.Exodus,
            1,
            (valid,),
        )
    with pytest.raises(ValueError, match="another chapter"):
        Chapter(BibleBookEnum.Genesis, 2, (valid,))
    with pytest.raises(ValueError, match="duplicate verse"):
        Chapter(BibleBookEnum.Genesis, 1, (valid, valid.copy_with()))
    with pytest.raises(VerseNotFoundError):
        Chapter(BibleBookEnum.Genesis, 1, (valid,)).get_verse(True)

    valid_chapter = Chapter(BibleBookEnum.Genesis, 1, (valid,))
    with pytest.raises(TypeError):
        Book(BibleBookEnum.Genesis, None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Book(BibleBookEnum.Genesis, (object(),))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="another book"):
        Book(BibleBookEnum.Exodus, (valid_chapter,))
    with pytest.raises(ValueError, match="duplicate chapter"):
        Book(BibleBookEnum.Genesis, (valid_chapter, valid_chapter.copy_with()))
    with pytest.raises(TypeError):
        Book(BibleBookEnum.Genesis, (), 1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="blank"):
        Book(BibleBookEnum.Genesis, (), "  ")
    with pytest.raises(ChapterNotFoundError):
        Book(BibleBookEnum.Genesis, (valid_chapter,)).get_chapter(False)


def test_loading_options_progress_and_enums_are_validated() -> None:
    strict = BibleDataValidationOptions.STRICT
    permissive = BibleDataValidationOptions.PERMISSIVE
    assert strict == getattr(BibleDataValidationOptions, "strict")
    assert permissive == getattr(BibleDataValidationOptions, "permissive")
    assert strict.copy_with(require_books=False).require_books is False
    assert permissive.copy_with(require_verse_text=True).require_verse_text is True
    assert str(SearchIndexMode.LAZY) == "lazy"
    assert SearchIndexMode.lazy is SearchIndexMode.LAZY
    assert str(BibleLoadPhase.PROCESSING) == "processing"

    for field in (
        "require_books",
        "require_chapters",
        "require_verses",
        "require_verse_text",
    ):
        with pytest.raises(TypeError, match=field):
            BibleDataValidationOptions(**{field: 1})  # type: ignore[arg-type]

    options = BibleLoadOptions(
        search_index_mode="lazy",  # type: ignore[arg-type]
        parse_in_background=False,
    )
    assert options.search_index_mode is SearchIndexMode.LAZY
    assert options.copy_with(parse_in_background=True).parse_in_background
    with pytest.raises(TypeError, match="validation"):
        BibleLoadOptions(validation=object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="search_index_mode"):
        BibleLoadOptions(search_index_mode="unknown")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="parse_in_background"):
        BibleLoadOptions(parse_in_background=1)  # type: ignore[arg-type]

    progress = BibleLoadProgress("reading", 0, 1)  # type: ignore[arg-type]
    assert progress == BibleLoadProgress(BibleLoadPhase.READING, 0.0, 1.0)
    with pytest.raises(TypeError, match="phase"):
        BibleLoadProgress("unknown", 0, 0)  # type: ignore[arg-type]
    for bad in (True, "0", None):
        with pytest.raises(TypeError):
            BibleLoadProgress(BibleLoadPhase.READING, bad, 0)  # type: ignore[arg-type]
    for bad_number in (-0.1, 1.1, float("inf"), float("nan")):
        with pytest.raises(ValueError):
            BibleLoadProgress(BibleLoadPhase.READING, bad_number, 0)


def test_locations_and_edition_keys_cover_all_conversion_paths() -> None:
    verse = Verse(BibleBookEnum.Genesis, 2, 3, "text")
    reference = VerseRef(BibleBookEnum.Genesis, 2, 3)
    location = BibleLocation.checked(book=BibleBookEnum.Genesis, chapter=2, verse=3)

    assert BibleLocation.from_verse(verse) == location
    assert BibleLocation.from_verse_ref(reference) == location
    assert BibleLocation.from_json({"book": "GEN", "chapter": 2, "verse": 3}) == location
    assert location.chapter_number == 2 and location.verse_number == 3
    assert location.has_verse
    assert location.copy_with(chapter=4) == BibleLocation(BibleBookEnum.Genesis, 4, 3)
    assert location.to_verse_ref() == reference
    passage = location.to_passage()
    assert isinstance(passage, VersePassage)
    assert location.to_dict() == location.to_json()
    assert location.reference == str(location) == "Genesis 2:3"

    chapter_location = location.copy_with(verse=None)
    assert isinstance(chapter_location.to_passage(), ChapterPassage)
    assert not chapter_location.has_verse
    with pytest.raises(ValueError, match="chapter-only"):
        chapter_location.to_verse_ref()

    key = BibleVerseKey.checked(edition_id="edition", location=location)
    assert BibleVerseKey.from_verse("edition", verse) == key
    assert BibleVerseKey.from_dict(
        {"edition_id": "edition", "location": location.to_dict()}
    ) == key
    assert key.to_verse_ref() == reference
    assert key.copy_with(edition_id="other").edition_id == "other"
    assert key.with_edition_id("other").edition_id == "other"
    assert key.with_location(BibleLocation(BibleBookEnum.Genesis, 2, 4)).location.verse == 4
    assert key.to_dict() == key.to_json()
    assert str(key) == "edition:Genesis 2:3"


def test_locations_and_keys_reject_malformed_state() -> None:
    with pytest.raises(TypeError):
        BibleLocation("Genesis", 1)  # type: ignore[arg-type]
    for value in (0, -1, True, "1"):
        with pytest.raises(ValueError):
            BibleLocation.from_json({"book": "Genesis", "chapter": value})
    with pytest.raises(TypeError):
        BibleLocation.from_json([])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="keys"):
        BibleLocation.from_json({1: "Genesis"})  # type: ignore[dict-item]
    with pytest.raises(ValueError, match="unknown"):
        BibleLocation.from_json({"book": "unknown", "chapter": 1})
    with pytest.raises(TypeError):
        BibleLocation.from_verse_ref(object())  # type: ignore[arg-type]

    chapter = BibleLocation(BibleBookEnum.Genesis, 1)
    verse = BibleLocation(BibleBookEnum.Genesis, 1, 1)
    with pytest.raises(ValueError, match="edition_id"):
        BibleVerseKey(" ", verse)
    with pytest.raises(ValueError, match="identify a verse"):
        BibleVerseKey("edition", chapter)
    with pytest.raises(TypeError, match="location"):
        BibleVerseKey("edition", object())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        BibleVerseKey.from_json([])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="keys"):
        BibleVerseKey.from_json({1: "x"})  # type: ignore[dict-item]
    with pytest.raises(ValueError, match="editionId"):
        BibleVerseKey.from_json({"editionId": 1, "location": verse.to_json()})
    with pytest.raises(ValueError, match="location"):
        BibleVerseKey.from_json({"editionId": "x", "location": None})


def test_result_success_failure_mapping_and_exception_retention() -> None:
    success = Result.success(3)
    assert isinstance(success, Success)
    assert success.value == 3
    assert success.error is None and success.cause is None
    assert success.traceback is None and success.stack_trace is None
    assert success.map(lambda value: value + 1) == Success(4)
    assert success.flat_map(lambda value: Success(str(value))) == Success("3")
    assert success.get_or_else(9) == 3
    assert success.fold(lambda error: error, lambda value: value * 2) == 6
    assert repr(success) == "Success(3)"
    assert hash(success) == hash(Success(3))
    with pytest.raises(TypeError, match="must return Result"):
        success.flat_map(lambda value: value + 1)

    failure: Result[int] = Result.failure("bad")
    assert isinstance(failure, Failure)
    assert failure.error == "bad"
    assert failure.map(str).error == "bad"
    assert failure.flat_map(lambda value: Success(value)).error == "bad"
    assert failure.get_or_else(9) == 9
    assert failure.fold(str.upper, str) == "BAD"
    assert repr(failure) == "Failure('bad')"
    with pytest.raises(ResultException, match="ResultException: bad"):
        _ = failure.value
    with pytest.raises(TypeError, match="string"):
        Failure(1)  # type: ignore[arg-type]

    original: ValueError | None = None
    retained: Result[object]
    try:
        raise ValueError("original")
    except ValueError as caught:
        original = caught
        retained = Result.failure_from(caught)
    assert original is not None
    assert isinstance(retained, Failure)
    assert retained.cause is original
    assert retained.traceback is not None
    assert retained.stack_trace is retained.traceback
    from_object = getattr(Failure, "from_object")
    assert from_object(original) == Failure[object].from_exception(
        original,
        retained.traceback,
    )
    assert hash(retained) == hash(
        Failure[object].from_exception(original, retained.traceback)
    )
    with pytest.raises(ResultException) as raised:
        _ = retained.value
    assert raised.value.cause is original
    assert raised.value.stack_trace is retained.traceback
    assert raised.value.__cause__ is original


def test_bible_lookup_indexing_copy_metadata_and_metrics() -> None:
    bible = _bible()
    exodus = BibleBookEnum.Exodus
    genesis = BibleBookEnum.Genesis

    assert bible[exodus] is bible.get_book(exodus)
    assert bible[(exodus, 2)] is bible.get_chapter(exodus, 2)
    assert bible[(exodus, 2, 2)] is bible.get_verse(exodus, 2, 2)
    assert bible.get_book_by_abbreviation("Ex") is bible.get_book(exodus)
    assert bible.get_book_by_abbrev("gn") is bible.get_book(genesis)
    assert bible.get_book_by_id(1).book is exodus
    assert tuple(bible.books_with_index)[0] == (0, bible.get_book(exodus))
    assert tuple(bible.get_verses(exodus, 2)) == bible.get_book(exodus).all_verses
    assert (bible.book_count, bible.chapter_count, bible.verse_count) == (2, 3, 5)
    assert bible.schema_version == 1
    assert bible.name == bible.translation_name == "Tiny Edition"
    assert bible.id == "tiny" and bible.abbreviation == "TNY"
    assert bible.language is BibleLanguageEnum.ENGLISH
    assert bible.language_name == "English" and bible.language_code == "en"
    assert bible.text_direction is TextDirectionHint.LTR
    assert bible.source is None
    assert bible.created_at.tzinfo is timezone.utc
    assert bible.reference_parser is not None and bible.passage_parser is not None

    copied = bible.copy_with(annotations={"copy": True})
    assert copied.annotations["copy"] is True
    assert copied != bible and hash(copied) != hash(bible)
    assert bible.copy_with() == bible
    assert bible.to_json(indent=2).startswith("{\n")

    metrics = bible.performance_metrics
    assert not metrics.search_index_built
    assert metrics.search_index_size == metrics.posting_count == 0
    assert metrics.memory_usage == metrics.memory_usage_kib > 0
    assert metrics.verse_count == 5 and metrics.text_bytes >= metrics.text_characters
    assert bible.stats.verses_per_book[exodus] == 2

    for bad in (0, 3, True, "1"):
        with pytest.raises(BookNotFoundError):
            bible.get_book_by_id(bad)  # type: ignore[arg-type]
    with pytest.raises(BookNotFoundError):
        bible.get_book_by_abbreviation("unknown")
    with pytest.raises(TypeError):
        _ = bible["gn"]  # type: ignore[index]


def test_bible_navigation_boundaries_and_invalid_locations() -> None:
    bible = _bible()
    exodus_first = BibleLocation(BibleBookEnum.Exodus, 2, 2)
    exodus_last = BibleLocation(BibleBookEnum.Exodus, 2, 5)
    genesis_first = BibleLocation(BibleBookEnum.Genesis, 1, 1)
    genesis_last = BibleLocation(BibleBookEnum.Genesis, 3, 2)

    assert bible.previous_verse(exodus_first) is None
    assert not bible.has_previous_verse(exodus_first)
    assert bible.next_verse(exodus_last) == genesis_first
    assert bible.has_next_verse(exodus_last)
    assert bible.next_verse(genesis_last) is None
    assert not bible.has_next_verse(genesis_last)
    assert bible.previous_verse(genesis_first) == exodus_last
    assert bible.previous_chapter(BibleLocation(BibleBookEnum.Exodus, 2)) is None
    assert not bible.has_previous_chapter(BibleLocation(BibleBookEnum.Exodus, 2))
    assert bible.next_chapter(BibleLocation(BibleBookEnum.Genesis, 1)) == BibleLocation(
        BibleBookEnum.Genesis, 3
    )
    assert bible.has_next_chapter(BibleLocation(BibleBookEnum.Genesis, 1))
    assert not bible.has_next_chapter(BibleLocation(BibleBookEnum.Genesis, 3))

    assert bible.get_chapter_at(BibleLocation(BibleBookEnum.Genesis, 1)).number == 1
    assert bible.get_verse_at(genesis_first).text == "Alpha beta"
    assert bible.contains_reference(genesis_first)
    assert not bible.contains_reference(BibleLocation(BibleBookEnum.Genesis, 1, 2))
    with pytest.raises(ValueError, match="verse is required"):
        bible.get_verse_at(BibleLocation(BibleBookEnum.Genesis, 1))
    with pytest.raises(ChapterNotFoundError):
        bible.next_chapter(BibleLocation(BibleBookEnum.Genesis, 2))
    with pytest.raises(BookNotFoundError):
        bible.next_chapter(BibleLocation(BibleBookEnum.John, 1))


def test_reference_passage_and_result_conveniences() -> None:
    bible = _bible()
    verse_ref = VerseRef(BibleBookEnum.Genesis, 1, 1)

    assert bible.parse_reference("Genesis Local 1:1") == verse_ref
    assert bible.parse_canonical_reference("Genesis 1:1") == verse_ref
    assert bible.try_parse_reference("not a reference") is None
    detailed = bible.parse_reference_detailed("Genesis Local 1:1")
    assert detailed.value == verse_ref and detailed.metadata is not None
    assert isinstance(bible.parse_reference_result("Genesis Local 1:1"), ParseSuccess)
    assert isinstance(bible.parse_reference_result("not a reference"), ParseFailure)
    assert bible.try_parse_passage("not a passage") is None
    assert bible.parse_passage_detailed("Genesis Local 1").metadata is not None
    assert isinstance(bible.parse_passage_result("Genesis Local 1"), ParseSuccess)
    assert isinstance(bible.parse_passage_result("not a passage"), ParseFailure)

    assert bible.resolve_reference(verse_ref).first == bible.get_verse_by_ref(verse_ref)
    assert bible.get_verse_by_ref("Genesis Local 1:1").text == "Alpha beta"
    assert bible.get_by_ref(verse_ref).text == "Alpha beta"
    assert bible.verse_or_none("missing") is None
    assert bible.verse_or_null("missing") is None
    assert bible.verses_or_none("Genesis Local 1:1-3") is not None
    assert bible.verses_or_null("missing") is None
    assert bible.get_passage(verse_ref).first is bible.get_verse_by_ref(verse_ref)
    assert bible.get_passage_selection("Genesis Local 1").first is not None

    assert isinstance(bible.get_book_result(BibleBookEnum.Genesis), Success)
    assert isinstance(bible.get_book_result(BibleBookEnum.John), Failure)
    assert isinstance(bible.get_book_by_id_result(1), Success)
    assert isinstance(bible.get_book_by_id_result(0), Failure)
    assert isinstance(bible.get_verse_by_ref_result("Genesis Local 1:1"), Success)
    assert isinstance(bible.get_verse_by_ref_result("missing"), Failure)
    assert isinstance(
        bible.get_verse_range_by_ref_result("Genesis Local 1:1-3"), Success
    )
    assert isinstance(bible.get_verse_range_by_ref_result("missing"), Failure)
    assert isinstance(bible.get_passage_result("Genesis Local 1"), Success)
    assert isinstance(bible.get_passage_result("missing"), Failure)

    selection = VerseSelection((bible.get_verse_by_ref(verse_ref),))
    assert selection.verses == tuple(selection)
    assert selection.first is selection.last
    assert selection[0] is selection.first and selection[:] == selection.verses
    assert tuple(reversed(selection)) == selection.verses
    assert selection == selection.verses
    assert hash(selection) == hash(VerseSelection(selection))
    assert "VerseSelection" in repr(selection)
    assert VerseSelection().first is None and VerseSelection().last is None

    single = BibleReferenceResult.from_verse(selection.first)
    multiple = BibleReferenceResult.from_selection(selection)
    assert single.is_verse and not single.is_range and single.as_verse() is selection.first
    assert multiple.is_range and multiple.as_range() == selection
    with pytest.raises(ValueError, match="exactly one"):
        BibleReferenceResult()
    with pytest.raises(ValueError, match="exactly one"):
        BibleReferenceResult(verse=selection.first, selection=selection)


def test_reference_and_passage_type_and_order_errors() -> None:
    bible = _bible()
    first = VerseRef(BibleBookEnum.Exodus, 2, 2)
    last = VerseRef(BibleBookEnum.Genesis, 3, 2)

    with pytest.raises(TypeError):
        EditionVerseRange(first, object())  # type: ignore[arg-type]
    assert bible.resolve_edition_range(EditionVerseRange(first, first)).first is not None
    with pytest.raises(TypeError):
        bible.resolve_reference(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        bible.resolve_passage(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        bible.get_passage(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        bible.get_verse_by_ref(1)  # type: ignore[call-overload]
    with pytest.raises(TypeError):
        bible.get_verse_by_ref("Genesis Local 1:1-3")
    with pytest.raises(TypeError):
        bible.get_verse_range_by_ref("Genesis Local 1:1")
    with pytest.raises(TypeError):
        bible.get_by_ref(object())  # type: ignore[call-overload]
    with pytest.raises(ValueError, match="before"):
        bible.resolve_edition_range(EditionVerseRange(last, first))


def test_location_formatting_and_persisted_key_guards() -> None:
    bible = _bible()
    location = BibleLocation(BibleBookEnum.Genesis, 1, 1)
    verse = bible.get_verse_at(location)

    assert bible.format_location(location) == "Genesis Local 1:1"
    assert bible.format_location(
        location,
        book_name_style=BookNameStyle.SHORT,
        prefer_edition_book_name=False,
    ).endswith(" 1:1")
    assert bible.key_for_verse(verse) == bible.key_for_location(location)
    with pytest.raises(ValueError, match="loaded by this edition"):
        bible.key_for_verse(verse.with_text("different"))

    no_id = Bible.from_books(
        bible.books,
        metadata=BibleMetadata(language_name="English", language_code="en"),
        search_index_mode=SearchIndexMode.DISABLED,
    )
    with pytest.raises(ValueError, match="define an id"):
        no_id.key_for_verse(verse)


def test_search_index_lifecycle_scopes_and_pagination() -> None:
    bible = _bible(mode=SearchIndexMode.LAZY)
    assert not bible.has_search_index
    bible.prewarm_search_index()
    assert bible.has_search_index
    built = bible.performance_metrics
    assert built.search_index_built and built.search_index_size > 0
    assert built.posting_count > 0
    bible.invalidate_search_index()
    assert not bible.has_search_index
    asyncio.run(bible.prewarm_search_index_async())
    assert bible.has_search_index
    asyncio.run(bible.prewarm_search_index_async())
    bible.clear_search_index()

    exact = bible.search_advanced("Alpha", mode=SearchMode.EXACT, max_results=1)
    assert exact.count == 1 and exact.has_more and exact.next_offset == 1
    second = bible.search_advanced(
        "Alpha",
        mode=SearchMode.EXACT,
        max_results=1,
        offset=1,
    )
    assert second.count == 1 and not second.has_more and second.total_count == 2
    scoped = bible.search_advanced(
        None,
        book=BibleBookEnum.Genesis,
        chapter=1,
        verse=3,
    )
    assert tuple(item.text for item in scoped.verses) == ("Caf\u00e9 ending",)
    assert bible.search_advanced("CAF\u00c9", ignore_diacritics=False).count == 1
    assert bible.search_advanced("cafe", ignore_diacritics=True).count == 1
    assert bible.search_advanced("alpha", case_sensitive=True).count == 0
    assert bible.books_containing("alpha") == bible.books

    fuzzy = bible.fuzzy_search(
        "Alphx",
        SearchOptions(mode=SearchMode.EXACT, max_results=1),
        max_distance=1,
    )
    assert fuzzy.count == 1 and fuzzy.has_more
    assert bible.fuzzy_search("   ").total_count == 0
    with pytest.raises(TypeError, match="max_distance"):
        bible.fuzzy_search("alpha", max_distance=True)
    with pytest.raises(ValueError, match="non-negative"):
        bible.fuzzy_search("alpha", max_distance=-1)
    with pytest.raises(TypeError, match="options"):
        bible.fuzzy_search("alpha", object())

    disabled = _bible(mode=SearchIndexMode.DISABLED)
    asyncio.run(disabled.prewarm_search_index_async())
    disabled.prewarm_search_index()
    assert not disabled.has_search_index


def test_sync_async_json_byte_and_path_loading(tmp_path: Path) -> None:
    encoded = json.dumps(_document())
    path = tmp_path / "edition.data"
    path.write_text(encoded, encoding="utf-8")
    foreground = BibleLoadOptions(
        search_index_mode=SearchIndexMode.DISABLED,
        parse_in_background=False,
    )
    background = foreground.copy_with(parse_in_background=True)

    assert Bible.from_utf8_bytes(b"\xef\xbb\xbf" + encoded.encode()).id == "tiny"
    assert Bible.from_bytes(encoded.encode()).id == "tiny"
    assert asyncio.run(Bible.from_json_async(encoded, options=foreground)).id == "tiny"
    assert asyncio.run(Bible.from_json_async(encoded, options=background)).id == "tiny"
    assert asyncio.run(Bible.load_async(path, options=foreground)).id == "tiny"
    assert asyncio.run(Bible.load_async(path, options=background)).id == "tiny"

    with pytest.raises(TypeError, match="json_string"):
        Bible.from_json(1)  # type: ignore[arg-type]
    with pytest.raises(BibleDataFormatError) as invalid_json:
        Bible.from_json("{")
    assert invalid_json.value.code is BibleDataFormatErrorCode.INVALID_JSON
    with pytest.raises(BibleDataFormatError) as invalid_utf8:
        Bible.from_utf8_bytes(b"\xff")
    assert invalid_utf8.value.code is BibleDataFormatErrorCode.INVALID_JSON
    with pytest.raises(BibleDataFormatError):
        Bible.from_utf8_bytes(b"{")


def test_foreground_async_loading_keeps_file_io_off_the_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "edition.json"
    path.write_text(json.dumps(_document()), encoding="utf-8")
    started = threading.Event()
    release = threading.Event()
    original = Bible._read_path_bytes

    def blocked_read(
        cls: type[Bible],
        input_path: str | Path,
        *,
        on_load_progress: object,
        on_progress: object,
    ) -> bytes:
        del cls
        started.set()
        release.wait(timeout=2)
        return original(
            input_path,
            on_load_progress=on_load_progress,  # type: ignore[arg-type]
            on_progress=on_progress,  # type: ignore[arg-type]
        )

    monkeypatch.setattr(Bible, "_read_path_bytes", classmethod(blocked_read))

    async def exercise() -> Bible:
        task = asyncio.create_task(
            Bible.load_async(
                path,
                options=BibleLoadOptions(
                    search_index_mode=SearchIndexMode.DISABLED,
                    parse_in_background=False,
                ),
            )
        )
        assert await asyncio.to_thread(started.wait, 1)
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        return await task

    assert asyncio.run(exercise()).id == "tiny"


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {"schemaVersion": True, "books": {}},
        {"schemaVersion": 2, "books": {}},
        {"schemaVersion": 1},
        {"schemaVersion": 1, "books": []},
        {"schemaVersion": 1, "books": {}},
        {"schemaVersion": 1, "books": {"unknown": {}}},
        {"schemaVersion": 1, "books": {"gn": []}},
        {
            "schemaVersion": 1,
            "books": {"gn": {"name": "Genesis", "chapters": {}}},
        },
        {
            "schemaVersion": 1,
            "books": {
                "gn": {
                    "name": "Genesis",
                    "chapters": {"1": {}},
                }
            },
        },
        {
            "schemaVersion": 1,
            "books": {
                "gn": {
                    "name": "Genesis",
                    "chapters": {"1": {"1": "  "}},
                }
            },
        },
    ],
)
def test_strict_schema_rejects_incomplete_or_invalid_documents(value: object) -> None:
    with pytest.raises(BibleDataFormatError):
        Bible.from_decoded_json(value)


def test_permissive_loading_and_direct_construction_validation() -> None:
    permissive = BibleLoadOptions(
        validation=BibleDataValidationOptions.PERMISSIVE,
        search_index_mode=SearchIndexMode.DISABLED,
    )
    empty = Bible.from_decoded_json({"schemaVersion": 1}, options=permissive)
    assert empty.books == () and empty.stats.average_verse_length == 0
    assert empty.performance_metrics.verse_count == 0

    blank_verse = Verse(BibleBookEnum.Genesis, 1, 1, "")
    empty_chapter = Chapter(BibleBookEnum.Exodus, 1, ())
    blank_book = Book(
        BibleBookEnum.Genesis,
        (Chapter(BibleBookEnum.Genesis, 1, (blank_verse,)),),
    )
    chapterless_book = Book(BibleBookEnum.John, ())
    verseless_book = Book(BibleBookEnum.Exodus, (empty_chapter,))

    with pytest.raises(ValueError, match="at least one"):
        Bible.from_books(())
    with pytest.raises(ValueError, match="must contain a chapter"):
        Bible.from_books((chapterless_book,))
    with pytest.raises(ValueError, match="must contain a verse"):
        Bible.from_books((verseless_book,))
    with pytest.raises(ValueError, match="blank verse"):
        Bible.from_books((blank_book,))
    with pytest.raises(TypeError, match="Book objects"):
        Bible.from_books((object(),))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="language"):
        Bible.from_books((blank_book,), language="English")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="validation"):
        Bible.from_books((blank_book,), validation=object())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="schema version"):
        Bible.from_books((blank_book,), schema_version=2)

    restored = Bible.from_books(
        (chapterless_book, verseless_book, blank_book),
        validation=BibleDataValidationOptions.PERMISSIVE,
        search_index_mode=SearchIndexMode.DISABLED,
    )
    assert restored.verse_count == 1


def test_source_backed_metadata_convenience_properties() -> None:
    date = datetime(2026, 8, 14, tzinfo=timezone.utc)
    source = BibleSource.checked(
        id="source",
        asset_path="source.json",
        language_name="English",
        language_code="en",
        translation_name="Source Edition",
        abbreviation="SRC",
        description="description",
        year=2026,
        direction=TextDirectionHint.LTR,
        source_name="provider",
        copyright="copyright",
        license="license",
        canon="canon",
        version_date=date,
    )
    bible = Bible.from_books(
        _bible().books,
        source=source,
        search_index_mode=SearchIndexMode.DISABLED,
    )

    assert bible.source is source
    assert bible.description == "description"
    assert bible.year == 2026
    assert bible.source_name == "provider"
    assert bible.copyright == "copyright"
    assert bible.license == "license"
    assert bible.canon == "canon"
    assert bible.version_date == date


@pytest.mark.parametrize(
    ("language", "code"),
    (
        ("Hindi", "hi"),
        ("hin", "hi"),
        ("Indonesian", "id"),
        ("id", "id"),
        ("Korean", "ko"),
        ("Tagalog", "tl"),
        ("fil", "tl"),
        ("Vietnamese", "vi"),
        ("Italian", "it"),
    ),
)
def test_source_language_alias_inference_matrix(language: str, code: str) -> None:
    source = BibleSource.from_asset_path(f"bibles/{language}/edition.json")
    assert source.language_code == code


def test_multilingual_reference_parser_reports_selected_language() -> None:
    document = {
        "language": "Spanish",
        "books": {
            "jo": {
                "name": "Juan",
                "chapters": {"1": {"1": "texto"}},
            }
        },
    }
    bible = Bible.from_decoded_json(
        document,
        options=BibleLoadOptions(search_index_mode=SearchIndexMode.DISABLED),
    )

    automatic = bible.parse_reference_detailed("Juan 1:1")
    explicit = bible.parse_reference_detailed(
        "John 1:1",
        input_language=BibleLanguageEnum.ENGLISH,
    )
    assert automatic.value == explicit.value
    assert automatic.metadata is not None and explicit.metadata is not None
    assert automatic.metadata.book_matches[0].selected.language is BibleLanguageEnum.SPANISH
    assert explicit.metadata.book_matches[0].selected.language is BibleLanguageEnum.ENGLISH


def test_full_fixture_has_sequential_canonical_coordinates(bible: Bible) -> None:
    assert bible.book_count == 66
    assert bible.chapter_count == 1_189
    assert bible.verse_count == 31_100
    assert bible.get_book_by_id(1).book is BibleBookEnum.Genesis
    assert bible.get_book_by_id(66).book is BibleBookEnum.Revelation
    assert bible.get_chapter(BibleBookEnum.Genesis, 1).number == 1
    assert bible.get_chapter(BibleBookEnum.Revelation, 22).number == 22
    assert bible.get_verse(BibleBookEnum.Genesis, 1, 1).number == 1
    assert bible.get_verse(BibleBookEnum.Revelation, 22, 21).number == 21
    for book_index, book in bible.books_with_index:
        assert bible.get_book_by_id(book_index + 1) is book
        assert tuple(chapter.number for chapter in book.chapters) == tuple(
            range(1, len(book.chapters) + 1)
        )
        for chapter in book.chapters:
            assert tuple(verse.number for verse in chapter.verses) == tuple(
                range(1, len(chapter.verses) + 1)
            )
            assert all(
                verse.book is book.book_enum
                and verse.chapter_number == chapter.chapter_number
                for verse in chapter.verses
            )

    search_started = perf_counter()
    common = bible.search("the")
    search_elapsed = perf_counter() - search_started
    assert len(common) > 1_000
    assert search_elapsed < 5.0
    metrics = bible.performance_metrics
    assert metrics.load_time.total_seconds() > 0
    assert metrics.search_index_built and metrics.search_index_size > 0
    assert metrics.posting_count > metrics.verse_count
    assert metrics.text_bytes > 0 and metrics.memory_usage_kib > 0


def test_concurrent_reads_and_lazy_searches_are_deterministic() -> None:
    bible = _bible(mode=SearchIndexMode.LAZY)
    queries = ("Alpha", "Caf\u00e9", "ending", "missing") * 8
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = tuple(executor.map(bible.search, queries))

    expected_counts = (2, 1, 1, 0) * 8
    assert tuple(len(result) for result in results) == expected_counts
    assert bible.has_search_index
