import pytest

from bible_io import BibleBookEnum
from bible_io.errors import VerseNotFoundError


def test_verse_per_chapter(bible):
    verses = bible.get_verses(BibleBookEnum.Genesis, 1)

    assert len(verses) == 31


def test_verses_negative(bible):
    verses = bible.get_verses(BibleBookEnum.Genesis, 1)
    verse_count = len(verses)

    with pytest.raises(VerseNotFoundError):
        bible.get_book(BibleBookEnum.Genesis).get_verse(1, verse_count + 1)
