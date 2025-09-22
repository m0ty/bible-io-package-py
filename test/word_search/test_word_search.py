from src.bible_io import Verse


def test_search(bible):
    verses = bible.search("Moses")

    assert verses, "Expected to find at least one verse containing 'Moses'"

    for verse in verses:
        assert isinstance(verse, Verse)
        assert verse.contains_word("Moses")
