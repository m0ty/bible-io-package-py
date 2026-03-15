from bible_io_references import BibleBookEnum


class Verse:
    """Lightweight data structure representing a single verse."""

    def __init__(self, book: BibleBookEnum, chapter_number: int, verse_number: int, text: str):
        """Create a Verse instance.

        Args:
            book (BibleBookEnum): Enumeration identifying the parent book.
            chapter_number (int): Chapter containing the verse.
            verse_number (int): One-based verse number.
            text (str): The verse text content.

        Returns:
            None: The verse fields are set in-place.
        """

        self.book = book
        self.chapter_number = chapter_number
        self.verse_number = verse_number
        self.text = text

    def __repr__(self):
        """Return a developer-friendly representation of the verse.

        Returns:
            str: String including the verse reference and text.
        """

        return (
            f"Verse({self.book.as_str()}:{self.chapter_number}:{self.verse_number}) -> {self.text}"
        )

    def contains_word(self, word: str) -> bool:
        """Check if the verse contains a given word (case-insensitive).

        Args:
            word (str): Word or phrase to search for within the verse text.

        Returns:
            bool: ``True`` if the normalized word is found; otherwise ``False``.
        """

        return word.lower() in self.text.lower()
