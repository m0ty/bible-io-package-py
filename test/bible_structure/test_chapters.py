import pytest

from bible_io import BibleBookEnum
from bible_io.errors import ChapterNotFoundError


def test_chapters_per_book(bible):
    chapters = bible.get_book(BibleBookEnum.Genesis).chapters

    assert len(chapters) == 50


def test_chapters_negative(bible):
    with pytest.raises(ChapterNotFoundError):
        bible.get_book(BibleBookEnum.Genesis).get_verses(51)


def test_get_chapter(bible):
    chapter = bible.get_chapter(BibleBookEnum.Genesis, 1)

    assert chapter.book == BibleBookEnum.Genesis
    assert chapter.chapter_number == 1
    assert len(chapter.get_verses()) == 31


def test_get_chapter_out_of_range(bible):
    with pytest.raises(ChapterNotFoundError):
        bible.get_chapter(BibleBookEnum.Genesis, 0)

    with pytest.raises(ChapterNotFoundError):
        bible.get_chapter(BibleBookEnum.Genesis, 51)
