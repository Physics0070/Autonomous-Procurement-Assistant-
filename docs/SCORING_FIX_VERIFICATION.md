# Scoring fix verification

Status on 28 November 2026. Working tree on `main`, uncommitted. Results below are from actual test runs; nothing here
is claimed from documentation alone.

## Starting point

* `git status`: clean, `main` level with `origin/main`, one branch only (no other branch holds fixes).
* `origin/main` at `ebb602d` already contained the first round of fixes (receipt, quality, accepted quantity, evidence
  coverage, displayed weights, response timestamps, invoice classes, receipt validation, currency, GST, extraction
  attribution, anomaly gate, weight validation). The review that called these missing was looking at an older state.
* **Method, stated honestly:** the first-round fixes in `ebb602d` were written with their tests alongside, not test
  first. The defects new in this round were handled test first: `tests/test_scoring_followup.py` was written and run
  against the unchanged code before any fix (**18 failed, 2 passed**), then the fixes were made.

## Test runs

| Run | Result |
|---|---|
| `tests/test_scoring_followup.py` before any fix | 18 failed, 2 passed |
| Same file after the fixes | 20 passed |
| Targeted: `test_scoring_followup.py`, `test_supplier_scorecard.py`, `test_discounts.py` (run alone) | 54 passed, 0 failed |
| Related suites (purchase orders, discounts, comparison, scorecard, award, agents, analytics, communications) | 99 passed |
| Full backend suite, run alone | **8,537 passed, 60 skipped, 0 failed** (12 min 40 s) |
| Frontend `tsc --noEmit` | no errors |
| Frontend `vite build` | built |

An earlier full run reported 1 failure and 2 errors (`KeyError` in fixture setup). It had been run at the same time
as a second pytest process sharing the same test database, which each test drops; run alone, everything passed. That
earlier result is not counted.

Two tests passed before the fixes because the behaviour was already correct: one rejected unit in 100, and a reminder
before any reply. Two of the 18 failures (`test_percentage_discount_scales_with_quantity`,
`test_po_reconciles_to_the_paisa`) failed only because the new `discount_type` field and `reconcile()` check did not
exist; the arithmetic they check was already right.

Two existing tests were changed, because they asserted the old, defective behaviour:

* `test_discounts.py::test_the_purchase_order_takes_the_discount_off_before_gst` expected a fixed ₹100 discount to be
  scaled to ₹190 when the quantity changed. It now uses a 10% discount, which should scale; fixed amounts are covered
  by the new tests.
* `test_supplier_scorecard.py::test_repeated_rfq_sends_count_once_from_the_first_send` sent its "reminder" after the
  supplier had replied, which under per-round matching is a new round. The reminder now precedes the reply.

## Findings

### Reliability (`backend/app/services/procurement/reliability.py`)

