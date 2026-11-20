"""Suggest the HSN heading for a quotation line, from the official GST HSN master.

Indian GST invoices must carry an HSN code, and SMEs often get it wrong. Quotations say
"MS Plate 10mm IS 2062"; the master says "FLAT-ROLLED PRODUCTS OF IRON OR NON-ALLOY STEEL".

Two stages:
  1. text matching - every heading becomes one document holding all its official text
     (the detailed rows too: the GST portal file has at least one wrong heading text,
     8539 carries 8538's, while the rows beneath it are right). Trade shorthand is
     expanded first. This alone is weak (see the evaluation report), but it is a good
     shortlist.
  2. a language model reads the item and the shortlist's official descriptions and
     picks one - or names a heading it knows that the shortlist missed. Whatever it
     answers must exist in the official master, so it cannot invent a code.

Usage (from backend/):  python -m ml.hsn [dev|test] [--llm]
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
from scipy.sparse import hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

DATA_DIR = Path(__file__).resolve().parent / "data" / "india"
MASTER_PATH = DATA_DIR / "HSN_SAC.xlsx"
BENCHMARK_PATH = DATA_DIR / "hsn_benchmark.csv"
LABELLED_PATH = DATA_DIR / "hsn_labelled.csv"  # 750 items with their 4-digit heading, supplied by the team
NEAR_ENOUGH = 0.4  # measured on 100 held-out items: at or above this the closest labelled item is right 60% of the time
REPORT_PATH = Path(__file__).resolve().parent / "artifacts" / "hsn_evaluation.md"
SHORTLIST_SIZE = 30
EVAL_PACE_SECONDS = 5.0  # pause between model calls in evaluate(); free tiers allow ~15 requests/minute

# Standard Indian trade shorthand -> the wording the HSN master uses. General vocabulary
# of Indian purchasing, not tuned to individual benchmark items.
ABBREVIATIONS = {
    "ms": "iron non-alloy steel", "mild steel": "iron non-alloy steel",
    "gi": "galvanised zinc coated iron non-alloy steel", "ss": "stainless steel",
    "cr": "cold-rolled", "hr": "hot-rolled", "tmt": "bars rods iron non-alloy steel",
    "erw": "welded tubes pipes", "ci": "cast iron", "ht": "high tensile",
    "pvc": "polyvinyl chloride plastics", "hdpe": "polyethylene plastics", "ldpe": "polymers of ethylene",
    "pp": "polymers of propylene", "opc": "portland cement", "bwr": "plywood",
    "mcb": "automatic circuit breakers", "led": "light-emitting diode lamps", "hss": "tools high speed steel",
    "sqmm": "insulated electric conductors cable", "ro": "water filtering purifying",
    "cctv": "television cameras", "dg": "generating sets", "sae": "lubricating oils petroleum",
    "ctc": "tea", "atta": "wheat flour", "dal": "dried leguminous vegetables", "toor": "pigeon peas",
    "almirah": "metal furniture", "gunny": "sacks bags", "emery": "abrasive",
}
_UNITS = re.compile(r"\b\d+(\.\d+)?\s*(mm|cm|m|inch|in|kg|g|l|ltr|ml|gsm|hp|kva|kw|w|a|v|ah|bar|ton|ply|nos?)\b")
_NUMBERS = re.compile(r"(?<![a-z])\d[\d.,x/%-]*")  # tokens that start with a digit; keeps "non-alloy"

HSN_SYSTEM = (
    "You classify goods for Indian GST. Given an item as a buyer wrote it and a shortlist of official HSN "
    "headings, reply with JSON only: {\"heading\": \"<4 digits>\", \"confidence\": <0-1>, \"reason\": \"...\"}. "
    "Pick the shortlist heading that fits the goods themselves (material, form, function). If none fits and "
    "you know the correct 4-digit heading, give that instead. Never guess a code you are unsure exists."
)


def normalize_item(text: str) -> str:
    """Lowercase, expand trade abbreviations, drop sizes and numbers that only add noise."""
    text = _UNITS.sub(" ", (text or "").lower())
    joined = " ".join(ABBREVIATIONS.get(word, word) for word in re.findall(r"[a-z]+", text))
    for phrase, expansion in ABBREVIATIONS.items():  # multi-word shorthand ("mild steel")
        if " " in phrase and phrase in joined:
            joined = joined.replace(phrase, expansion)
    return _NUMBERS.sub(" ", joined)


@dataclass
class HsnIndex:
    headings: list[str]
    matrix: Any
    char_vectorizer: TfidfVectorizer
    word_vectorizer: TfidfVectorizer
    heading_text: dict[str, str]

    @classmethod
    @lru_cache(maxsize=1)
    def load(cls, path: Path = MASTER_PATH) -> "HsnIndex":
        master = pd.read_excel(path, sheet_name="HSN_MSTR", dtype=str).dropna()
        master["HSN_CD"] = master["HSN_CD"].str.strip()
        master = master[master["HSN_CD"].str.len() >= 4]
        master["heading"] = master["HSN_CD"].str[:4]
        # Newer rows repeat the hierarchy joined by "~"; one de-duplicated document per heading.
        text = master["HSN_Description"].str.replace("~", " ", regex=False).str.lower()
        docs = text.groupby(master["heading"]).apply(lambda parts: " ".join(dict.fromkeys(parts)))
        char_vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, min_df=2)
        word_vectorizer = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), sublinear_tf=True, stop_words="english")
        matrix = normalize(hstack([char_vectorizer.fit_transform(docs), word_vectorizer.fit_transform(docs)]).tocsr())
        four = master[master["HSN_CD"].str.len() == 4]
        return cls(headings=docs.index.tolist(), matrix=matrix, char_vectorizer=char_vectorizer,
                   word_vectorizer=word_vectorizer, heading_text=dict(zip(four["HSN_CD"], four["HSN_Description"])))

    @property
    def heading_count(self) -> int:
        return len(self.heading_text)

    def describe(self, heading: str) -> str:
        return self.heading_text.get(heading, "")

    def exists(self, heading: str) -> bool:
        return heading in self.heading_text

    def suggest(self, item: str, k: int = 3) -> list[dict]:
        query = normalize_item(item)
        vector = normalize(hstack([self.char_vectorizer.transform([query]),
                                   self.word_vectorizer.transform([query])]).tocsr())
        scores = (self.matrix @ vector.T).toarray().ravel()
        return [{"heading": self.headings[i], "score": round(float(scores[i]), 4),
                 "description": self.describe(self.headings[i])} for i in np.argsort(-scores)[:k]]


@dataclass
class Examples:
    """Items already labelled with their heading. Used as the answer when no model is available. (Showing them to the
    model was tried and did not help: 94.0% without, 92.0% with, on the same 100 held-out items.)"""

    items: list[str]
    headings: list[str]
    vectorizer: TfidfVectorizer
    matrix: Any

    @classmethod
    def load(cls, path: Path = LABELLED_PATH, exclude: Optional[set[str]] = None) -> "Optional[Examples]":
        if not Path(path).is_file():
            return None
        frame = pd.read_csv(path, dtype={"heading": str})
        frame["heading"] = frame["heading"].str.zfill(4)
        if exclude:  # an evaluation must not see its own test items
            frame = frame[~frame["item"].str.lower().str.strip().isin(exclude)]
        vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
        names = [normalize_item(i) for i in frame["item"]]
        return cls(frame["item"].tolist(), frame["heading"].tolist(), vectorizer,
                   normalize(vectorizer.fit_transform(names)))

    def nearest(self, item: str, k: int = 1) -> list[dict]:
        scores = (self.matrix @ normalize(self.vectorizer.transform([normalize_item(item)])).T).toarray().ravel()
        return [{"item": self.items[i], "heading": self.headings[i], "score": round(float(scores[i]), 3)}
                for i in np.argsort(-scores)[:k] if scores[i] > 0]


def _because(fallback: dict, reason: str) -> str:
    """Why the model was not used, plus how the fallback guess was made."""
    return f"{reason} {fallback['note']}" if fallback.get("note") else f"{reason} Text match used."


@lru_cache(maxsize=1)
def _default_examples() -> "Optional[Examples]":
    return Examples.load()


async def classify_hsn(item: str, provider=None, *, index: Optional[HsnIndex] = None,
                       examples: "Optional[Examples] | bool" = True) -> dict:
    """Best HSN heading for an item: the model's checked choice, else the closest labelled item, else the top text match.

    `examples=True` uses the bundled labelled items, an Examples object uses those, False turns them off.
    """
    index = index or HsnIndex.load()
    shortlist = index.suggest(item, k=SHORTLIST_SIZE)
    fallback = {**shortlist[0], "method": "text_match", "confidence": None}
    pool = _default_examples() if examples is True else (examples or None)
    near = pool.nearest(item, 1) if pool else []
    if near and near[0]["score"] >= NEAR_ENOUGH and index.exists(near[0]["heading"]):
        # No model needed: a close, already-labelled item is a better guess than text matching alone.
        fallback = {"heading": near[0]["heading"], "score": near[0]["score"], "description": index.describe(near[0]["heading"]),
                    "method": "similar_item", "confidence": None, "note": f"Same heading as \"{near[0]['item']}\"."}

    if provider is None or not provider.is_configured():
        reason = provider.configuration_error() if provider is not None else "no model configured"
        return {**fallback, "note": _because(fallback, f"No model ({reason}).")}

    options = "\n".join(f"{s['heading']}: {s['description'][:160]}" for s in shortlist)
    response = await provider.generate(f"Item: {item}\n\nShortlist:\n{options}", system=HSN_SYSTEM,
                                       json_mode=True, temperature=0.0, max_output_tokens=300)
    if not response.ok:
        return {**fallback, "note": _because(fallback, f"Model unavailable ({response.error}).")}
    try:
        answer = json.loads(response.text)
        heading = str(answer.get("heading", "")).strip()[:4]
    except (ValueError, TypeError, AttributeError):
        return {**fallback, "note": _because(fallback, "Model reply was not valid JSON.")}
    if not index.exists(heading):
        return {**fallback, "note": _because(fallback, f"Model named {heading or 'nothing'}, which is not an official heading.")}
    return {"heading": heading, "description": index.describe(heading), "method": "llm",
            "confidence": answer.get("confidence"), "note": str(answer.get("reason") or "")[:200],
            "in_shortlist": any(s["heading"] == heading for s in shortlist)}


async def evaluate(split: str, provider=None, index: Optional[HsnIndex] = None) -> dict:
    """Top-1 heading and chapter accuracy (plus shortlist recall) on one benchmark split."""
    index = index or HsnIndex.load()
    bench = pd.read_csv(BENCHMARK_PATH, dtype=str)
    bench = bench[bench["split"] == split]
    rows = []
    for item, truth in zip(bench["item"], bench["heading"]):
        result = await classify_hsn(item, provider, index=index)
        if provider is not None:
            await asyncio.sleep(EVAL_PACE_SECONDS)
        shortlist = [s["heading"] for s in index.suggest(item, k=SHORTLIST_SIZE)]
        rows.append({"item": item, "truth": truth, "predicted": result["heading"], "method": result["method"],
                     "correct": result["heading"] == truth, "chapter": result["heading"][:2] == truth[:2],
                     "top3": truth in shortlist[:3], "shortlisted": truth in shortlist})
    frame = pd.DataFrame(rows)
    return {"split": split, "items": len(frame), "methods": frame["method"].value_counts().to_dict(),
            "top1": float(frame["correct"].mean()), "chapter_top1": float(frame["chapter"].mean()),
            "text_top3": float(frame["top3"].mean()), "shortlist_recall": float(frame["shortlisted"].mean()),
            "misses": frame[~frame["correct"]][["item", "truth", "predicted"]].to_dict("records")}


def main(argv: Optional[list[str]] = None) -> int:
    import asyncio
    import sys

    args = sys.argv[1:] if argv is None else argv
    provider = None
    if "--llm" in args:
        from app.integrations.ai.factory import get_ai_provider
        provider = get_ai_provider("hsn")
    for split in [a for a in args if a in ("dev", "test")] or ["dev"]:
        r = asyncio.run(evaluate(split, provider))
        print(f"{split}: {r['items']} items via {r['methods']} | heading top-1 {r['top1']:.1%} | "
              f"chapter top-1 {r['chapter_top1']:.1%} | text top-3 {r['text_top3']:.1%} | "
              f"shortlist({SHORTLIST_SIZE}) recall {r['shortlist_recall']:.1%}")
        for miss in r["misses"]:
            print(f"   miss: {miss['item']!r} -> {miss['predicted']} (truth {miss['truth']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
