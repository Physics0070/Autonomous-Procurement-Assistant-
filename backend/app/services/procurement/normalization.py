"""Product and unit normalization.

Layer 1 - deterministic: casing, punctuation, unit canonicalisation, abbreviations.
Layer 2 - fuzzy: RapidFuzz similarity for near-identical descriptions.
Layer 3 - AI: reserved for genuinely ambiguous pairs only (see matching.py).

The original value is always carried alongside the normalized one; nothing here
overwrites source data.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional

from rapidfuzz import fuzz

# ---------------------------------------------------------------------------
# Unit canonicalisation
# ---------------------------------------------------------------------------

# canonical -> accepted spellings (including regional-script forms)
UNIT_ALIASES: dict[str, tuple[str, ...]] = {
    "nos": ("no", "nos", "number", "numbers", "pc", "pcs", "piece", "pieces", "qty",
            "ea", "each", "unit", "units", "नग", "नंग"),
    "kg": ("kg", "kgs", "kilo", "kilos", "kilogram", "kilograms", "किलो", "किग्रा"),
    "g": ("g", "gm", "gms", "gram", "grams", "ग्राम"),
    "ton": ("ton", "tons", "tonne", "tonnes", "mt"),
    "l": ("l", "lt", "ltr", "ltrs", "litre", "litres", "liter", "liters", "लीटर"),
    "ml": ("ml", "mls", "millilitre", "millilitres", "milliliter"),
    "m": ("m", "mtr", "mtrs", "meter", "meters", "metre", "metres", "मीटर"),
    "mm": ("mm", "millimeter", "millimetre"),
    "cm": ("cm", "centimeter", "centimetre"),
    "ft": ("ft", "feet", "foot", "फुट"),
    # Canonical is "inch", not "in": "in" collides with the English preposition
    # and would be dropped as a stopword, taking the size with it.
    "inch": ("in", "inch", "inches", '"', "इंच", "इन्च"),
    "sqm": ("sqm", "sq m", "sq.m", "square meter", "square metre", "m2"),
    "sqft": ("sqft", "sq ft", "sq.ft", "square feet", "square foot", "ft2"),
    "box": ("box", "boxes", "bx", "carton", "cartons", "बॉक्स"),
    "bottle": ("bottle", "bottles", "btl", "btls", "बोतल"),
    "bag": ("bag", "bags", "बैग"),
    "roll": ("roll", "rolls"),
    "packet": ("packet", "packets", "pkt", "pkts", "pack", "packs"),
    "set": ("set", "sets"),
    "pair": ("pair", "pairs"),
    "dozen": ("dozen", "dozens", "dz"),
    "coil": ("coil", "coils"),
    "bundle": ("bundle", "bundles", "bdl"),
}

_UNIT_LOOKUP: dict[str, str] = {}
for canonical, aliases in UNIT_ALIASES.items():
    _UNIT_LOOKUP[canonical] = canonical
    for alias in aliases:
        _UNIT_LOOKUP[alias] = canonical

# Conversions into a base unit, used to compare quantities across suppliers.
UNIT_CONVERSIONS: dict[str, tuple[str, float]] = {
    "g": ("kg", 0.001),
    "kg": ("kg", 1.0),
    "ton": ("kg", 1000.0),
    "ml": ("l", 0.001),
    "l": ("l", 1.0),
    "mm": ("m", 0.001),
    "cm": ("m", 0.01),
    "m": ("m", 1.0),
    "ft": ("m", 0.3048),
    "inch": ("m", 0.0254),
    "dozen": ("nos", 12.0),
    "pair": ("nos", 2.0),
    "nos": ("nos", 1.0),
}

# ---------------------------------------------------------------------------
# Product term normalisation
# ---------------------------------------------------------------------------

# Domain abbreviations and regional-script equivalents folded to one spelling.
TERM_ALIASES: dict[str, str] = {
    "पाइप": "pipe", "पाईप": "pipe", "पइप": "pipe",
    "नल": "pipe",
    "कोहनी": "elbow",
    "सीमेंट": "cement",
    "टेप": "tape",
    "पीवीसी": "pvc",
    "pvcpipe": "pvc pipe",
    "gi": "galvanised iron",
    "g.i": "galvanised iron",
    "ms": "mild steel",
    "m.s": "mild steel",
    "ss": "stainless steel",
    "s.s": "stainless steel",
    "cpvc": "cpvc",
    "upvc": "upvc",
    "dia": "diameter",
    "thk": "thickness",
    "qty": "quantity",
    "approx": "approximate",
    "asst": "assorted",
    "hex": "hexagonal",
    "sq": "square",
    "galv": "galvanised",
    "galvanized": "galvanised",
    "grey": "gray",
    "colour": "color",
    "metre": "meter",
    "litre": "liter",
    "cls": "class",
}

# Words that add no discriminating value when comparing products.
STOPWORDS = {
    "of", "the", "a", "an", "for", "with", "and", "or", "in", "to",
    "make", "brand", "quality", "std", "standard", "type",
}

_KEEP_PUNCT = set(" \t\n\"'.-/")


def _strip_punctuation(text: str) -> str:
    """Remove punctuation while preserving letters, digits and combining marks.

    A plain \\w class drops Devanagari vowel signs (Unicode categories Mn/Mc),
    which silently shreds regional-language product names into fragments.
    """
    out = []
    for ch in text:
        if ch in _KEEP_PUNCT:
            out.append(ch)
            continue
        if unicodedata.category(ch)[0] in ("L", "N", "M"):
            out.append(ch)
        else:
            out.append(" ")
    return "".join(out)


_MULTISPACE_RE = re.compile(r"\s+")
# "2inch" / "500ml" / "6m" -> "2 inch" / "500 ml" / "6 m"
_NUM_UNIT_RE = re.compile(r"(\d)\s*([a-zA-Z\"]+)")
_INCH_MARK_RE = re.compile(r'(\d+(?:\.\d+)?)\s*"')
_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(mm|cm|m|inch|in|ft|kg|g|ml|l|nos)\b", re.IGNORECASE)


def normalize_unit(unit: Optional[str]) -> Optional[str]:
    """Map a written unit onto its canonical symbol, or None if unrecognised."""
    if not unit:
        return None
    cleaned = str(unit).strip().lower().strip(".:()[]")
    cleaned = _MULTISPACE_RE.sub(" ", cleaned)
    if not cleaned:
        return None
    return _UNIT_LOOKUP.get(cleaned) or _UNIT_LOOKUP.get(cleaned.rstrip("s"))


def convert_quantity(quantity: Optional[float], unit: Optional[str]) -> tuple[Optional[float], Optional[str]]:
    """Express a quantity in its base unit so suppliers can be compared."""
    if quantity is None:
        return None, normalize_unit(unit)
    canonical = normalize_unit(unit)
    if canonical is None:
        return quantity, None
    base, factor = UNIT_CONVERSIONS.get(canonical, (canonical, 1.0))
    return round(quantity * factor, 6), base


def normalize_text(value: Optional[str]) -> str:
    """Layer 1: deterministic string normalisation.

    Handles the variations the spec calls out - casing, spacing, punctuation,
    inch marks, glued number+unit pairs, abbreviations and regional script.
    """
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = text.lower()
    text = _INCH_MARK_RE.sub(r"\1 inch ", text)          # 2" -> 2 inch
    text = text.replace("×", "x").replace("–", "-").replace("—", "-")
    text = _strip_punctuation(text)
    text = text.replace("/", " ").replace("-", " ").replace(".", " ")
    text = _NUM_UNIT_RE.sub(r"\1 \2", text)              # 2inch -> 2 inch
    text = _MULTISPACE_RE.sub(" ", text).strip()

    tokens_out: list[str] = []
    for token in text.split():
        token = TERM_ALIASES.get(token, token)
        # Units are resolved before the stopword filter, otherwise short unit
        # spellings that double as English words are discarded.
        canonical_unit = _UNIT_LOOKUP.get(token)
        if canonical_unit:
            tokens_out.append(canonical_unit)
            continue
        if token in STOPWORDS:
            continue
        tokens_out.append(token)

    # Re-run alias folding: some aliases expand into multiple tokens.
    expanded: list[str] = []
    for token in tokens_out:
        expanded.extend(t for t in token.split() if t not in STOPWORDS)
    return " ".join(expanded).strip()


def normalize_tokens(value: Optional[str]) -> list[str]:
    """Sorted, de-duplicated tokens - an order-insensitive product signature."""
    normalized = normalize_text(value)
    if not normalized:
        return []
    return sorted(set(normalized.split()))


def extract_size_attributes(value: Optional[str]) -> dict[str, str]:
    """Pull dimensional facts out of a description.

    Size is the usual reason two similar-looking descriptions are different
    products, so it is captured separately and compared explicitly.
    """
    if not value:
        return {}
    normalized = normalize_text(value)
    sizes = {}
    for match in _SIZE_RE.finditer(normalized):
        amount, unit = match.group(1), normalize_unit(match.group(2)) or match.group(2)
        base_value, base_unit = convert_quantity(float(amount), unit)
        if base_unit:
            sizes.setdefault(base_unit, f"{base_value}{base_unit}")
    return sizes


# ---------------------------------------------------------------------------
# Layer 2: fuzzy similarity
# ---------------------------------------------------------------------------


def similarity(left: Optional[str], right: Optional[str]) -> float:
    """Similarity in 0..1 between two product descriptions.

    Blends several RapidFuzz scorers because supplier descriptions differ in
    word order, abbreviation and padding, and no single scorer handles all three.
    """
    a, b = normalize_text(left), normalize_text(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0

    token_sort = fuzz.token_sort_ratio(a, b) / 100.0
    token_set = fuzz.token_set_ratio(a, b) / 100.0
    partial = fuzz.partial_ratio(a, b) / 100.0
    plain = fuzz.ratio(a, b) / 100.0

    score = max(token_sort, token_set) * 0.6 + partial * 0.2 + plain * 0.2

    # Contradictory dimensions mean different products, whatever the string
    # similarity says. This is what stops "2 inch" matching "3 inch".
    left_sizes, right_sizes = extract_size_attributes(left), extract_size_attributes(right)
    shared = set(left_sizes) & set(right_sizes)
    if shared:
        if any(left_sizes[u] != right_sizes[u] for u in shared):
            score *= 0.45
        else:
            score = min(1.0, score + 0.05)
    return round(min(score, 1.0), 4)


def best_match(
    target: str, candidates: Iterable[tuple[str, str]]
) -> tuple[Optional[str], Optional[str], float]:
    """Return (candidate_id, candidate_name, score) for the closest candidate."""
    best_id: Optional[str] = None
    best_name: Optional[str] = None
    best_score = 0.0
    for candidate_id, candidate_name in candidates:
        score = similarity(target, candidate_name)
        if score > best_score:
            best_id, best_name, best_score = candidate_id, candidate_name, score
    return best_id, best_name, best_score

