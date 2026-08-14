# Bible IO

Bible IO is a typed Python content layer for Bible applications. It loads
validated translation data into edition-aware models and provides stable
navigation, multilingual references, lossless JSON round-tripping, metadata,
catalogs, and Unicode search.

## Features

- Validated `Bible`, `Book`, `Chapter`, and `Verse` value models
- Versioned schema v1 with explicit canon order and extensible annotations
- Strict validation with path-aware `BibleDataFormatError` diagnostics
- Construction from files, strings, UTF-8 bytes, decoded mappings, or models
- Eager, lazy, or disabled search indexes
- Canonically normalized multilingual exact/all/any and fuzzy search
- Paginated, display-ready hits with safe snippets and accurate Python ranges
- Full `bible-io-references` 1.1 API re-export
- Rich passages, custom edition order, OSIS/USFM, and localized formatting
- Edition-aware keys for bookmarks, highlights, notes, and reading progress
- Translation metadata, catalogs, statistics, and performance diagnostics

## Installation

Bible IO supports Python 3.10 and later.

```bash
pip install bible-io
```

`bible-io-references` is a dependency and its public API is re-exported, so one
import provides both content and reference types.

## Quick start

```python
from bible_io import Bible, BibleBookEnum

bible = Bible("path/to/en_kjv.json")

genesis_1_1 = bible.get_verse(BibleBookEnum.Genesis, 1, 1)
john_3_16 = bible.get_verse_by_ref("John 3:16")

print(genesis_1_1.text)
print(john_3_16.text)
```

Declared coordinates—not list offsets—drive lookups. Sparse chapters and
verses therefore work correctly.

```python
book = bible[BibleBookEnum.Genesis]
chapter = bible[BibleBookEnum.Genesis, 1]
verse = bible[BibleBookEnum.Genesis, 1, 1]
```

## Loading

The compatibility constructor loads a JSON path. Equivalent constructors cover
other application boundaries:

```python
from bible_io import Bible

from_path = Bible.load("path/to/bible.json")
from_text = Bible.from_json(json_text)
from_bytes = Bible.from_utf8_bytes(payload)
from_mapping = Bible.from_decoded_json(decoded)

# Keep an asyncio event loop responsive while reading and processing a file.
from_path_async = await Bible.load_async("path/to/bible.json")

# Adapters with load_string(key) can provide bundled application assets.
from_asset = await Bible.load_asset(asset_bundle, "bibles/en_kjv")
```

Load progress uses stable reading, processing, and complete phases:

```python
def report(progress):
    print(progress.phase, f"{progress.fraction:.0%}")

bible = Bible("path/to/bible.json", on_load_progress=report)
```

Search indexes can be retained eagerly, built on first compatible search, or
disabled:

```python
from bible_io import BibleLoadOptions, SearchIndexMode

options = BibleLoadOptions(search_index_mode=SearchIndexMode.LAZY)
bible = Bible("path/to/bible.json", options=options)

print(bible.has_search_index)  # False
bible.prewarm_search_index()
bible.clear_search_index()
```

Content values are immutable. Derive edits with `verse.with_text(...)` and the
model `copy_with(...)` helpers; retained search indexes therefore cannot become
stale through public mutation.

## Validation and schema v1

Strict validation is the default. It requires at least one book, chapter, and
verse and rejects blank verse text. It also rejects malformed types, invalid
identifiers, duplicate semantic books or numeric coordinates, inconsistent
parents, unsupported schema versions, incomplete `bookOrder`, and non-JSON
annotations.

Use the permissive policy only for intentionally skeletal content:

```python
from bible_io import Bible, BibleDataValidationOptions, BibleLoadOptions

partial = Bible.from_decoded_json(
    {"schemaVersion": 1, "books": {}},
    options=BibleLoadOptions(
        validation=BibleDataValidationOptions.PERMISSIVE,
    ),
)
```

Permissive validation relaxes only the four content-presence requirements; it
does not accept malformed structure.

Schema v1 supports legacy plain verse strings and annotated values together:

```json
{
  "schemaVersion": 1,
  "language": "English",
  "metadata": {
    "id": "eng-example-2026",
    "translationName": "Example Translation",
    "abbreviation": "EXT"
  },
  "bookOrder": ["gn"],
  "books": {
    "gn": {
      "name": "Genesis",
      "section": "Pentateuch",
      "chapters": {
        "1": {
          "heading": "Creation",
          "verses": {
            "1": {
              "text": "In the beginning...",
              "paragraphStart": true
            },
            "2": "The earth was formless..."
          }
        }
      }
    }
  }
}
```

