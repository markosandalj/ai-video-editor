from __future__ import annotations

from collections.abc import Iterator


def windowed_pairs(n: int, window: int = 5) -> Iterator[tuple[int, int]]:
    """
    Yield ``(i, j)`` index pairs for a bounded lookahead comparison.

    Each sentence ``i`` is paired with sentences ``i+1`` through
    ``min(i + window, n - 1)``.  This prevents comparing sentences
    that are far apart in the lecture (which would flag legitimate
    pedagogical recaps as duplicates).
    """
    for i in range(n):
        for j in range(i + 1, min(i + window + 1, n)):
            yield i, j
