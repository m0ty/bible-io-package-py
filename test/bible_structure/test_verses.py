import pytest

from bible_io import BibleBookEnum
from bible_io.errors import VerseNotFoundError
from bible_io_references import VerseRangeRef, VerseRef


def test_verse_per_chapter(bible):
    verses = bible.get_verses(BibleBookEnum.Genesis, 1)

    assert len(verses) == 31


def test_verses_negative(bible):
    verses = bible.get_verses(BibleBookEnum.Genesis, 1)
    verse_count = len(verses)

    with pytest.raises(VerseNotFoundError):
        bible.get_book(BibleBookEnum.Genesis).get_verse(1, verse_count + 1)


def test_get_verse_by_ref(bible):
    verse_ref = VerseRef(BibleBookEnum.Genesis, 1, 1)

    verse = bible.get_verse_by_ref(verse_ref)

    assert verse == bible.get_verse(BibleBookEnum.Genesis, 1, 1)


def test_get_verse_range_by_ref_same_chapter(bible):
    verse_range_ref = VerseRangeRef(
        VerseRef(BibleBookEnum.Genesis, 1, 1),
        VerseRef(BibleBookEnum.Genesis, 1, 3),
    )

    verses = bible.get_verse_range_by_ref(verse_range_ref)
    expected = bible.get_verses(BibleBookEnum.Genesis, 1)[:3]

    assert verses == expected


def test_get_verse_range_by_ref_multiple_chapters(bible):
    verse_range_ref = VerseRangeRef(
        VerseRef(BibleBookEnum.Genesis, 1, 31),
        VerseRef(BibleBookEnum.Genesis, 2, 3),
    )

    verses = bible.get_verse_range_by_ref(verse_range_ref)
    expected = (
        bible.get_verses(BibleBookEnum.Genesis, 1)[30:]
        + bible.get_verses(BibleBookEnum.Genesis, 2)[:3]
    )

    assert verses == expected
