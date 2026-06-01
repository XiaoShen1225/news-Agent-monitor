"""Shared utility functions used across the project."""

import difflib


def title_similar(a: str, b: str, threshold: float = 0.85) -> bool:
    """Check if two title strings refer to the same underlying item.

    Uses difflib.SequenceMatcher (stdlib) to catch minor variations
    like truncation, punctuation, or whitespace differences.
    """
    if not a or not b:
        return False
    a_norm = a.strip()
    b_norm = b.strip()
    if a_norm == b_norm:
        return True
    return difflib.SequenceMatcher(None, a_norm, b_norm).ratio() >= threshold
