"""Generic RTL text normalization utility for Persian and Arabic text.

Handles Arabic text as found in Telegram channel exports.

Responsibilities:
  - Strip Telegram-specific artifacts (channel @mentions embedded in footer)
  - Normalize Unicode: ZWNJ, ZWSP, directional marks, composite chars
  - Collapse whitespace, remove redundant newlines
  - Separate emoji from substantive text (return both)
  - Detect language heuristically (no ML dependency)
  - Extract inline links, hashtags, @mentions from entity lists

No external NLP dependencies required -- stdlib + unicodedata only.
Heavy NLP (hazm, parsivar) is optional; see ``hazm_normalize()`` for an
opt-in integration point.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Unicode constants for Persian/Arabic normalization
# ---------------------------------------------------------------------------
ZWNJ = "\u200c"  # Zero-Width Non-Joiner (common in Persian)
ZWJ = "\u200d"  # Zero-Width Joiner
ZWSP = "\u200b"  # Zero-Width Space
LRM = "\u200e"  # Left-to-Right Mark
RLM = "\u200f"  # Right-to-Left Mark
LRE = "\u202a"
RLE = "\u202b"
PDF = "\u202c"
LRO = "\u202d"
RLO = "\u202e"

DIRECTIONAL_MARKS = {ZWNJ, ZWJ, ZWSP, LRM, RLM, LRE, RLE, PDF, LRO, RLO}

# Persian Arabic numeral maps (Eastern Arabic -> Western)
EASTERN_ARABIC_DIGITS = str.maketrans(
    "\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669", "0123456789"
)
ARABIC_DIGITS = str.maketrans(
    "\u06f0\u06f1\u06f2\u06f3\u06f4\u06f5\u06f6\u06f7\u06f8\u06f9", "0123456789"
)

# Common Arabic -> Persian char substitutions
ARABIC_TO_PERSIAN = str.maketrans(
    "\u0643\u064a\u0649",  # Arabic
    "\u06a9\u06cc\u06cc",  # Persian
)

# Emoji range detector
_EMOJI_RE = re.compile(
    "["
    "\U0001f600-\U0001f64f"  # emoticons
    "\U0001f300-\U0001f5ff"  # symbols & pictographs
    "\U0001f680-\U0001f6ff"  # transport & map
    "\U0001f1e0-\U0001f1ff"  # flags
    "\U00002702-\U000027b0"
    "\U000024c2-\U0001f251"
    "\U0001f900-\U0001f9ff"  # supplemental symbols
    "\U0001fa00-\U0001fa6f"
    "\U0001fa70-\U0001faff"
    "\U00002600-\U000026ff"  # misc symbols
    "]+",
    flags=re.UNICODE,
)

# Telegram footer patterns to strip
_TG_FOOTER_RE = re.compile(
    r"(@\w+\s*[-\u2013\u2014]\s*Link\s*$|@\w+\s*$)",
    re.MULTILINE | re.UNICODE,
)

# Hashtag and mention patterns
_HASHTAG_RE = re.compile(r"#[\w\u0600-\u06FF\u0750-\u077F]+", re.UNICODE)
_MENTION_RE = re.compile(r"@[\w\u0600-\u06FF]+", re.UNICODE)


@dataclass
class NormalizationResult:
    """Result of RTL text normalization."""

    text_clean: str
    text_raw: str
    emojis_found: list[str] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
    mentions: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    is_rtl: bool = True
    language_hint: str = "unknown"  # "fa" | "ar" | "en" | "mixed" | "unknown"


def normalize(
    text: str,
    strip_emojis: bool = True,
    normalize_digits: bool = True,
    strip_tg_footer: bool = True,
    preserve_zwnj: bool = True,
    links: list[str] | None = None,
    use_hazm: bool = False,
) -> NormalizationResult:
    """Main normalization entry point.

    Args:
        text:             Input text (already flattened to str)
        strip_emojis:     Remove emoji characters from clean output
        normalize_digits: Convert Eastern/Arabic digits to Western (0-9)
        strip_tg_footer:  Remove Telegram @channel - Link footers
        preserve_zwnj:    Keep ZWNJ (needed for correct Persian rendering)
        links:            Optional pre-extracted links from text_entities
        use_hazm:         If True, apply hazm normalization as a final step
                          (requires ``hazm`` to be installed; silently skipped
                          if the library is unavailable)

    Returns:
        NormalizationResult with clean text and extracted metadata
    """
    raw = text

    # 1. Extract metadata before stripping
    hashtags = _HASHTAG_RE.findall(text)
    mentions = _MENTION_RE.findall(text)
    emojis = _EMOJI_RE.findall(text)

    # 2. Strip Telegram footer noise
    if strip_tg_footer:
        text = _TG_FOOTER_RE.sub("", text)

    # 3. Remove directional marks (selectively keep ZWNJ for Persian)
    marks_to_remove = DIRECTIONAL_MARKS - ({ZWNJ} if preserve_zwnj else set())
    for mark in marks_to_remove:
        text = text.replace(mark, "")

    # 4. Arabic -> Persian char substitution
    text = text.translate(ARABIC_TO_PERSIAN)

    # 5. Digit normalization
    if normalize_digits:
        text = text.translate(EASTERN_ARABIC_DIGITS)
        text = text.translate(ARABIC_DIGITS)

    # 6. Strip or preserve emoji
    if strip_emojis:
        text = _EMOJI_RE.sub(" ", text)

    # 7. Unicode normalization (NFC)
    text = unicodedata.normalize("NFC", text)

    # 8. Collapse whitespace
    text = re.sub(r"[^\S\n]+", " ", text)  # horizontal whitespace -> single space
    text = re.sub(r"\n{3,}", "\n\n", text)  # triple+ newlines -> double
    text = text.strip()

    # 9. Optional hazm normalization
    if use_hazm:
        text = hazm_normalize(text)

    return NormalizationResult(
        text_raw=raw,
        text_clean=text,
        emojis_found=list(set(emojis)),
        hashtags=hashtags,
        mentions=mentions,
        links=links or [],
        is_rtl=_is_predominantly_rtl(text),
        language_hint=_detect_language_hint(text),
    )


def _is_predominantly_rtl(text: str) -> bool:
    """Heuristic: count RTL vs LTR characters.

    Persian/Arabic Unicode blocks: 0x0600-0x06FF, 0x0750-0x077F.
    """
    rtl = sum(1 for c in text if ("\u0600" <= c <= "\u06ff") or ("\u0750" <= c <= "\u077f"))
    ltr = sum(1 for c in text if c.isalpha() and c.isascii())
    if rtl + ltr == 0:
        return True  # default to RTL for this corpus
    return rtl >= ltr


def _detect_language_hint(text: str) -> str:
    """Lightweight language heuristic -- no ML.

    Returns "fa" | "ar" | "en" | "mixed" | "unknown".
    """
    persian_chars = sum(1 for c in text if "\u0600" <= c <= "\u06ff" or "\u0750" <= c <= "\u077f")
    ascii_alpha = sum(1 for c in text if c.isalpha() and c.isascii())
    total_alpha = persian_chars + ascii_alpha

    if total_alpha == 0:
        return "unknown"

    persian_ratio = persian_chars / total_alpha
    ascii_ratio = ascii_alpha / total_alpha

    if persian_ratio > 0.7:
        # Could be Farsi or Arabic -- distinguish by specific chars
        fa_specific = sum(1 for c in text if c in "\u0698\u067e\u0686\u06af")
        ar_specific = sum(1 for c in text if c in "\u0636\u0638\u062b")
        if fa_specific >= ar_specific:
            return "fa"
        return "ar"
    if ascii_ratio > 0.7:
        return "en"
    if persian_ratio > 0.2 and ascii_ratio > 0.2:
        return "mixed"
    return "unknown"


def extract_links_from_entities(entities: list[dict]) -> list[str]:
    """Extract href values from Telegram text_entities of type 'text_link'.

    Compatible with both raw dict and TextEntity model.
    """
    links: list[str] = []
    for e in entities:
        href = e.get("href") if isinstance(e, dict) else getattr(e, "href", None)
        etype = e.get("type") if isinstance(e, dict) else getattr(e, "type", "")
        if etype == "text_link" and href:
            links.append(href)
    return links


def hazm_normalize(text: str) -> str:
    """
    Optional heavy normalization using hazm (Persian NLP library).

    This is a public utility function that can be called directly or enabled
    via the ``use_hazm=True`` parameter in :func:`normalize`.  If hazm is not
    installed, the input text is returned unchanged.
    """
    try:
        from hazm import Normalizer as HazmNormalizer

        return HazmNormalizer().normalize(text)
    except ImportError:
        return text
