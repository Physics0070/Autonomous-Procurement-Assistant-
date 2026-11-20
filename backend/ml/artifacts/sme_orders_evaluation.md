# Late delivery from order features: the team's 4,000-order file

`python -m ml.sme_orders_eval` on `ml/data/india/late_delivery_orders.csv` (4,000 orders, 14 suppliers,
13.8% late).

**Provenance is unverified.** The file was supplied as vendor data, but its arithmetic is perfectly consistent (dates, totals,
days late) and its order ids are sequential, which is typical of generated data. Treat every number below as measured on this
file only, and do not describe it as real-vendor evidence until its origin is confirmed.

## Split

Time-ordered. Train 01 Jan 2024 to 21 Apr 2025 (late rate 13.3%); test
21 Apr 2025 to 01 Oct 2025 (1,000 orders, late rate 15.3%). Only features known when
the order is placed are used.

## Result on the later period

| Scorer | ROC-AUC | PR-AUC |
|---|---:|---:|
| logistic regression | 0.709 | 0.352 |
| random forest | 0.711 | 0.336 |
| gradient boosting | 0.700 | 0.349 |
| baseline: supplier's prior late rate | 0.659 | 0.239 |
| baseline: urgent / short-lead rule | 0.631 | 0.228 |

For contrast, the same forest scored 0.713 ROC-AUC under a shuffled 5-fold split, so the later-period
figure is not being depressed by drift: this file's ceiling is about 0.71.

## What drives lateness here

- By priority: {'Normal': 0.117, 'Planned': 0.084, 'Urgent': 0.306}.
- By promised lead time (quartiles, shortest first): [0.237, 0.112, 0.095, 0.084].

## Reading it

Order features add a real but modest signal over the supplier's record alone. The data carries a lot of noise that no
model on these columns removes, so it does not support claims near 0.9. The shipped risk model (supplier history, USAID
SCMS) is unchanged.
