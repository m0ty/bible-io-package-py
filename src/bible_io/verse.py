

class Verse:
    def __init__(self, book_number: int, chapter_number: int, verse_number: int, text: str):
        self.book_number = book_number
        self.chapter_number = chapter_number
        self.verse_number = verse_number
        self.text = text

    def __repr__(self):
        return f"Verse({self.book_number}:{self.chapter_number}:{self.verse_number}) -> {self.text}"

    def contains_word(self, word: str) -> bool:
        """Check if the verse contains a given word (case-insensitive)."""
        return word.lower() in self.text.lower()
