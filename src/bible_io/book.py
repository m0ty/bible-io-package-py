from bible_io_references import BibleBookEnum
from .chapter import Chapter
from .errors import ChapterNotFoundError
from .verse import Verse


class Book:
    """Container for chapters belonging to a single Bible book."""

    def __init__(self, book_enum: BibleBookEnum, chapters: list[Chapter], name: str | None = None):
        """Create a Book instance.

        Args:
            book_enum (BibleBookEnum): Enumeration identifying the book.
            chapters (list[Chapter]): Ordered list of chapters in the book.
            name (str | None): Optional display name overriding the default.

        Returns:
            None: The object is initialized with the provided data.
        """

        self.book_enum = book_enum
        self.name = name or book_enum.full_name
        self.chapters = chapters

    def get_chapters(self) -> list[Chapter]:
        """Return the chapters that belong to this book.

        Returns:
            list[Chapter]: Ordered chapters contained in the book.
        """

        return self.chapters

    def get_verses(self, chapter_number: int) -> list[Verse]:
        """Retrieve all verses for the requested chapter number.

        Args:
            chapter_number (int): One-based chapter index.

        Returns:
            list[Verse]: Verses contained in the chapter.

        Raises:
            ChapterNotFoundError: If ``chapter_number`` is invalid.
        """

        if not (1 <= chapter_number <= len(self.chapters)):
            raise ChapterNotFoundError(self.book_enum, chapter_number)
        return self.chapters[chapter_number - 1].get_verses()

    def get_verse(self, chapter_number: int, verse_number: int) -> Verse:
        """Retrieve a single verse from a chapter.

        Args:
            chapter_number (int): One-based chapter index.
            verse_number (int): One-based verse index.

        Returns:
            Verse: The requested verse.

        Raises:
            ChapterNotFoundError: If the chapter is not part of this book.
            VerseNotFoundError: If the verse number is invalid within the chapter.
        """

        if not (1 <= chapter_number <= len(self.chapters)):
            raise ChapterNotFoundError(self.book_enum, chapter_number)
        return self.chapters[chapter_number - 1].get_verse(verse_number)

    def search(self, word: str) -> list[Verse]:
        """Search within the book for verses containing a word.

        Args:
            word (str): Word or phrase to search, case-insensitive.

        Returns:
            list[Verse]: Verses containing the search token.
        """

        matches: list['Verse'] = []
        for chapter in self.chapters:
            matches.extend(chapter.search(word))
        return matches

    def __repr__(self):
        """Return a helpful string representation of the book.

        Returns:
            str: Abbreviated book identifier and display name.
        """

        return f"Book({self.book_enum.as_str()}: {self.name})"
