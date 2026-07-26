"""
Keyword & coin filter engine.

Matches incoming message text against configurable watchlists using
word-boundary-aware regex to minimise false positives.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class MatchResult:
    """Result of a successful watchlist match."""

    matched_coins: list[str] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)
    severity_score: int = 0  # Total number of keyword + coin hits


def _build_pattern(terms: list[str]) -> re.Pattern[str] | None:
    """Build a compiled regex that matches any of the given terms at word boundaries."""
    if not terms:
        return None
    # Escape each term so special chars are treated literally, then join with |
    escaped = [re.escape(t.strip().lower()) for t in terms if t.strip()]
    if not escaped:
        return None

    # Build patterns with adaptive boundaries:
    # - For terms starting/ending with word chars, use \b
    # - For terms with non-word boundary chars (like c++, f#), use
    #   lookahead/lookbehind for whitespace or string edges
    parts = []
    for term in escaped:
        raw = re.sub(r"\\(.)", r"\1", term)  # un-escape to check chars
        left = r"\b" if raw[0].isalnum() or raw[0] == "_" else r"(?<!\S)"
        right = r"\b" if raw[-1].isalnum() or raw[-1] == "_" else r"(?!\S)"
        parts.append(f"{left}{term}{right}")

    pattern = "(" + "|".join(parts) + ")"
    return re.compile(pattern, re.IGNORECASE)


def matches_watchlist(
    text: str,
    coins: list[str],
    keywords: list[str],
) -> MatchResult | None:
    """
    Check if *text* mentions at least one coin AND at least one keyword.

    Returns a MatchResult with all matched terms and a severity score,
    or None if the text does not match the watchlist criteria.
    """
    if not text or not coins or not keywords:
        return None

    coin_pattern = _build_pattern(coins)
    keyword_pattern = _build_pattern(keywords)

    if coin_pattern is None or keyword_pattern is None:
        return None

    text_lower = text.lower()

    # Find all distinct coin matches
    coin_hits = list({m.group().lower() for m in coin_pattern.finditer(text_lower)})
    if not coin_hits:
        return None

    # Find all distinct keyword matches
    keyword_hits = list(
        {m.group().lower() for m in keyword_pattern.finditer(text_lower)}
    )
    if not keyword_hits:
        return None

    severity = len(coin_hits) + len(keyword_hits)

    return MatchResult(
        matched_coins=sorted(coin_hits),
        matched_keywords=sorted(keyword_hits),
        severity_score=severity,
    )
