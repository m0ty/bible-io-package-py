"""Focused schema-v1 and public-API parity tests.

The fixtures are intentionally tiny while still exercising custom edition
ordering, sparse chapter/verse coordinates, and lossless JSON extensions.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import pytest

from bible_io import (
    Bible,
    BibleBookEnum,
    BibleCatalog,
    BibleDataFormatError,
    BibleDataFormatErrorCode,
    BibleLoadOptions,
    BibleLoadPhase,
    BibleLoadProgress,
    BibleLocation,
    BibleSource,
    BibleMetadata,
    BibleVerseKey,
    Book,
    Chapter,
    ChapterNotFoundError,
    EditionVerseRange,
    Failure,
    SearchIndexMode,
    SearchMode,
    SearchOptions,
    Success,
    TextDirectionHint,
    Verse,
    VerseNotFoundError,
)


def _schema_v1_document() -> dict[str, Any]:
    """Return a fresh, compact schema-v1 document for every caller."""

    return {
        "schemaVersion": 1,
        "language": "English",
        "provider": {
            "slug": "example",
            "links": ["https://example.test"],
            "config": {"active": True},
        },
        "metadata": {
            "id": "example-2026",
            "description": "Schema fixture",
            "translationName": "Example Translation",
            "abbreviation": "EX",
            "languageName": "English",
            "languageCode": "en",
            "year": 2026,
            "direction": "ltr",
            "versionDate": "2026-08-14",
            "customMetadata": {"revision": 2, "tags": ["tiny", "test"]},
        },
        # Exodus before Genesis deliberately reverses canonical book order.
        "bookOrder": ["ex", "gn", "jo"],
        "books": {
            "gn": {
                "name": "Genesis Local",
                "section": "Torah",
                "chapters": {
                    "1": {
                        "heading": "Creation",
                        "verses": {
                            "1": {
                                "text": "Genesis one one",
                                "paragraphStart": True,
                                "notes": [{"kind": "study", "value": 1}],
                            },
                            "3": "Genesis one three",
                        },
                    },
                    "3": {"2": "Genesis three two"},
                },
            },
            "ex": {
                "name": "Exodus Local",
                "bookNote": {"source": "fixture"},
                "chapters": {
                    "2": {
                        "2": "Exodus two two",
                        "5": "Exodus two five",
                    }
                },
            },
            "jo": {
                "name": "John Local",
                "chapters": {"1": {"1": "John one one"}},
            },
        },
    }


def _load(
    document: object | None = None,
    *,
    mode: SearchIndexMode = SearchIndexMode.DISABLED,
) -> Bible:
    return Bible.from_decoded_json(
        _schema_v1_document() if document is None else document,
        options=BibleLoadOptions(search_index_mode=mode),
    )


def _coordinates(verses: Iterable[Verse]) -> list[tuple[BibleBookEnum, int, int]]:
    return [
        (verse.book, verse.chapter_number, verse.verse_number)
        for verse in verses
    ]


def _texts(verses: Iterable[Verse]) -> list[str]:
    return [verse.text for verse in verses]


def test_schema_v1_roundtrip_preserves_deep_extensions_and_annotations() -> None:
    document = _schema_v1_document()
    bible = _load(document)

    # Loaded values own a frozen deep copy, independent of the caller's input.
    document["provider"]["slug"] = "mutated"
    document["books"]["gn"]["section"] = "mutated"
    provider = bible.annotations["provider"]
    assert isinstance(provider, Mapping)
    assert provider["slug"] == "example"

    genesis = bible.get_book(BibleBookEnum.Genesis)
    chapter = genesis.get_chapter(1)
    verse = chapter.get_verse(1)
    assert genesis.annotations["section"] == "Torah"
    assert chapter.annotations["heading"] == "Creation"
    assert verse.annotations["paragraphStart"] is True
    notes = verse.annotations["notes"]
    assert isinstance(notes, tuple)
    assert isinstance(notes[0], Mapping)
    assert notes[0]["kind"] == "study"

    assert bible.id == "example-2026"
    assert bible.translation_name == "Example Translation"
    custom_metadata = bible.metadata.additional["customMetadata"]
    assert isinstance(custom_metadata, Mapping)
    assert custom_metadata["revision"] == 2

    encoded = bible.to_dict()
    assert encoded["provider"] == {
        "slug": "example",
        "links": ["https://example.test"],
        "config": {"active": True},
    }
    assert encoded["bookOrder"] == ["ex", "gn", "jo"]
    assert encoded["metadata"]["customMetadata"] == {
        "revision": 2,
        "tags": ["tiny", "test"],
    }
    assert encoded["books"]["gn"]["chapters"]["1"]["verses"]["1"] == {
        "text": "Genesis one one",
        "paragraphStart": True,
        "notes": [{"kind": "study", "value": 1}],
    }

    restored = Bible.from_json(json.dumps(encoded))
    assert restored == bible
    assert restored.to_dict() == encoded


def test_root_extensions_do_not_leak_into_metadata_extensions() -> None:
    bible = _load()

    # Rust/Dart keep root annotations on Bible and nested extensions on metadata.
    assert set(bible.annotations) == {"provider"}
    assert set(bible.metadata.additional) == {"customMetadata"}


def test_sparse_navigation_and_custom_order_cross_book_ranges() -> None:
    bible = _load()
    exodus = BibleBookEnum.Exodus
    genesis = BibleBookEnum.Genesis
    john = BibleBookEnum.John

    assert [book.book_enum for book in bible.books] == [exodus, genesis, john]
    assert bible.next_chapter(BibleLocation(exodus, 2)) == BibleLocation(genesis, 1)
    assert bible.next_chapter(BibleLocation(genesis, 1)) == BibleLocation(genesis, 3)
    assert bible.previous_chapter(BibleLocation(genesis, 1)) == BibleLocation(exodus, 2)
    assert bible.next_chapter(BibleLocation(john, 1)) is None

    assert bible.next_verse(BibleLocation(exodus, 2, 2)) == BibleLocation(exodus, 2, 5)
    assert bible.next_verse(BibleLocation(exodus, 2, 5)) == BibleLocation(genesis, 1, 1)
    assert bible.next_verse(BibleLocation(genesis, 1, 3)) == BibleLocation(genesis, 3, 2)
    assert bible.previous_verse(BibleLocation(genesis, 1, 1)) == BibleLocation(exodus, 2, 5)

    parsed = bible.parse_reference("Exodus Local 2:2-Genesis Local 1:1")
    assert isinstance(parsed, EditionVerseRange)
    assert _coordinates(bible.resolve_edition_range(parsed)) == [
        (exodus, 2, 2),
        (exodus, 2, 5),
        (genesis, 1, 1),
    ]


def test_rich_passage_parsing_resolution_and_shape_preservation() -> None:
    bible = _load()

    assert _texts(bible.get_passage("Genesis Local")) == [
        "Genesis one one",
        "Genesis one three",
        "Genesis three two",
    ]
    assert _texts(bible.get_passage("Exodus Local 2")) == [
        "Exodus two two",
        "Exodus two five",
    ]
    with pytest.raises(ChapterNotFoundError):
        bible.get_passage("Genesis Local 1-3")
    assert _texts(bible.get_passage("Genesis Local 1; Genesis Local 3")) == [
        "Genesis one one",
        "Genesis one three",
        "Genesis three two",
    ]

    parsed = bible.parse_passage(
        "Genesis Local 1:1,1:3; Genesis Local 1:3"
    )
    # Passage sequences intentionally preserve input order and duplicates.
    assert _texts(bible.resolve_passage(parsed)) == [
        "Genesis one one",
        "Genesis one three",
        "Genesis one three",
    ]

    one = bible.get_by_reference("Genesis Local 1:1")
    assert one.is_verse and one.as_verse().text == "Genesis one one"  # type: ignore[union-attr]
    many = bible.get_by_reference("Genesis Local 1:1-3")
    assert many.is_range
    assert _texts(many.as_range() or ()) == ["Genesis one one", "Genesis one three"]


@pytest.mark.parametrize(
    ("mode", "initially_built", "built_after_search"),
    [
        (SearchIndexMode.EAGER, True, True),
        (SearchIndexMode.LAZY, False, True),
        (SearchIndexMode.DISABLED, False, False),
    ],
)
def test_loading_search_index_modes(
    mode: SearchIndexMode,
    initially_built: bool,
    built_after_search: bool,
) -> None:
    bible = _load(mode=mode)

    assert bible.search_index_mode is mode
    assert bible.has_search_index is initially_built
    assert _coordinates(bible.search("Genesis")) == [
        (BibleBookEnum.Genesis, 1, 1),
        (BibleBookEnum.Genesis, 1, 3),
        (BibleBookEnum.Genesis, 3, 2),
    ]
    assert bible.has_search_index is built_after_search


def test_path_loading_reports_monotonic_phase_progress(tmp_path: Path) -> None:
    path = tmp_path / "tiny.data"
    path.write_text(json.dumps(_schema_v1_document()), encoding="utf-8")
    reports: list[BibleLoadProgress] = []
    scalar_reports: list[float] = []

    loaded = Bible.load(
        path,
        options=BibleLoadOptions(search_index_mode=SearchIndexMode.DISABLED),
        on_load_progress=reports.append,
        on_progress=scalar_reports.append,
    )

    assert loaded.id == "example-2026"
    assert [(item.phase, item.fraction, item.phase_fraction) for item in reports] == [
        (BibleLoadPhase.READING, 0.0, 0.0),
        (BibleLoadPhase.READING, 0.65, 1.0),
        (BibleLoadPhase.PROCESSING, 0.65, 0.0),
        (BibleLoadPhase.PROCESSING, 1.0, 1.0),
        (BibleLoadPhase.COMPLETE, 1.0, 1.0),
    ]
    assert [item.fraction for item in reports] == sorted(
        item.fraction for item in reports
    )
    assert scalar_reports == [0.65, 1.0]


def test_asset_loading_reports_the_stable_progress_sequence() -> None:
    class Bundle:
        async def load_string(self, key: str) -> str:
            assert key == "tiny"
            return json.dumps(_schema_v1_document())

    reports: list[BibleLoadProgress] = []
    loaded = asyncio.run(
        Bible.load_asset(
            Bundle(),
            "tiny",
            options=BibleLoadOptions(
                search_index_mode=SearchIndexMode.DISABLED,
            ),
            on_load_progress=reports.append,
        )
    )

    assert loaded.id == "example-2026"
    assert [report.phase for report in reports] == [
        BibleLoadPhase.READING,
        BibleLoadPhase.READING,
        BibleLoadPhase.PROCESSING,
        BibleLoadPhase.PROCESSING,
        BibleLoadPhase.COMPLETE,
    ]


def test_stats_locations_keys_and_result_helpers() -> None:
    bible = _load()
    stats = bible.stats

    assert (stats.book_count, stats.chapter_count, stats.verse_count) == (3, 4, 6)
    assert stats.total_words == 18
    assert stats.average_verse_length == 15
    assert stats.verses_per_book[BibleBookEnum.Exodus] == 2
    assert stats.verses_per_book[BibleBookEnum.Genesis] == 3
    assert stats.verses_per_book[BibleBookEnum.John] == 1
    assert hash(stats) == hash(bible.stats)

    location = BibleLocation(BibleBookEnum.Genesis, 1, 3)
    assert BibleLocation.from_json(location.to_json()) == location
    assert location.copy_with(verse=None) == BibleLocation(BibleBookEnum.Genesis, 1)
    assert bible.contains_reference(location)
    assert bible.format_location(location) == "Genesis Local 1:3"

    key = bible.key_for_location(location)
    assert key == BibleVerseKey.from_json(key.to_json())
    assert key.edition_id == "example-2026"
    assert key.location == location

    success = bible.get_verse_result(BibleBookEnum.Genesis, 1, 3)
    assert isinstance(success, Success)
    assert success.is_success and not success.is_failure
    assert success.map(lambda verse: verse.text).value == "Genesis one three"

    failure = bible.get_verse_result(BibleBookEnum.Genesis, 1, 2)
    assert isinstance(failure, Failure)
    assert failure.is_failure and not failure.is_success
    assert isinstance(failure.cause, VerseNotFoundError)
    assert failure.get_or_else(None) is None
    assert failure.fold(lambda error: error, lambda verse: verse.text) == failure.error


def test_direct_model_construction_rejects_structural_annotations() -> None:
    bible = _load()

    with pytest.raises(AttributeError):
        setattr(bible, "books", ())
    with pytest.raises(AttributeError):
        setattr(bible, "metadata", BibleMetadata())

    with pytest.raises(ValueError, match="structural key"):
        Bible.from_books(
            bible.books,
            annotations={"books": {"shadowed": True}},
            search_index_mode=SearchIndexMode.DISABLED,
        )


def test_checked_metadata_and_json_scalar_equality_are_strict() -> None:
    with pytest.raises(BibleDataFormatError):
        BibleMetadata(year=True).validate()
    with pytest.raises(BibleDataFormatError):
        BibleSource.checked(
            id="source",
            asset_path="source.json",
            language_name="English",
            language_code="en",
            translation_name="Source",
            abbreviation="SRC",
            description=123,
        )

    bible = _load()
    with_boolean = Bible.from_books(
        bible.books,
        annotations={"flag": True},
        search_index_mode=SearchIndexMode.DISABLED,
    )
    with_number = Bible.from_books(
        bible.books,
        annotations={"flag": 1},
        search_index_mode=SearchIndexMode.DISABLED,
    )
    assert with_boolean != with_number
    assert hash(with_boolean) != hash(with_number)


def test_json_loading_rejects_duplicate_keys_and_lone_surrogates() -> None:
    duplicate = '{"schemaVersion":1,"schemaVersion":1,"books":{}}'
    with pytest.raises(BibleDataFormatError) as duplicate_error:
        Bible.from_json(duplicate)
    assert duplicate_error.value.code is BibleDataFormatErrorCode.DUPLICATE_KEY

    document = _schema_v1_document()
    document["books"]["gn"]["chapters"]["1"]["verses"]["1"]["text"] = "\ud800"
    with pytest.raises(BibleDataFormatError) as unicode_error:
        Bible.from_json(json.dumps(document))
    assert unicode_error.value.code is BibleDataFormatErrorCode.INVALID_VALUE


def test_public_search_index_and_fuzzy_defaults_match_value_contract() -> None:
    verses = (
        Verse(BibleBookEnum.Genesis, 1, 1, "alpha beta"),
        Verse(BibleBookEnum.Genesis, 1, 2, "beta alpha"),
        Verse(BibleBookEnum.Genesis, 1, 3, "emoji \U0001f600"),
    )
    bible = Bible.from_books(
        (
            Book(
                BibleBookEnum.Genesis,
                (Chapter(BibleBookEnum.Genesis, 1, verses),),
            ),
        ),
        search_index_mode=SearchIndexMode.DISABLED,
    )

    index = bible.build_search_index()
    assert index.search("alpha beta") == (
        (BibleBookEnum.Genesis, 1, 1),
        (BibleBookEnum.Genesis, 1, 2),
    )
    assert tuple(bible.fuzzy_search("alpha beta", max_distance=0)) == (
        verses[0],
    )
    assert tuple(
        bible.fuzzy_search(
            "alpha beta",
            SearchOptions(mode=SearchMode.ALL),
            max_distance=0,
        )
    ) == verses[:2]
    assert bible.performance_metrics.text_code_units == sum(
        len(verse.text.encode("utf-16-le")) // 2 for verse in verses
    )


def test_source_inference_and_mixed_catalog_roundtrip() -> None:
    inferred = BibleSource.from_asset_path("bible_io_json/English/kjv.json")
    assert (
        inferred.id,
        inferred.language_name,
        inferred.language_code,
        inferred.translation_name,
        inferred.abbreviation,
    ) == ("english_kjv", "English", "en", "KJV", "KJV")

    catalog = BibleCatalog.from_decoded_json(
        {
            "sources": [
                {
                    "id": "kjv",
                    "assetPath": "bible_io_json/English/kjv.json",
                    "translationName": "King James Version",
                    "abbreviation": "KJV",
                    "languageCode": "en",
                    "provider": {"name": "Fixture Provider"},
                },
                "bible_io_json/Hebrew/wlc.json",
            ]
        }
    )

    assert len(catalog.sources) == 2
    kjv = catalog.find_by_id("kjv")
    assert kjv is not None
    assert kjv.translation_name == "King James Version"
    provider = kjv.additional["provider"]
    assert isinstance(provider, Mapping)
    assert provider["name"] == "Fixture Provider"
    assert catalog.for_language("en")[0].abbreviation == "KJV"
    assert catalog.for_language("he")[0].direction is TextDirectionHint.RTL
    assert BibleCatalog.from_decoded_json(catalog.to_json()) == catalog

    nested = BibleCatalog.from_decoded_json(
        {
            "English": {
                "kjv": "translations/kjv.json",
                "web": "translations/web.json",
            }
        }
    )
    assert [source.id for source in nested.sources] == ["kjv", "web"]
    assert tuple(nested.by_language_name) == ("English",)
    assert len(nested.for_language("English")) == 2