| # | Original defect | Corrected implementation | Regression test(s) | Result |
|---|---|---|---|---|
| R1 | `all()` over an empty receipt counted an order as in full | `receipt_lines()` returns None unless every PO line has a valid receipt line; OTIF uses only receipted orders; with none, on-time alone, marked `partial` | `test_on_time_orders_without_receipts_are_never_in_full`, `test_receipted_orders_decide_otif_and_unreceipted_ones_are_not_counted_as_in_full` | passed |
| R2 | Quality was the mean of per-line rejection rates | total rejected / total received; `n` = orders with inspection data | `test_quality_is_weighted_by_quantity_not_averaged_per_line`, `test_one_rejected_unit_out_of_100` (1 in 100 → 0.95) | passed |
| R3 | In-full ignored rejected units | accepted = received − rejected, stored per line, used for in-full and receipt status | `test_partial_delivery_and_rejections_use_accepted_quantity`, `test_receipt_cancellation_and_scorecard_through_the_api` | passed |
| R4 | Receipt line count and quantities loosely checked | API: `line` index required once each, `ge=0`, `allow_inf_nan=False`; service: rejected ≤ received; stored broken receipts count as missing | `test_broken_receipts_count_as_missing_never_as_good`, `test_receipt_is_validated` | passed |
| R5 | Invoices compared loosely; zero invoice counted as underbilling | `invoice_check()`: correct / overbilled / underbilled for final invoices on comparable orders; partial, credit note, short delivery, zero not scored; approved revised total; API refuses 0 (`gt=0`) | `test_invoices_are_classified_and_only_comparable_final_ones_scored`, `test_zero_invoice_amount_is_not_scored_as_underbilling`, `test_zero_invoice_amount_is_refused_by_the_api` | passed |
| R6 | Supplier cancellations reported as completed orders | `sample_size` = orders assessed; `delivered_orders` and `supplier_cancellations` separate; notes say "3 orders assessed: 0 delivered, 3 cancelled by the supplier" | `test_three_supplier_cancellations_are_not_three_completed_orders`, `test_buyer_cancellations_and_never_issued_orders_do_not_count` | passed |
| R7 | Response time from processing time; RFQ instances not matched | Email Date header only; uploads untimed; `_rounds()` pairs each RFQ round with its first reply: a send while unanswered is a reminder (clock from the first send), a send after a reply opens a new round, extra replies are not counted again | `test_each_rfq_round_is_timed_against_its_own_reply`, `test_a_reminder_before_any_reply_does_not_restart_the_clock`, `test_delayed_gmail_sync_uses_the_email_time_not_processing_time`, `test_uploads_without_a_received_time_are_not_timed_and_silence_scores_zero`, `test_repeated_rfq_sends_count_once_from_the_first_send` | passed |
| R8 | Low evidence produced confident ratings | `coverage` (partial counts half), `confidence`, `provisional` under 5 orders or 60% coverage; comparison moves a provisional score from 0.5 only in proportion to coverage | `test_four_perfect_orders_are_only_provisional`, `test_three_supplier_cancellations_are_not_three_completed_orders` | passed |
| R9 | Displayed weights did not reproduce the score | `applied_weight` and `contribution` per factor; score = sum of contributions | `contributions_add_up()` in `test_perfect_supplier_with_enough_evidence_is_rated` and the API test | passed |

`VERSION` raised to 3 so suppliers stored with older rules are rescored once at startup.

### Comparison (`backend/app/services/procurement/comparison.py`, `backend/app/schemas/comparison.py`, `backend/app/repositories/quotations.py`)

| # | Original defect | Corrected implementation | Regression test(s) | Result |
|---|---|---|---|---|
| C1 | Mixed currencies priced on one scale | Other-currency quotations not priced, `requires_review`, never recommended | `test_mixed_currencies_are_not_priced_against_each_other_or_recommended` | passed |
| C2 | A GST rate was taken as "total includes GST" | `tax_basis()`: reconciling figures first; when total = net subtotal the document's wording decides (`gst_wording()`: "inclusive of GST", "GST extra"…); a stated rate without wording is treated as GST extra and added; "extra" with no rate gives no comparable price. `for_request` now keeps the document's plain text | `test_tax_rate_alone_does_not_make_a_total_inclusive`, `test_gst_wording_decides_when_the_figures_cannot`, `test_comparison_reads_the_document_wording`, `test_tax_extra_quotation_is_compared_with_gst_added`, `test_unknown_tax_basis_is_left_off_the_price_scale_when_others_are_known` | passed |
| C3 | Extraction findings lowered the supplier's score | Validation never scored; confirmed supplier arithmetic errors (after a person reviewed and left the figure) listed separately | `test_ocr_validation_errors_do_not_cost_the_supplier_points` | passed |
| C4 | High price anomaly could be the recommendation | `requires_review`; recommendation = best-ranked unflagged quotation; award needs `confirm_review`, recorded in PO history; supervisor agent picks the same | `test_high_anomaly_top_quotation_is_not_recommended_as_awardable`, `test_award_of_a_quotation_flagged_for_review_needs_confirmation` | passed |
| C5 | Unknown or invalid weights accepted | `validate_weights()` in the request schema and the engine: only the five criteria, finite, ≥ 0, not all zero (422) | `test_weight_overrides_are_validated`, `test_unknown_weight_overrides_are_rejected_by_the_api` | passed |
| C6 | A single quotation, or tied ones, scored a perfect 1.0 on relative criteria | No spread → neutral 0.5 with the reason in the deductions | `test_a_single_quotation_gets_no_perfect_relative_scores`, `test_tied_quotations_get_no_perfect_relative_scores` | passed |

