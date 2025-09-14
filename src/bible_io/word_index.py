

class WordIndex:
    def __init__(self, book_number: int, chapter_number: int, verse_number: int):
        self.book_number = book_number
        self.chapter_number = chapter_number
        self.verse_number = verse_number

    def __repr__(self):
        return f"WordIndex(Book {self.book_number}, Chapter {self.chapter_number}, Verse {self.verse_number})"
