from src.bible_io import Bible, Verse


def test_search(bible):
    verses = bible.search("Moses")

    assert verses, "Expected to find at least one verse containing 'Moses'"

    for verse in verses:
        assert isinstance(verse, Verse)
        assert verse.contains_word("Moses")


def test_search_normalizes_query(bible):
    verses = bible.search("mOsEs!!!")

    assert verses, "Expected to find verses despite mixed case and punctuation"
    assert all(verse.contains_word("Moses") for verse in verses)


def test_search_deduplicates_results(bible):
    verses = bible.search("Moses moses MOSes")

    assert verses, "Expected deduplicated verses for repeated query terms"
    assert len(verses) == len({id(verse) for verse in verses})


def test_search_reuses_built_index(bible, monkeypatch):
    build_calls = 0
    original_build = Bible._build_search_index

    def counted(self):
        nonlocal build_calls
        build_calls += 1
        return original_build(self)

    monkeypatch.setattr(Bible, "_build_search_index", counted)

    bible.invalidate_search_index()

    bible.search("Moses")
    assert build_calls == 1

    bible.search("Moses")
    assert build_calls == 1


def test_search_rebuilds_after_text_change(bible):
    verses = bible.search("Moses")
    assert verses

    verse = verses[0]
    verse.text = "uniquetestword"

    bible.invalidate_search_index()

    updated_results = bible.search("uniquetestword")
    assert verse in updated_results
