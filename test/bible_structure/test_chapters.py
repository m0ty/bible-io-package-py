
def test_chapters_per_book(bible):
    chapters = bible.get_book(1).chapters

    assert len(chapters) == 50
