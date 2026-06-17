"""Safe keyword matching engine for CareerSignal HH scoring.

Provides:
  - word_boundary_match: match only at word boundaries (no substring false positives)
  - phrase_match: multi-word exact phrase matching
  - short_keyword_safeguard: keywords ≤3 chars match only as whole tokens
  - field_aware_match: title vs description distinction
"""

from __future__ import annotations

import re
from typing import Any

from .utils import normalize_text

# Characters treated as word delimiters
_WORD_SEP = re.compile(r"[^a-zа-яё0-9]+")

# Common short keywords that must match as whole tokens
_SHORT_KEYWORDS = {"ai", "api", "crm", "qa", "ml", "dl", "ui", "ux", "db", "saas", "paas"}

_MIN_SAFE_LENGTH = 4  # Keywords with length > this can use substring match


def tokenize(text: str) -> list[str]:
    """Split normalized text into lowercase word tokens."""
    return [t for t in _WORD_SEP.split(normalize_text(text)) if t]


def word_boundary_match(keyword: str, text: str) -> bool:
    """Match keyword only at word boundaries.

    For keywords of length ≤ 3, require exact token match.
    For keywords of length ≥ 4, also allow substring at word boundaries.
    """
    nk = normalize_text(keyword)
    nt = normalize_text(text)
    if not nk or not nt:
        return False

    # Multi-word phrase
    if " " in nk:
        return phrase_match(nk, nt)

    # Short keyword safeguard
    if len(nk) <= _MIN_SAFE_LENGTH and nk in _SHORT_KEYWORDS:
        return _exact_token_match(nk, nt)

    if len(nk) <= _MIN_SAFE_LENGTH:
        return _exact_token_match(nk, nt)

    # For longer keywords, allow substring at word boundaries
    tokens = tokenize(nt)
    for token in tokens:
        if nk in token or token in nk:
            return True
        # Also match at start/end of longer tokens
        if token.startswith(nk) or token.endswith(nk):
            return True
    return False


def phrase_match(phrase: str, text: str) -> bool:
    """Match multi-word phrase exactly in text (word boundaries respected)."""
    np = normalize_text(phrase)
    nt = normalize_text(text)
    if not np or not nt:
        return False

    # Tokenize both
    p_tokens = tokenize(np)
    t_tokens = tokenize(nt)

    if not p_tokens:
        return False

    # Sliding window for exact token sequence match
    pl = len(p_tokens)
    for i in range(len(t_tokens) - pl + 1):
        if t_tokens[i : i + pl] == p_tokens:
            return True
    return False


def _exact_token_match(keyword: str, text: str) -> bool:
    """Keyword matches only if it appears as a whole token."""
    kw_tokens = tokenize(keyword)
    text_tokens = tokenize(text)
    return kw_tokens[0] in text_tokens if kw_tokens else False


def safe_keyword_match(
    keyword: str,
    text: str,
    *,
    allow_substring: bool = False,
) -> tuple[bool, str]:
    """Safe keyword matching with classification.

    Returns (matched, match_type) where match_type is one of:
      'exact_token'    — whole token match
      'word_boundary'  — substring at word boundary
      'phrase'         — multi-word exact phrase
      'none'           — no match

    When allow_substring=False (default), only exact_token or phrase matches
    are returned for short keywords.
    """
    nk = normalize_text(keyword)
    nt = normalize_text(text)
    if not nk or not nt:
        return False, "none"

    # Multi-word phrase
    if " " in nk:
        if phrase_match(nk, nt):
            return True, "phrase"
        return False, "none"

    # Short keyword safeguard
    if len(nk) <= _MIN_SAFE_LENGTH:
        if _exact_token_match(nk, nt):
            return True, "exact_token"
        return False, "none"

    # Longer keyword
    tokens = tokenize(nt)
    for token in tokens:
        if nk == token:
            return True, "exact_token"
        if allow_substring and nk in token:
            return True, "word_boundary"

    # Substring at word boundaries (default for long keywords)
    if not allow_substring:
        for token in tokens:
            if nk in token or token in nk:
                return True, "word_boundary"

    return False, "none"


def match_in_fields(
    keyword: str,
    fields: dict[str, str],
    *,
    preferred_fields: list[str] | None = None,
    allow_substring: bool = False,
) -> list[dict[str, Any]]:
    """Find keyword matches across multiple fields.

    Returns list of {field, match_type, weight} dicts.
    If preferred_fields is given, those are checked first.
    """
    matched = []
    check_order = (preferred_fields or []) + [
        f for f in fields if f not in (preferred_fields or [])
    ]
    for fname in check_order:
        if fname not in fields:
            continue
        ok, match_type = safe_keyword_match(keyword, fields[fname], allow_substring=allow_substring)
        if ok:
            matched.append({"field": fname, "match_type": match_type, "keyword": keyword})
            if preferred_fields:
                break  # Stop at first preferred field match
    return matched
