import pytest
from bible_io.errors import VerseNotFoundError


def test_verse_per_chapter(bible):
    verses = bible.get_verses(1, 1)

    assert len(verses) == 31


def test_verses_negative(bible):
    verses = bible.get_verses(1, 1)
    verse_count = len(verses)

    with pytest.raises(VerseNotFoundError):
        bible.get_book(1).get_verse(1, verse_count + 1)
