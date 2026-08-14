"""Immutable aggregate statistics for Bible content value objects."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VerseStats:
    """Aggregate text statistics for one verse."""

    word_count: int
    character_count: int
    average_word_length: float


@dataclass(frozen=True, slots=True)
class ChapterStats:
    """Aggregate statistics for one chapter."""

    verse_count: int
    total_words: int
    average_verse_length: int


@dataclass(frozen=True, slots=True)
class BookStats:
    """Aggregate statistics for one book."""

    chapter_count: int
    verse_count: int
    total_words: int
    average_verses_per_chapter: float
