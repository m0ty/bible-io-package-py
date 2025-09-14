import pytest

from src.bible_io.errors import ChapterNotFoundError


def test_chapters_per_book(bible):
    chapters = bible.get_book(1).chapters

    assert len(chapters) == 50


def test_chapters_negative(bible):
    with pytest.raises(ChapterNotFoundError):
        bible.get_book(1).get_verses(51)

