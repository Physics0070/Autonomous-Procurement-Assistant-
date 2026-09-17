# Supplier late-delivery risk model

Model version `reliability-scms-20260917`, trained 2026-09-17T16:48:04+00:00 with scikit-learn
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
0.6179. Risk bands: medium from 0.3090,
high from 0.6179.

## Test period results

| Subset | Rows | Late rate | ROC-AUC | PR-AUC | Macro-F1 | Brier | Mean score |
|---|---:|---:|---:|---:|---:|---:|---:|
| All shipments | 2,545 | 13.99% | 0.8306 | 0.3288 | 0.6664 | 0.1671 | 0.3736 |
| External vendors | 1,550 | 2.45% | 0.7999 | 0.1901 | 0.5196 | 0.0596 | 0.1862 |

Confusion matrix, all test shipments, at threshold 0.6179:

| | Predicted on time | Predicted late |
|---|---:|---:|
| Actually on time | 1,706 | 483 |
| Actually late | 93 | 263 |

"Mean score" is the average predicted late probability. The candidates are trained with
balanced class weights, so their scores are risk scores rather than calibrated
probabilities; compare the mean score with the observed late rate.

## Baselines

Same test period. "Always on time" scores every shipment 0. "Prior on-time rate" scores a
shipment as 1 - the supplier's prior on-time rate (training late rate when the supplier has
no history), with its own F1-maximising threshold from the training period
(0.0407).

| Scorer | Rows | Late rate | ROC-AUC | PR-AUC | Macro-F1 | Brier |
|---|---:|---:|---:|---:|---:|---:|
| random_forest (all shipments) | 2,545 | 14.0% | 0.8306 | 0.3288 | 0.6664 | 0.1671 |
| baseline: always on time (all shipments) | 2,545 | 14.0% | 0.5000 | 0.1399 | 0.4624 | 0.1399 |
| baseline: prior on-time rate (all shipments) | 2,545 | 14.0% | 0.7609 | 0.2507 | 0.5448 | 0.1109 |
| random_forest (external vendors) | 1,550 | 2.5% | 0.7999 | 0.1901 | 0.5196 | 0.0596 |
| baseline: always on time (external vendors) | 1,550 | 2.5% | 0.5000 | 0.0245 | 0.4938 | 0.0245 |
| baseline: prior on-time rate (external vendors) | 1,550 | 2.5% | 0.7466 | 0.0631 | 0.5024 | 0.0240 |

## Feature importance

Permutation importance of the selected model on the test period (mean drop in PR-AUC over
10 shuffles; values near zero or negative mean the model does not rely on the feature).

| Feature | Importance |
|---|---:|
| prior_count | 0.0257 |
| prior_on_time_rate | 0.0147 |
| recent_late_rate | 0.0086 |
| has_history | 0.0000 |
| log_order_value | -0.0000 |
| days_since_previous | -0.0002 |
| shipment_mode | -0.0023 |
| fulfil_via | -0.0032 |
| log_quantity | -0.0038 |
| prior_mean_delay_days | -0.0040 |

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
  0.5127, test PR-AUC 0.3288).
- Scores are not calibrated probabilities: balanced class weights push them up (mean test
  score 0.3736 against an observed late rate of
  13.99%), which is why the Brier score can be worse than a baseline's.
  Use them to rank suppliers and with the risk bands, not as literal chances.
- Narrow training range: the lowest prior on-time rate of any training shipment's supplier is
  60%. Tree models give flat scores outside the range they were trained on, so a supplier that is late far more often than any SCMS supplier is not scored as riskier than a moderately unreliable one, and may not reach the high band.
- More than half of all shipments share one supplier key ("SCMS from RDC"). For those rows
  the history features describe SCMS's whole warehouse network, and `prior_count` grows
  steadily with calendar time, so the model can partly use it as a proxy for the period.