Unknown JSON-compatible fields are retained at their original root, metadata,
source, book, chapter, or verse level. `bible.to_json()` emits canonical schema
v1 data with the effective book order.

## References, passages, and navigation

Parsing prefers the loaded edition's language and custom book names while
remaining multilingual by default. Supplying `input_language` makes the input
language explicit.

```python
from bible_io import BibleLanguageEnum

verse = bible.get_verse_by_ref(
    "Juan 3:16",
    input_language=BibleLanguageEnum.SPANISH,
)

range_verses = bible.get_verse_range_by_ref("John 21:25-Acts 1:2")
passage = bible.get_passage("John 3:16,18-20; Acts 2:1-4; Romans 8")
```

Rich passages include whole books, chapter ranges, verse lists/ranges, and
semicolon-separated sequences. Overlaps and explicit sequence duplicates are
preserved. Cross-book ranges and navigation follow the loaded `bookOrder`,
including custom canons.

```python
current = verse.location
next_location = bible.next_verse(current)
previous_location = bible.previous_verse(current)
```

Persist UI state with an edition-aware key rather than a location alone:

```python
key = bible.key_for_verse(verse)
stored = key.to_json()
restored = type(key).from_json(stored)
```

The Bible metadata must define a stable, trimmed `id` before a key can be
created.

## Search

`search()` is a fast all-terms search, not an exact phrase search:

```python
verses = bible.search("faith hope")
```

Advanced search controls modes, scopes, normalization, and pagination:

```python
from bible_io import SearchMode, SearchOptions

page = bible.search_with_options(
    "creacion",
    SearchOptions(
        mode=SearchMode.ANY,
        ignore_diacritics=True,
        offset=20,
        max_results=20,
    ),
)

print(page.count, page.has_more, page.next_offset)
for hit in page.hits:
    print(hit.reference, hit.snippet, hit.snippet_match_ranges)
```

Canonical NFC normalization is enabled by default. Diacritic folding is
explicit because marks can be meaningful in Hebrew and Arabic. Unspaced Han,
kana, Thai, Lao, Khmer, and Myanmar queries receive substring-aware token
matching. Typo-tolerant search uses bounded Unicode edit distance:

```python
page = bible.fuzzy_search(
    "beginnig creatd",
    max_distance=1,
    mode=SearchMode.ALL,
    max_results=20,
)
```

`TextRange` values use half-open Python string indices, so they can be passed
directly to normal Python slicing.

## Metadata and catalogs

`BibleMetadata` carries edition identity, language, display name,
abbreviation, direction, provenance, copyright, content license, canon, and
version date. `BibleSource` represents a catalog/load source and can infer
common values from an asset path.

```python
from bible_io import BibleCatalog

catalog = BibleCatalog.from_decoded_json(catalog_data)
source = catalog.find_by_id("eng-kjv-1769")
english_sources = catalog.for_language("en")
```

Catalogs accept lists, ID-keyed maps, nested language maps, and the documented
`sources`, `bibles`, or `translations` container names.

## Statistics and diagnostics

```python
print(bible.stats)
print(bible.get_book(BibleBookEnum.Genesis).stats)
print(bible.get_chapter(BibleBookEnum.Genesis, 1).stats)
print(bible.performance_metrics)
```

Performance and memory values are estimates intended for diagnostics, not heap
profiling.

## Development

```bash
uv run pytest
uv run coverage run -m pytest
uv run coverage report
uv run mypy src test
uv build
```

Coverage measures branches as well as statements and is gated at 90% combined
coverage. The parity suites mirror the current Rust and Dart contracts across
schema validation, immutable values, loaders and progress, sparse navigation,
references and passages, metadata and catalogs, Unicode search, persisted
state, results, statistics, and index lifecycle. They were audited against
[`bible-io-package-rs` main at `13cf07b`](https://github.com/m0ty/bible-io-package-rs/commit/13cf07b73cf4a49e116f3b4cd48e55a7ffcb6d2e)
and [`bible-io-package-dart` main at `8f056b6`](https://github.com/m0ty/bible-io-package-dart/commit/8f056b6734c5f80e656c4b12e8e3de0786c0837b).

The test fixture is development-only and is not included in package archives.

## License

Bible IO source code is licensed under the GNU Affero General Public License
v3 (`AGPL-3.0-only`); see [LICENSE](LICENSE).

Bible translations, study notes, and other loaded content are independent
works. Applications and data distributors must obtain and honor the rights for
each edition; the metadata `copyright` and `license` fields can carry those
terms with the content.
