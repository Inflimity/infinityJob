"""
Heuristic intent filtering for ginNews.

Translates text, scores intent based on combinations of crypto entities and 
problem/support words, and assigns categories without relying on AI APIs.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from deep_translator import GoogleTranslator
from deep_translator.exceptions import RequestError

logger = logging.getLogger(__name__)

# Core entity keywords (things users have issues with)
CRYPTO_ENTITIES = [
    "token", "wallet", "coin", "balance", "transaction", "tx", "smart contract", "blockchain"
]

# Action keywords
CRYPTO_ACTIONS = [
    "withdraw", "withdrawal", "swap", "swapping", "transfer", "sent", "received", 
    "deposit", "deposited", "bridge", "bridging", "staked", "staking", "unstake", 
    "unstaking", "claim", "claiming", "airdrop", "reward", "rewards", "connect", "connection"
]

# Problem / Support indicator keywords
PROBLEM_WORDS = [
    "error", "failed", "pending", "stuck", "missing", "lost", "display",
    "not showing", "not received", "not working", "can't swap", "can't withdraw",
    "can't deposit", "unable to", "cannot", "can't", "issue", "problem", "bug",
    "why", "how do I", "fix", "recover", "restore", "scam", "help", "anyone help",
    "please help", "support"
]

# Map keywords to categories
CATEGORY_MAP = {
    "wallet": ["wallet", "wallet connect", "balance", "connection", "connect"],
    "staking": ["stake", "staked", "staking", "unstake", "unstaking"],
    "swap": ["swap", "swapping", "can't swap"],
    "bridge": ["bridge", "bridging"],
    "transfer": ["withdraw", "withdrawal", "transfer", "sent", "received", "deposit", "deposited", "pending", "transaction"],
    "exchange": ["exchange"],
    "airdrop": ["airdrop", "claim", "claiming"],
    "rewards": ["reward", "rewards"],
    "scam": ["scam", "lost", "stolen", "drain", "drained"],
    "recovery": ["recover", "restore", "recovery", "seed phrase"]
}

@dataclass
class IntentMatch:
    original_text: str
    translated_text: str
    language: str
    matched_keywords: list[str]
    category: str
    summary_sentence: str


def detect_and_translate(text: str) -> tuple[str, str]:
    """
    Translates text to English if it is not.
    Returns (translated_text, source_language_code).
    Defaults to 'en' and original text if translation fails.
    """
    try:
        translator = GoogleTranslator(source='auto', target='en')
        translated = translator.translate(text)
        # deep-translator doesn't easily return the detected source lang in a single call with the translated string.
        # However, for simplicity, we assume if it changed, it was non-English.
        # Actually, deep-translator has `detect` but it takes an extra API call.
        # For speed, we just return the translated text and "auto".
        # If text == translated, we assume "en".
        lang = "en" if text.strip().lower() == translated.strip().lower() else "translated"
        return translated, lang
    except Exception as e:
        logger.debug(f"Translation failed: {e}")
        return text, "en"


def categorize_issue(text_lower: str) -> str:
    """Assigns the best matching category based on keywords present."""
    for category, keywords in CATEGORY_MAP.items():
        if any(re.search(rf"\b{re.escape(k)}\b", text_lower) for k in keywords):
            return category
    return "other"


def extract_summary(text: str, keywords: list[str]) -> str:
    """Extracts the sentence containing the most keywords to serve as a summary."""
    sentences = re.split(r'(?<=[.!?]) +', text.replace('\n', ' '))
    best_sentence = ""
    max_matches = -1
    
    for sentence in sentences:
        s_lower = sentence.lower()
        matches = sum(1 for k in keywords if k in s_lower)
        if matches > max_matches:
            max_matches = matches
            best_sentence = sentence

    return best_sentence.strip() if best_sentence else text.strip()


def analyze_intent(raw_text: str, watch_coins: list[str] = None, from_search: bool = False) -> Optional[IntentMatch]:
    """
    Analyzes the text to determine if it's a real user complaint/support request.
    Returns IntentMatch if it passes the heuristic filters, else None.
    
    If from_search=True (e.g. Twitter deep search), use a relaxed filter since
    the search query itself already pre-filtered for relevance.
    """
    if watch_coins is None:
        watch_coins = []
        
    translated_text, lang = detect_and_translate(raw_text)
    text_lower = translated_text.lower()
    
    # Include user's specific coins as valid entities
    dynamic_entities = CRYPTO_ENTITIES + watch_coins
    
    found_entities = [k for k in dynamic_entities if re.search(rf"\b{re.escape(k)}[a-z]*\b", text_lower)]
    found_actions = [k for k in CRYPTO_ACTIONS if re.search(rf"\b{re.escape(k)}[a-z]*\b", text_lower)]
    found_problems = [k for k in PROBLEM_WORDS if re.search(rf"\b{re.escape(k)}[a-z]*\b", text_lower)]
    
    all_matched = found_entities + found_actions + found_problems
    
    if from_search:
        # Relaxed mode: the search query already ensured relevance.
        # Just need at least 1 keyword match of any kind to pass.
        if len(all_matched) < 1:
            return None
    else:
        # Strict mode for Telegram/Discord/Reddit:
        # Must have at least one PROBLEM word, AND at least one ENTITY or ACTION word.
        # OR must have multiple PROBLEM words (e.g., "help me", "stuck").
        if not found_problems:
            return None
        if not (found_entities or found_actions) and len(found_problems) < 2:
            return None
        
    # We found a valid intent
    category = categorize_issue(text_lower)
    summary = extract_summary(translated_text, all_matched)
    
    return IntentMatch(
        original_text=raw_text,
        translated_text=translated_text,
        language=lang,
        matched_keywords=list(set(all_matched)),
        category=category,
        summary_sentence=summary
    )

