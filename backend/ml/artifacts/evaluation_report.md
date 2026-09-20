# Supplier late-delivery risk model

Model version `reliability-scms-20260920`, trained 2026-09-20T13:30:46+00:00 with scikit-learn
1.9.1. Selected model: **random_forest**.

## Dataset

- Source: USAID Supply Chain Management System (SCMS) Delivery History, 10,324 shipments
  (SHA-256 `918b992dd3e8d4b64d2a727b2c4ea607603d0c58f19484e73f7b78528c6a8673`); see `ml/data/README.md`.
- Label: late = delivered_date > scheduled_date.
- Training period (scheduled delivery date): 2006-05-02 to
  2013-12-31, 7,779 shipments, late rate
  10.67% (3,370 external-vendor shipments, late rate
  6.56%).
- Test period: 2014-01-03 to 2015-12-31,
  2,545 shipments, late rate 13.99%
  (1,550 external-vendor shipments, late rate 2.45%).
- Late rate by training year: 2006: 0.0%, 2007: 2.1%, 2008: 1.3%, 2009: 3.6%, 2010: 15.9%, 2011: 23.5%, 2012: 7.9%, 2013: 17.9%.
  By test year: 2014: 15.4% of 1,528, 2015: 11.8% of 1,017.
- "External vendors" means `Fulfill Via = Direct Drop`; the other shipments come from
  SCMS's own regional distribution centres (one supplier key, "SCMS from RDC").

## Leakage controls

- Time-ordered split: the model is fitted only on shipments scheduled up to
  2013 and evaluated on later ones.
- Each shipment's features use only the same supplier's shipments **delivered** before a
  knowledge cutoff of scheduled date minus 30 days, so outcomes that
  were not yet known are never used, and the shipment's own outcome never is.
- Features: `has_history`, `prior_count`, `prior_on_time_rate`, `prior_mean_delay_days`, `recent_late_rate`, `days_since_previous`, `log_order_value`, `log_quantity`, `shipment_mode`, `fulfil_via`.
  Excluded: actual and recorded delivery dates, freight and insurance (known only
  afterwards), country and product (domain-specific).
- Model selection and the decision threshold use the training period only
  (5-fold stratified cross-validation, `random_state=42`).
  The test period was used once, for the numbers below.

## Model selection (cross-validation)

Mean over 5 folds of the training period; the model with the highest PR-AUC is
selected and refitted on the whole training period.

| Model | ROC-AUC | PR-AUC |
|---|---:|---:|
| logistic_regression | 0.7750 | 0.2646 |
| random_forest (selected) | 0.8834 | 0.5127 |
| hist_gradient_boosting | 0.8761 | 0.4915 |

Decision threshold (maximises F1 on the selected model's out-of-fold predictions):
0.2906. Risk bands: medium from 0.1453,
high from 0.2906.

## Test period results

| Subset | Rows | Late rate | ROC-AUC | PR-AUC | Macro-F1 | Precision | Recall | Brier | Mean score |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| All shipments | 2,545 | 13.99% | 0.8320 | 0.3344 | 0.6559 | 0.358 | 0.553 | 0.0985 | 0.1359 |
| External vendors | 1,550 | 2.45% | 0.8078 | 0.1570 | 0.4938 | 0.000 | 0.000 | 0.0226 | 0.0336 |

Confusion matrix, all test shipments, at threshold 0.2906:

| | Predicted on time | Predicted late |
|---|---:|---:|
| Actually on time | 1,835 | 354 |
| Actually late | 159 | 197 |

"Precision" is how often a "late" warning is right; "recall" is the share of late shipments
caught. At this threshold the model catches 55% of late shipments,
and 36% of its warnings are correct.

## Operating points

The shipped threshold balances the two errors. A deployment that would rather catch almost
every late delivery, and accept more needless checks, can use the screening threshold instead
(F2, recall weighted above precision). Both are measured on the same
calibrated model and the same test period.

| Operating point | Threshold | Precision | Recall | Orders flagged |
|---|---:|---:|---:|---:|
| Shipped (balanced F1) | 0.2906 | 0.358 | 0.553 | 21.7% |
| Screening (F2) | 0.1445 | 0.317 | 0.924 | 40.8% |

## Calibration

The selected model is class-weighted, which makes its raw scores good for ranking but far too
high to read as probabilities. It is wrapped in `CalibratedClassifierCV`
(sigmoid, fitted on the training period only), so a displayed
percentage can be read literally.

| | Mean predicted | Brier (lower is better) |
|---|---:|---:|
| Before calibration | 0.3736 | 0.1671 |
| After calibration | 0.1359 | 0.0985 |
| Observed late rate | 0.1399 | - |

## Baselines

Same test period. "Always on time" scores every shipment 0. "Prior on-time rate" scores a
shipment as 1 - the supplier's prior on-time rate (training late rate when the supplier has
no history), with its own F1-maximising threshold from the training period
(0.0341).