### Purchase orders (`backend/app/services/automation/purchase_orders.py`, `backend/app/api/routes/automation.py`)

| # | Original defect | Corrected implementation | Regression test(s) | Result |
|---|---|---|---|---|
| P1 | GST-inclusive unit prices were taxed again | When the quotation says rates include GST and its total does not add GST on top, GST is taken out of each line (amount / (1 + rate)) and added once; unclear treatment is warned on the PO | `test_gst_inclusive_unit_prices_are_not_taxed_twice` (118 incl. 18% → 100 + 18), `test_unknown_gst_treatment_is_flagged_on_the_po` | passed |
| P2 | A fixed discount was scaled when quantities changed | `discount_type`: percentage applies to the PO subtotal; a fixed amount applies only to exactly the quoted items and quantities, otherwise not applied and warned | `test_percentage_discount_scales_with_quantity`, `test_fixed_discount_is_not_scaled_when_quantities_change`, `test_the_purchase_order_takes_the_discount_off_before_gst` | passed |
| P3 | Quantity-tiered rates not considered | Ordering a quantity different from the quoted one is warned | `test_ordering_a_different_quantity_than_quoted_is_flagged_for_tiered_rates` | passed |
| P4 | No deterministic reconciliation | `reconcile()` in paise: lines sum to subtotal, qty × rate = amount, discount ≤ subtotal, total = subtotal − discount + GST + freight, total > 0 | `test_po_reconciles_to_the_paisa` | passed |
| P5 | Invalid values could enter approval | Missing, zero, negative or non-finite price, quantity or GST rate never makes a PO line; `approve` refuses a PO that does not reconcile | `test_invalid_prices_never_reach_a_po_line[nan/inf/-5.0/0.0]`, `test_a_po_that_does_not_reconcile_cannot_be_approved` | passed |

## Remaining limitations

* **RFQ matching is by request and time, not by email thread.** RFQs are marked sent by hand and carry no Gmail thread
  id, so a supplier's unrelated mail about the same request after a new send would be read as that round's reply.
* **GST wording is matched in English only** ("inclusive of GST", "GST extra", "+ GST"…). Hindi or Marathi wording, or
  unusual phrasing, falls back to the figures; a document saying both gives "unknown". Quotations with no stored text
  cannot use wording.
* **Without wording, a total equal to the subtotal with a GST rate stated is assumed to be GST extra.** If such a
  quotation really meant "rates inclusive", its comparison price is overstated by the GST until a person checks.
* **Tiered pricing is not extracted;** a changed quantity is only warned about. A fixed discount on a changed order is
  left off (the cautious choice), so the PO may be higher than what the supplier would actually agree.
* **Backing GST out of inclusive rates can differ from the quoted total by ₹0.01** from rounding; the PO itself still
  reconciles exactly.
* **"Confirmed supplier error" needs a correction on that quotation;** there is no explicit "confirm" action.
* **Scorecard thresholds are design choices, not fitted:** 3 and 5 orders, 60% coverage, 5 points per 1% rejected,
  2 and 14 reply days. They have not been validated against real outcomes; no organization has recorded enough
  deliveries yet.
* **Stored data:** comparisons already saved keep their old figures until recomputed; existing POs are checked only
  when approved.
* **Frontend:** the PO page does not yet show `discount_type`, and no screen was checked in a browser this round (the
  browser session is signed out).
* **Unchanged by design:** ML models, agents and frontend architecture.
