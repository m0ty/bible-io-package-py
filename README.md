# Bible-IO

A Python package for loading and working with structured Bible text data. The
package reads JSON exports of Bible translations and exposes convenient classes
for navigating books, chapters, and verses or running simple searches.

## Features

- Parse Bible translations from JSON files into rich Python objects
- Access books, chapters, and verses by index or by enum identifiers
- Search verses for a word or phrase (case-insensitive)
- Pythonic error handling with custom exceptions for missing references

## Installation

Install the package from PyPI:

```bash
pip install bible-io
```

Or install from a local clone:

```bash
pip install .
```

Python 3.7 or later is required.

## Getting Started

```python
from bible_io import Bible
from bible_io.bible_book_enums import BibleBook

# Load a translation exported in the supported JSON structure
bible = Bible.new("path/to/en_kjv.json")

# Retrieve a specific chapter (Genesis 1) using canonical indices
for verse in bible.get_verses(1, 1):
    print(f"Genesis 1:{verse.verse_number} {verse.text}")

# Access a book via the BibleBook enum
john = bible.get_book_by_enum(BibleBook.John)

# Fetch John 3:16 and print the verse text
john_316 = john.get_verse(3, 16)
print(john_316.text)

# Search the entire translation (case-insensitive)
for verse in bible.search("shepherd"):
    print(verse)
```

The high-level API centres around four classes:

- `Bible` – container for all loaded books.
- `Book` – holds the chapters of a single Bible book.
- `Chapter` – manages the verses inside a chapter and validates access.
- `Verse` – stores an individual verse with helpers such as `contains_word`.

Additional helper enums and exceptions live in `bible_io.bible_book_enums` and
`bible_io.errors` respectively.

## JSON Structure

The loader expects Bible data in the following JSON format:

```json
{
    "id": "kjv",
    "name": "King James Version",
    "description": "The King James Version (Oxford 1769) is a standardized revision of the classic 1611 English Bible.",
    "language": "English",
    "books": {
        "gn": {
            "name": "Genesis",
            "chapters": {
                "1": {
                    "1": "In the beginning God created the heaven and the earth.",
                    "2": "And the earth was without form, and void; and darkness {was} upon the face of the deep. And the Spirit of God moved upon the face of the waters.",
                    "3": "And God said, Let there be light: and there was light."
                },
                "2": {
                    "1": "Thus the heavens and the earth were finished, and all the host of them.",
                    "2": "And on the seventh day God ended his work which he had made; and he rested on the seventh day from all his work which he had made.",
                    "3": "And God blessed the seventh day, and sanctified it: because that in it he had rested from all his work which God created and made. "
                }
            }
        }
    }
}
```

Each book entry uses a compact abbreviation (e.g., `"gn"` for Genesis). The
loader maps these abbreviations onto `BibleBook` enum members and constructs the
corresponding hierarchy of `Book`, `Chapter`, and `Verse` objects.

## Running the Tests

The repository uses `pytest` for automated tests. After installing the package's
dependencies (via `pip install .` or `pip install -e .`), run:

```bash
pytest
```

If you prefer [`uv`](https://github.com/astral-sh/uv), you can run the suite via:

```bash
uv run pytest
```

The test suite expects the sample translation at
`test/bible_versions/en_kjv.json`.

## License

MIT License – see the [LICENSE](LICENSE) file for details.
