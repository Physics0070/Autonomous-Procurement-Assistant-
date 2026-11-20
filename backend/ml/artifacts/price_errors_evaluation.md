# Price errors: how well wrong quoted prices are caught

`python -m ml.price_errors_eval` on the team's labelled file (`ml/data/india/price_history.csv`, `price_quotes_labelled.csv`).
The history (468 purchases, 2024-01 to 2026-03) ends before the first quote (2026-05), so only the past is used. Items have
9 to 24 past prices. **The errors were injected on purpose and the data's origin is
unverified: read the numbers as "on this file", not as field accuracy.**

Rule: a price is POSSIBLE when it is at least 2.7 standard deviations (of that item's past log prices) from their centre, HIGH at
5.0 or more, or when it is at least 2.7 out and the Isolation Forest also isolates it. The detector judges from 8
past prices. 2.7 was chosen on the first 150 quotes by date; the later quotes were not used for any choice.

| Quotes | n | Precision (any flag) | Recall (any flag) | Precision (HIGH) | Recall (HIGH) | Correct quotes flagged |
|---|---|---:|---:|---:|---:|---|
| Later quotes (untouched test) | 150 (39 wrong) | 0.75 | 1.00 | 0.83 | 0.90 | 13 of 111 |
| All quotes (includes the tuning half) | 300 (76 wrong) | 0.76 | 0.95 | 0.85 | 0.87 | 23 of 224 |

Before this change the detector (Isolation Forest percentile cut-offs, judging only from 20 past prices) scored on the same
300 quotes: any flag precision 0.47 / recall 0.96 (81 of 224 correct quotes flagged); HIGH precision 0.73 / recall 0.86; and it
could not judge the 57 quotes whose item had fewer than 20 past prices.

## Share of wrong quotes caught, by kind of error

| Error | Wrong quotes | Flagged |
|---|---:|---:|
| currency_mixup | 8 | 100% |
| decimal_shift | 12 | 100% |
| digit_transposition | 8 | 75% |
| gst_added_twice | 10 | 80% |
| overcharge | 16 | 100% |
| suspiciously_low | 8 | 100% |
| unit_mismatch | 14 | 100% |

## Real data check

On 10,120 real SCMS prices (leave-one-out, the 48 products with 8 or more prices; `analytics_evaluation.md`) the same rule flags 1.1% as
POSSIBLE and 0.5% as HIGH, against 9.3% and 1.8% for the old percentile cut-offs (which judged only the products with 20 or more
prices). SCMS has no error labels, so this shows fewer false alarms but says nothing about missed errors on real data.