| Scorer | Rows | Late rate | ROC-AUC | PR-AUC | Macro-F1 | Precision | Recall | Brier |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| random_forest (all shipments) | 2,545 | 14.0% | 0.8320 | 0.3344 | 0.6559 | 0.358 | 0.553 | 0.0985 |
| baseline: always on time (all shipments) | 2,545 | 14.0% | 0.5000 | 0.1399 | 0.4624 | 0.000 | 0.000 | 0.1399 |
| baseline: prior on-time rate (all shipments) | 2,545 | 14.0% | 0.7609 | 0.2507 | 0.5448 | 0.252 | 0.978 | 0.1109 |
| random_forest (external vendors) | 1,550 | 2.5% | 0.8078 | 0.1570 | 0.4938 | 0.000 | 0.000 | 0.0226 |
| baseline: always on time (external vendors) | 1,550 | 2.5% | 0.5000 | 0.0245 | 0.4938 | 0.000 | 0.000 | 0.0245 |
| baseline: prior on-time rate (external vendors) | 1,550 | 2.5% | 0.7466 | 0.0631 | 0.5024 | 0.078 | 0.789 | 0.0240 |

## Feature importance

Permutation importance of the selected model on the test period (mean drop in PR-AUC over
10 shuffles; values near zero or negative mean the model does not rely on the feature).

| Feature | Importance |
|---|---:|
| prior_count | 0.0270 |
| prior_on_time_rate | 0.0223 |
| recent_late_rate | 0.0122 |
| days_since_previous | 0.0033 |
| log_order_value | 0.0024 |
| shipment_mode | 0.0010 |
| has_history | 0.0000 |
| log_quantity | -0.0022 |
| fulfil_via | -0.0031 |
| prior_mean_delay_days | -0.0044 |

## Limitations

- Health-commodity domain: SCMS shipped HIV/AIDS and malaria medicines and test kits to
  public health programmes. Delivery behaviour of other suppliers and industries may differ,
  so scores for an organisation's own suppliers are indicative only.
- Year-to-year drift: the late rate moves a lot between years (see Dataset), so a model
  fitted on 2006-2013 is tested on a period with a different base rate.
- Low positive rate: about 11% of training shipments are late, and
  2.5% of external-vendor test shipments, so PR-AUC and F1 are more
  informative than accuracy, and small subsets give noisy estimates.
- Features intentionally exclude country and product so the model transfers to any
  organisation's purchase-order history; this costs accuracy that SCMS-specific features
  might add.
- Shuffled cross-validation mixes years, so the cross-validated scores above are more
  optimistic than the time-ordered test (random_forest: CV PR-AUC
  0.5127, test PR-AUC 0.3344).
- Calibration is fitted on the training period and applied to a later one with a different base
  rate (10.67% then, 13.99% in the test period), so
  the probabilities are close but not exact: mean predicted 0.1359
  against 13.99% observed.
- Narrow training range: the lowest prior on-time rate of any training shipment's supplier is
  60%. Tree models give flat scores outside the range they were trained on, so a supplier that is late far more often than any SCMS supplier is not scored as riskier than a moderately unreliable one, and may not reach the high band.
- More than half of all shipments share one supplier key ("SCMS from RDC"). For those rows
  the history features describe SCMS's whole warehouse network, and `prior_count` grows
  steadily with calendar time, so the model can partly use it as a proxy for the period.
