"""
Unit tests for core.filters — keyword & coin matching logic.
"""

import pytest

from core.filters import MatchResult, matches_watchlist

COINS = ["btc", "eth", "sol", "avax"]
KEYWORDS = ["scam", "bug", "stuck", "failed", "drain", "exploit", "rug"]


class TestMatchesWatchlist:
    """Tests for the matches_watchlist function."""

    def test_match_coin_and_keyword(self):
        """Should match when text contains both a coin and a keyword."""
        result = matches_watchlist("BTC is a total scam!", COINS, KEYWORDS)
        assert result is not None
        assert "btc" in result.matched_coins
        assert "scam" in result.matched_keywords
        assert result.severity_score == 2

    def test_no_match_coin_only(self):
        """Should NOT match when only a coin is mentioned without a keyword."""
        result = matches_watchlist("I just bought some ETH today", COINS, KEYWORDS)
        assert result is None

    def test_no_match_keyword_only(self):
        """Should NOT match when only a keyword is mentioned without a coin."""
        result = matches_watchlist("This website is a total scam", COINS, KEYWORDS)
        assert result is None

    def test_no_match_empty_text(self):
        """Should return None for empty text."""
        assert matches_watchlist("", COINS, KEYWORDS) is None

    def test_no_match_none_lists(self):
        """Should return None when coin or keyword lists are empty."""
        assert matches_watchlist("BTC scam", [], KEYWORDS) is None
        assert matches_watchlist("BTC scam", COINS, []) is None

    def test_case_insensitive(self):
        """Matching should be case-insensitive."""
        result = matches_watchlist("ETH HAS A MAJOR BUG", COINS, KEYWORDS)
        assert result is not None
        assert "eth" in result.matched_coins
        assert "bug" in result.matched_keywords

    def test_word_boundary_prevents_partial_match(self):
        """Should NOT match partial words — 'the' should not match inside 'ethereum'."""
        coins_with_short = ["the", "sol"]
        result = matches_watchlist("ethereum is great", coins_with_short, KEYWORDS)
        # "the" is inside "ethereum" but word boundary should prevent match
        assert result is None

    def test_word_boundary_allows_exact_match(self):
        """Should match exact word occurrences with proper boundaries."""
        result = matches_watchlist("the sol network has a bug", COINS, KEYWORDS)
        assert result is not None
        assert "sol" in result.matched_coins
        assert "bug" in result.matched_keywords

    def test_multiple_coins_and_keywords(self):
        """Should capture all matched coins and keywords with correct severity."""
        result = matches_watchlist(
            "Both BTC and ETH have a bug, possible exploit detected!",
            COINS,
            KEYWORDS,
        )
        assert result is not None
        assert set(result.matched_coins) == {"btc", "eth"}
        assert set(result.matched_keywords) == {"bug", "exploit"}
        assert result.severity_score == 4  # 2 coins + 2 keywords

    def test_result_is_frozen_dataclass(self):
        """MatchResult should be immutable (frozen dataclass)."""
        result = matches_watchlist("SOL scam alert", COINS, KEYWORDS)
        assert result is not None
        with pytest.raises(AttributeError):
            result.severity_score = 999  # type: ignore[misc]

    def test_special_chars_in_coins(self):
        """Coins with special regex characters should be escaped properly."""
        special_coins = ["c++", "f#"]
        result = matches_watchlist("c++ is stuck", special_coins, KEYWORDS)
        assert result is not None
        assert "c++" in result.matched_coins

    def test_matched_lists_are_sorted(self):
        """Matched coins and keywords should be returned in sorted order."""
        result = matches_watchlist(
            "SOL ETH BTC all have bug and exploit and scam going on",
            COINS,
            KEYWORDS,
        )
        assert result is not None
        assert result.matched_coins == sorted(result.matched_coins)
        assert result.matched_keywords == sorted(result.matched_keywords)
