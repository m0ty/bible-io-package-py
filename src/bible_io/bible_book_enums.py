from enum import Enum
from typing import Dict


class ParseBibleBookError(ValueError):
    """Error raised when parsing an unknown or unsupported abbreviation."""

    def __str__(self) -> str:
        """Return the human-friendly error message.

        Returns:
            str: A short description indicating the abbreviation was invalid.
        """
        return "invalid Bible book abbreviation"


class BibleBookEnum(Enum):
    """Enumeration of Bible books with abbreviations and standard names."""
    # --- Protestant (66) ---
    Genesis = ("gn", "Genesis")
    Exodus = ("ex", "Exodus")
    Leviticus = ("lv", "Leviticus")
    Numbers = ("nm", "Numbers")
    Deuteronomy = ("dt", "Deuteronomy")
    Joshua = ("js", "Joshua")
    Judges = ("jud", "Judges")
    Ruth = ("rt", "Ruth")
    FirstSamuel = ("1sm", "1 Samuel")
    SecondSamuel = ("2sm", "2 Samuel")
    FirstKings = ("1kgs", "1 Kings")
    SecondKings = ("2kgs", "2 Kings")
    FirstChronicles = ("1ch", "1 Chronicles")
    SecondChronicles = ("2ch", "2 Chronicles")
    Ezra = ("ezr", "Ezra")
    Nehemiah = ("ne", "Nehemiah")
    Esther = ("et", "Esther")
    Job = ("job", "Job")
    Psalms = ("ps", "Psalms")
    Proverbs = ("prv", "Proverbs")
    Ecclesiastes = ("ec", "Ecclesiastes")
    SongOfSolomon = ("so", "Song of Solomon")
    Isaiah = ("is", "Isaiah")
    Jeremiah = ("jr", "Jeremiah")
    Lamentations = ("lm", "Lamentations")
    Ezekiel = ("ez", "Ezekiel")
    Daniel = ("dn", "Daniel")
    Hosea = ("ho", "Hosea")
    Joel = ("jl", "Joel")
    Amos = ("am", "Amos")
    Obadiah = ("ob", "Obadiah")
    Jonah = ("jn", "Jonah")
    Micah = ("mi", "Micah")
    Nahum = ("na", "Nahum")
    Habakkuk = ("hk", "Habakkuk")
    Zephaniah = ("zp", "Zephaniah")
    Haggai = ("hg", "Haggai")
    Zechariah = ("zc", "Zechariah")
    Malachi = ("ml", "Malachi")
    Matthew = ("mt", "Matthew")
    Mark = ("mk", "Mark")
    Luke = ("lk", "Luke")
    John = ("jo", "John")
    Acts = ("act", "Acts")
    Romans = ("rm", "Romans")
    FirstCorinthians = ("1co", "1 Corinthians")
    SecondCorinthians = ("2co", "2 Corinthians")
    Galatians = ("gl", "Galatians")
    Ephesians = ("eph", "Ephesians")
    Philippians = ("ph", "Philippians")
    Colossians = ("cl", "Colossians")
    FirstThessalonians = ("1ts", "1 Thessalonians")
    SecondThessalonians = ("2ts", "2 Thessalonians")
    FirstTimothy = ("1tm", "1 Timothy")
    SecondTimothy = ("2tm", "2 Timothy")
    Titus = ("tt", "Titus")
    Philemon = ("phm", "Philemon")
    Hebrews = ("hb", "Hebrews")
    James = ("jm", "James")
    FirstPeter = ("1pe", "1 Peter")
    SecondPeter = ("2pe", "2 Peter")
    FirstJohn = ("1jo", "1 John")
    SecondJohn = ("2jo", "2 John")
    ThirdJohn = ("3jo", "3 John")
    Jude = ("jd", "Jude")
    Revelation = ("re", "Revelation")

    # --- Catholic Deuterocanon ---
    Tobit = ("tb", "Tobit")
    Judith = ("jdt", "Judith")
    Wisdom = ("ws", "Wisdom")
    Sirach = ("sir", "Sirach")
    Baruch = ("bar", "Baruch")
    FirstMaccabees = ("1mc", "1 Maccabees")
    SecondMaccabees = ("2mc", "2 Maccabees")
    EstherAdditions = ("etg", "Esther (Greek)")
    DanielSongOfThree = ("dn3", "Daniel (Song of Three)")
    DanielSusanna = ("dns", "Daniel (Susanna)")
    DanielBelAndTheDragon = ("dnb", "Daniel (Bel and the Dragon)")

    # --- Eastern Orthodox Additions (Anagignoskomena) ---
    FirstEsdras = ("1es", "1 Esdras")
    SecondEsdras = ("2es", "2 Esdras")
    PrayerOfManasseh = ("pmn", "Prayer of Manasseh")
    Psalm151 = ("ps151", "Psalm 151")
    ThirdMaccabees = ("3mc", "3 Maccabees")
    FourthMaccabees = ("4mc", "4 Maccabees")

    @property
    def full_name(self) -> str:
        """Return the standard English name for the Bible book.

        Returns:
            str: The full name associated with the enumeration member.
        """
        return self.value[1]

    def as_str(self) -> str:
        """Return the compact abbreviation for the Bible book.

        Returns:
            str: The short abbreviation (e.g., "gn", "jdt", "ps151").
        """
        return self.value[0]

    def __str__(self) -> str:
        """Return the abbreviation string representation.

        Returns:
            str: The short abbreviation used as the canonical string form.
        """
        return self.as_str()

    @classmethod
    def from_str(cls, s: str) -> "BibleBookEnum":
        """Create an enum member from a compact abbreviation.

        Args:
            s (str): The case-insensitive abbreviation to resolve.

        Returns:
            BibleBookEnum: The enumeration member matching the abbreviation.

        Raises:
            ParseBibleBookError: If ``s`` is not a known Bible book abbreviation.
        """
        if not isinstance(s, str) or not s:
            raise ParseBibleBookError()
        key = s.lower()
        try:
            return _ABBR_TO_BOOK[key]
        except KeyError as e:
            raise ParseBibleBookError() from e


# Build a fast lookup (once) after the Enum is defined
_ABBR_TO_BOOK: Dict[str, BibleBookEnum] = {b.as_str(): b for b in BibleBookEnum}
