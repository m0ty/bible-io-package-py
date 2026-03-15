from bible_io_references import BibleBookEnum
from .errors import VerseNotFoundError
from .verse import Verse


class Chapter:
    """Collection of verses representing a single chapter in a book."""

    def __init__(self, book: BibleBookEnum, chapter_number: int, verses: list[Verse]):
        """Create a Chapter instance.

        Args:
            book (BibleBookEnum): Enumeration identifying the parent book.
            chapter_number (int): One-based chapter number.
            verses (list[Verse]): Verses included in this chapter.

        Returns:
            None: The object is initialized with the provided verses.
        """

        self.book = book
        self.chapter_number = chapter_number
        self.verses = verses

    def get_verses(self) -> list[Verse]:
        """Return all verses in the chapter.

        Returns:
            list[Verse]: The verses in sequential order.
        """

        return self.verses

    def get_verse(self, verse_number: int) -> Verse:
        """Retrieve a verse by its index within the chapter.

        Args:
            verse_number (int): One-based verse number.

        Returns:
            Verse: The matching verse instance.

        Raises:
            VerseNotFoundError: If ``verse_number`` is invalid.
        """

        if not (1 <= verse_number <= len(self.verses)):
            raise VerseNotFoundError(self.book, self.chapter_number, verse_number)
        return self.verses[verse_number - 1]

    def search(self, word: str) -> list[Verse]:
        """Search verses in the chapter for a word.

        Args:
            word (str): Word or phrase to search, case-insensitive.

        Returns:
            list[Verse]: Verses containing the search token.
        """

        matches: list['Verse'] = []
        for verse in self.verses:
            if verse.contains_word(word):
                matches.append(verse)
        return matches
