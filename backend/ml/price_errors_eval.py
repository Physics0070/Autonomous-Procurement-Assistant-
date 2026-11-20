"""How well does the price-anomaly detector catch wrong quoted prices?

Uses the team's labelled file: 468 past purchases (the history) and 300 later quotes, 76 of them wrong.
The history ends before the first quote, so the detector only ever sees the past.

Usage (from backend/):  python -m ml.price_errors_eval      Writes ml/artifacts/price_errors_evaluation.md
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import precision_score, recall_score

from ml.anomaly import HIGH_Z, MIN_SAMPLES, POSSIBLE_Z, assess_price

DATA = Path(__file__).resolve().parent / "data" / "india"
REPORT = Path(__file__).resolve().parent / "artifacts" / "price_errors_evaluation.md"
TUNING_QUOTES = 150  # the first quotes by date chose POSSIBLE_Z; the rest are the untouched test


def evaluate() -> dict:
    history = pd.read_csv(DATA / "price_history.csv")
    quotes = pd.read_csv(DATA / "price_quotes_labelled.csv", parse_dates=["quote_date"]).sort_values("quote_date").reset_index(drop=True)
    past = {key: group["unit_price_inr"].to_numpy() for key, group in history.groupby("item_key")}
    results = [assess_price(row.quoted_unit_price_inr, past[row.item_key]) for row in quotes.itertuples()]
    quotes["flag"] = [int(r is not None and r["status"] != "NORMAL") for r in results]
    quotes["high"] = [int(r is not None and r["status"] == "HIGH_ANOMALY") for r in results]

    def scores(frame: pd.DataFrame) -> dict:
        y = frame["is_wrong"]
        return {"n": len(frame), "wrong": int(y.sum()),
                "any": (precision_score(y, frame["flag"]), recall_score(y, frame["flag"])),
                "high": (precision_score(y, frame["high"]), recall_score(y, frame["high"])),
                "false_alarms": int(((frame["flag"] == 1) & (y == 0)).sum()), "correct": int((y == 0).sum())}

    wrong = quotes[quotes["is_wrong"] == 1]
    return {"test": scores(quotes.iloc[TUNING_QUOTES:]), "all": scores(quotes),
            "by_type": wrong.groupby("error_type")["flag"].agg(["mean", "count"]).round(2),
            "history_sizes": sorted(set(history.groupby("item_key").size()))}


def report(r: dict) -> str:
    def row(name: str, s: dict) -> str:
        return (f"| {name} | {s['n']} ({s['wrong']} wrong) | {s['any'][0]:.2f} | {s['any'][1]:.2f} | {s['high'][0]:.2f} | "
                f"{s['high'][1]:.2f} | {s['false_alarms']} of {s['correct']} |")

    types = "\n".join(f"| {t} | {int(v['count'])} | {v['mean']:.0%} |" for t, v in r["by_type"].iterrows())
    return f"""# Price errors: how well wrong quoted prices are caught

`python -m ml.price_errors_eval` on the team's labelled file (`ml/data/india/price_history.csv`, `price_quotes_labelled.csv`).
The history (468 purchases, 2024-01 to 2026-03) ends before the first quote (2026-05), so only the past is used. Items have
{r['history_sizes'][0]} to {r['history_sizes'][-1]} past prices. **Supplied by the team as real vendor data; I have not verified the source independently. The numbers are measured on this
file only, and the labels of which quotes were wrong come from the team.**

Rule: a price is POSSIBLE when it is at least {POSSIBLE_Z} standard deviations (of that item's past log prices) from their centre, HIGH at
{HIGH_Z} or more, or when it is at least {POSSIBLE_Z} out and the Isolation Forest also isolates it. The detector judges from {MIN_SAMPLES}
past prices. {POSSIBLE_Z} was chosen on the first {TUNING_QUOTES} quotes by date; the later quotes were not used for any choice.

| Quotes | n | Precision (any flag) | Recall (any flag) | Precision (HIGH) | Recall (HIGH) | Correct quotes flagged |
|---|---|---:|---:|---:|---:|---|
{row('Later quotes (untouched test)', r['test'])}
{row('All quotes (includes the tuning half)', r['all'])}

Before this change the detector (Isolation Forest percentile cut-offs, judging only from 20 past prices) scored on the same
300 quotes: any flag precision 0.47 / recall 0.96 (81 of 224 correct quotes flagged); HIGH precision 0.73 / recall 0.86; and it
could not judge the 57 quotes whose item had fewer than 20 past prices.

## Share of wrong quotes caught, by kind of error

| Error | Wrong quotes | Flagged |
|---|---:|---:|
{types}

## Real data check

On 10,120 real SCMS prices (leave-one-out, the 48 products with 8 or more prices; `analytics_evaluation.md`) the same rule flags 1.1% as
POSSIBLE and 0.5% as HIGH, against 9.3% and 1.8% for the old percentile cut-offs (which judged only the products with 20 or more
prices). SCMS has no error labels, so this shows fewer false alarms but says nothing about missed errors on real data.
"""


def main() -> int:
    result = evaluate()
    REPORT.write_text(report(result), encoding="utf-8")
    t = result["test"]
    print(f"later quotes: any flag precision {t['any'][0]:.2f} recall {t['any'][1]:.2f}; HIGH precision {t['high'][0]:.2f} recall {t['high'][1]:.2f}")
    print(f"Report written to {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
