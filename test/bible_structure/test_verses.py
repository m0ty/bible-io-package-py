

def test_verse_per_chapter(bible):
    verses = bible.get_verses(1, 1)

    assert len(verses) == 31
