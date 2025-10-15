import pytest

from bible_io import BibleBookEnum
from bible_io.errors import ChapterNotFoundError


def test_chapters_per_book(bible):
    chapters = bible.get_book(BibleBookEnum.Genesis).chapters

    assert len(chapters) == 50


def test_chapters_negative(bible):
    with pytest.raises(ChapterNotFoundError):
        bible.get_book(BibleBookEnum.Genesis).get_verses(51)
