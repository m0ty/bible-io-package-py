"""Behavioral contracts mirrored from bible-io-package-dart.

The upstream Dart suite was audited at commit
``8f056b6734c5f80e656c4b12e8e3de0786c0837b``.  These cases intentionally
cover contracts that are not already exercised by the broader Python suite.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from bible_io import (
    Bible,
    BibleBookEnum,
    BibleCatalog,
    BibleDataFormatError,
    BibleDataFormatErrorCode,
    BibleLanguageEnum,
    BibleLoadOptions,
    BibleLoadPhase,
    BibleLoadProgress,
    BibleLocation,
    BibleMetadata,
    BibleSource,
    BibleVerseKey,
    Book,
    Chapter,
    ChapterPassage,
    Failure,
    Result,
    ResultException,
    SearchIndexMode,
    SearchMode,
    TextDirectionHint,
    Verse,
    VersePassage,
    VerseRef,
    merge_bible_metadata,
)


def _document(*texts: str, language: str | None = "English") -> dict[str, Any]:
    document: dict[str, Any] = {
        "schemaVersion": 1,
        "books": {
            "gn": {
                "name": "Genesis",
                "chapters": {
                    "1": {
                        str(number): text
                        for number, text in enumerate(texts, start=1)
                    }
                },
            }
        },
    }
    if language is not None:
        document["language"] = language
    return document


def _source(**changes: object) -> BibleSource:
    values: dict[str, Any] = {
        "id": "wlc",
        "asset_path": "bibles/Hebrew/wlc.json",
        "language_name": "Hebrew",
        "language_code": "he",
        "translation_name": "Westminster Leningrad Codex",
        "abbreviation": "WLC",
        "description": "Stable source",
        "direction": TextDirectionHint.RTL,
    }
    values.update(changes)
    return BibleSource.checked(**values)


def test_all_load_entrypoints_preserve_unicode_and_supplied_source() -> None:
    texts = (
        "في البدء خلق الله السماوات والأرض",
        "В начале сотворил Бог небо и землю",
        "起初，神创造天地。",
    )
    source = _source()
    document = _document(*texts, language=None)
    encoded = json.dumps(document, ensure_ascii=False)
    options = BibleLoadOptions(search_index_mode=SearchIndexMode.DISABLED)

    class CamelCaseBundle:
        def loadString(self, key: str) -> str:  # noqa: N802 - Dart adapter API
            assert key == "unicode.json"
            return encoded

    async def load_async_variants() -> tuple[Bible, Bible, Bible]:
        foreground = await Bible.from_json_async(
            encoded,
            source=source,
            options=options.copy_with(parse_in_background=False),
        )
        background = await Bible.from_json_async(
            encoded,
            source=source,
            options=options.copy_with(parse_in_background=True),
        )
        asset = await Bible.load_asset(
            CamelCaseBundle(),
            "unicode.json",
            source=source,
            options=options,
        )
        return foreground, background, asset

    bibles = (
        Bible.from_decoded_json(document, source=source, options=options),
        Bible.from_utf8_bytes(encoded.encode(), source=source, options=options),
        *asyncio.run(load_async_variants()),
    )

    for bible in bibles:
        assert tuple(
            bible.get_verse(BibleBookEnum.Genesis, 1, number).text
            for number in range(1, 4)
        ) == texts
        assert bible.source == source
        assert bible.language is BibleLanguageEnum.HEBREW


def test_path_loader_preserves_os_errors_and_wraps_decode_errors(
    tmp_path: Path,
) -> None:
    with pytest.raises(FileNotFoundError):
        Bible.load(tmp_path / "missing.json")

    malformed = tmp_path / "malformed.data"
    malformed.write_text("{not JSON", encoding="utf-8")
    with pytest.raises(BibleDataFormatError) as invalid_json:
        Bible.load(malformed)
    assert invalid_json.value.code is BibleDataFormatErrorCode.INVALID_JSON
    assert isinstance(invalid_json.value.cause, json.JSONDecodeError)

    with pytest.raises(BibleDataFormatError) as invalid_utf8:
        Bible.from_utf8_bytes(b"\xff")
    assert invalid_utf8.value.code is BibleDataFormatErrorCode.INVALID_JSON
    assert isinstance(invalid_utf8.value.cause, UnicodeDecodeError)

    class InvalidBundle:
        def load_string(self, key: str) -> int:
            return 7

    with pytest.raises(BibleDataFormatError) as invalid_asset:
        asyncio.run(Bible.load_asset(InvalidBundle(), "bad.json"))
    assert invalid_asset.value.code is BibleDataFormatErrorCode.INVALID_TYPE
    assert invalid_asset.value.path == "$"


def test_large_path_load_reports_real_intermediate_read_progress(
    tmp_path: Path,
) -> None:
    # The implementation reads in 1 MiB chunks, so this forces a genuine
    # partial read report rather than only boundary notifications.
    document = _document("created " * 150_000)
    path = tmp_path / "large.translation"
    path.write_text(json.dumps(document), encoding="utf-8")
    progress: list[BibleLoadProgress] = []
    scalar_progress: list[float] = []

    bible = Bible.load(
        path,
        options=BibleLoadOptions(search_index_mode=SearchIndexMode.DISABLED),
        on_load_progress=progress.append,
        on_progress=scalar_progress.append,
    )

    assert bible.verse_count == 1
    assert any(
        report.phase is BibleLoadPhase.READING
        and 0.0 < report.fraction < 0.65
        and 0.0 < report.phase_fraction < 1.0
        for report in progress
    )
    assert progress[-1] == BibleLoadProgress(BibleLoadPhase.COMPLETE, 1.0, 1.0)
    assert [report.fraction for report in progress] == sorted(
        report.fraction for report in progress
    )
    assert scalar_progress[-1] == 1.0
    assert scalar_progress == sorted(set(scalar_progress))
    assert all(0.0 < value <= 0.65 for value in scalar_progress[:-1])


def test_source_copy_value_semantics_and_required_field_diagnostics() -> None:
    raw_additional: dict[str, object] = {
        "provider": {
            "revision": 2,
            "links": ["https://example.test"],
        }
    }
    source = _source(additional=raw_additional)
    provider = source.additional["provider"]
    assert isinstance(provider, Mapping)

    raw_provider = raw_additional["provider"]
    assert isinstance(raw_provider, dict)
    raw_provider["revision"] = 3
    assert provider["revision"] == 2
    assert provider["links"] == ("https://example.test",)
    with pytest.raises(TypeError):
        provider["revision"] = 4  # type: ignore[index]

    restored = BibleSource.from_decoded_json(source.to_json())
    assert restored == source
    assert hash(restored) == hash(source)
    assert source.copy_with(description=None).description is None
    assert source.copy_with(translation_name="WLC 2026").id == source.id

    with pytest.raises(BibleDataFormatError) as padded:
        BibleSource.from_decoded_json({**source.to_json(), "id": " wlc "})
    assert padded.value.code is BibleDataFormatErrorCode.INVALID_VALUE
    assert padded.value.path == "$.id"

    invalid = BibleSource(
        id="",
        asset_path="bible.json",
        language_name="English",
        language_code="en",
        translation_name="Example",
        abbreviation="EX",
    )
    with pytest.raises(BibleDataFormatError) as missing:
        invalid.validate()
    assert missing.value.code is BibleDataFormatErrorCode.MISSING_FIELD
    assert missing.value.path == "$.id"


def test_metadata_precedence_extension_levels_override_and_merge() -> None:
    embedded = _source(
        id="embedded-id",
        description="source description",
        translation_name="Source name",
        abbreviation="SRC",
        license="source license",
        additional={"sourceExtension": {"revision": 1}},
    )
    supplied = _source(
        id="catalog-id",
        translation_name="Catalog name",
        abbreviation="CAT",
    )
    metadata = BibleMetadata.from_decoded_json(
        {
            "id": "root-id",
            "description": "root description",
            "license": "root license",
            "rootExtension": {"level": "root"},
            "source": embedded.to_json(),
            "metadata": {
                "translationName": "Metadata name",
                "metadataExtension": {"level": "metadata"},
            },
        }
    )

    assert metadata.id == "root-id"
    assert metadata.description == "root description"
    assert metadata.translation_name == "Metadata name"
    assert metadata.license == "root license"
    assert metadata.source == embedded
    assert metadata.source.additional["sourceExtension"] == {"revision": 1}
    assert metadata.additional["rootExtension"] == {"level": "root"}
    assert metadata.additional["metadataExtension"] == {"level": "metadata"}

    overridden = BibleMetadata.from_decoded_json(
        {"source": embedded.to_json()},
        source=supplied,
    )
    assert overridden.source is supplied
    assert overridden.id == "catalog-id"
    assert overridden.translation_name == "Catalog name"

    merged = merge_bible_metadata(
        metadata=BibleMetadata(
            translation_name="Display name",
            license="Custom license note",
        ),
        source=supplied,
        fallback_language_name="Fallback",
    )
    assert merged.source is supplied
    assert merged.id == "catalog-id"
    assert merged.translation_name == "Display name"
    assert merged.language_name == "Hebrew"
    assert merged.direction is TextDirectionHint.RTL
    assert merged.license == "Custom license note"


def test_metadata_checked_extensions_use_structured_errors() -> None:
    with pytest.raises(BibleDataFormatError) as non_json:
        BibleMetadata.with_additional(
            additional={"bad": datetime(2026, 1, 1)},
        )
    assert non_json.value.code is BibleDataFormatErrorCode.NON_JSON_VALUE
    assert non_json.value.path == "$.metadata.bad"

    with pytest.raises(BibleDataFormatError) as reserved:
        BibleMetadata.with_additional(
            additional={"translationName": "hidden"},
        )
    assert reserved.value.code is BibleDataFormatErrorCode.RESERVED_FIELD
    assert reserved.value.path == "$.metadata.translationName"


def test_catalog_rejects_bad_entries_and_supports_asset_adapters() -> None:
    source = _source(id="same")
    with pytest.raises(BibleDataFormatError) as duplicate:
        BibleCatalog((source, source))
    assert duplicate.value.code is BibleDataFormatErrorCode.DUPLICATE_ID
    assert duplicate.value.path == "$.sources[1].id"

    with pytest.raises(BibleDataFormatError) as missing_path:
        BibleCatalog.from_decoded_json({"sources": [{"id": "missing-path"}]})
    assert missing_path.value.path == "$.sources[0].assetPath"

    with pytest.raises(BibleDataFormatError) as malformed:
        BibleCatalog.from_decoded_json({"English": {"broken": 7}})
    assert malformed.value.code is BibleDataFormatErrorCode.INVALID_TYPE
    assert malformed.value.path == "$.English.broken"

    with pytest.raises(BibleDataFormatError) as invalid_json:
        BibleCatalog.from_json("{not JSON")
    assert invalid_json.value.code is BibleDataFormatErrorCode.INVALID_JSON
    assert isinstance(invalid_json.value.cause, json.JSONDecodeError)

    expected = BibleCatalog((source,))

    class CatalogBundle:
        def loadString(self, key: str) -> str:  # noqa: N802 - Dart adapter API
            assert key == "catalog.json"
            return json.dumps(expected.to_json())

    restored = asyncio.run(BibleCatalog.load_asset(CatalogBundle(), "catalog.json"))
    assert restored == expected
    assert restored.find_by_id("same") == source


def test_location_and_verse_key_interoperate_with_reference_values() -> None:
    reference = VerseRef(BibleBookEnum.Genesis, 2, 3)
    location = BibleLocation.from_verse_ref(reference)

    assert location.to_verse_ref() == reference
    assert location.to_passage() == VersePassage((reference,))
    assert BibleLocation(BibleBookEnum.Genesis, 2).to_passage() == ChapterPassage(
        BibleBookEnum.Genesis,
        2,
    )
    assert location.copy_with(chapter=3).verse == 3
    assert location.copy_with(verse=None) == BibleLocation(
        BibleBookEnum.Genesis,
        2,
    )
    assert BibleLocation.from_json(location.to_json()) == location

    with pytest.raises(ValueError):
        BibleLocation.from_json({"book": "gn", "chapter": "2"})
    with pytest.raises(ValueError):
        BibleLocation.from_json({"book": "unknown", "chapter": 2})

    verse = Verse(BibleBookEnum.Genesis, 2, 3, "text")
    key = BibleVerseKey.from_verse("eng-example", verse)
    assert BibleVerseKey.from_json(key.to_json()) == key
    assert key.to_verse_ref() == reference
    assert key.copy_with(edition_id="eng-other").edition_id == "eng-other"

    with pytest.raises(ValueError):
        BibleVerseKey(" ", location)
    with pytest.raises(ValueError):
        BibleVerseKey(
            "eng-example",
            BibleLocation(BibleBookEnum.Genesis, 2),
        )
    with pytest.raises(ValueError):
        BibleVerseKey.from_json(
            {
                "editionId": 1,
                "location": {"book": "gn", "chapter": 2, "verse": 3},
            }
        )


def test_result_failures_retain_cause_and_traceback_through_mapping() -> None:
    cause: BibleDataFormatError | None = None
    try:
        raise BibleDataFormatError(
            code=BibleDataFormatErrorCode.INVALID_VALUE,
            path="$.books",
            message="Invalid books.",
        )
    except BibleDataFormatError as error:
        cause = error
        original_traceback = error.__traceback__

    assert cause is not None
    failure: Result[int] = Result.failure_from(cause)
    mapped = failure.map(str)
    assert isinstance(failure, Failure)
    assert failure.error == "Invalid books."
    assert failure.cause is cause
    assert failure.traceback is original_traceback
    assert mapped.cause is cause
    assert mapped.traceback is original_traceback

    with pytest.raises(ResultException) as raised:
        _ = mapped.value
    assert raised.value.cause is cause
    assert raised.value.traceback is original_traceback

    string_failure: Result[int] = Result.failure("not found")
    assert string_failure.error == "not found"
    assert string_failure.cause is None
    assert string_failure.traceback is None


def test_direct_models_sort_copy_freeze_and_encode_annotation_values() -> None:
    raw_annotations: dict[str, object] = {
        "layout": {"lines": ["first"]},
    }
    verse_two = Verse(
        BibleBookEnum.Genesis,
        1,
        2,
        "second",
        annotations=raw_annotations,
    )
    raw_layout = raw_annotations["layout"]
    assert isinstance(raw_layout, dict)
    raw_layout["lines"] = ["changed"]
    assert verse_two.annotations["layout"] == {"lines": ("first",)}
    assert verse_two.to_json_value() == {
        "text": "second",
        "layout": {"lines": ["first"]},
    }
    assert Verse(BibleBookEnum.Genesis, 1, 1, "plain").to_json_value() == "plain"

    verse_one = Verse(BibleBookEnum.Genesis, 1, 1, "first")
    chapter_one = Chapter(
        BibleBookEnum.Genesis,
        1,
        (verse_two, verse_one),
        annotations={"heading": {"kind": "major"}},
    )
    chapter_three = Chapter(
        BibleBookEnum.Genesis,
        3,
        (Verse(BibleBookEnum.Genesis, 3, 2, "later"),),
    )
    book = Book(
        BibleBookEnum.Genesis,
        (chapter_three, chapter_one),
        annotations={"aliases": ["Beginning"]},
    )

    assert [verse.verse_number for verse in chapter_one.verses] == [1, 2]
    assert [chapter.chapter_number for chapter in book.chapters] == [1, 3]
    assert chapter_one.copy_with(annotations={}).annotations == {}
    assert book.copy_with(name="Genesis custom").name == "Genesis custom"
    assert verse_two.copy_with(text="updated").text == "updated"
    assert book.to_json_value() == {
        "aliases": ["Beginning"],
        "name": "Genesis",
        "chapters": {
            "1": {
                "heading": {"kind": "major"},
                "verses": {
                    "1": "first",
                    "2": {"text": "second", "layout": {"lines": ["first"]}},
                },
            },
            "3": {"2": "later"},
        },
    }
    equal = Book(
        BibleBookEnum.Genesis,
        book.chapters,
        annotations={"aliases": ["Beginning"]},
    )
    assert equal == book
    assert hash(equal) == hash(book)


def test_search_index_lifecycle_and_all_term_hit_ranges() -> None:
    document = _document(
        "alpha beta gamma",
        "beta appears before alpha",
        "beta only",
    )
    lazy = Bible.from_decoded_json(
        document,
        options=BibleLoadOptions(search_index_mode=SearchIndexMode.LAZY),
    )

    assert not lazy.has_search_index
    results = lazy.search_advanced("alpha beta", mode=SearchMode.ALL)
    assert lazy.has_search_index
    assert [verse.verse_number for verse in results.verses] == [1, 2]
    for hit in results.hits:
        matched = {
            hit.verse.text[match.start : match.end].casefold()
            for match in hit.match_ranges
        }
        assert {"alpha", "beta"} <= matched

    lazy.clear_search_index()
    assert not lazy.has_search_index
    asyncio.run(lazy.prewarm_search_index_async())
    assert lazy.has_search_index
    lazy.clear_search_index()
    lazy.prewarm_search_index()
    assert lazy.has_search_index

    disabled = Bible.from_decoded_json(
        document,
        options=BibleLoadOptions(search_index_mode=SearchIndexMode.DISABLED),
    )
    assert disabled.search("alpha beta")
    disabled.prewarm_search_index()
    asyncio.run(disabled.prewarm_search_index_async())
    assert not disabled.has_search_index
