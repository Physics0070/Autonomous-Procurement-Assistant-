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


---

# Edge-case audit (second round, 28 November 2026)

Scope: the six remaining issues only (award safety, OTIF evidence coverage, quality inspection, supplier-error
attribution, all-unknown GST basis, atomic delivery). The earlier fixes above were not rewritten.

**Method:** `backend/tests/test_edge_case_audit.py` (24 tests) was written and run against the unchanged code first:
**18 failed, 6 passed**. Then the corrections were made and the file rerun: **24 passed**.

The 6 that already passed were guards for behaviour that was already right or not yet reachable:
`test_missing_receipts_are_neither_successes_nor_failures` and `test_inspected_with_zero_rejected_is_real_quality_evidence`
(already correct), `test_receipts_not_yet_inspected_give_no_quality_evidence` and
`test_correcting_the_field_after_confirming_withdraws_the_confirmation` (passed for the wrong reason: the old code had
no inspection flag or confirmation, so the receipt was treated as broken and the issue as unconfirmed),
`test_a_cancelled_award_frees_the_request_for_a_new_award` (trivially, since duplicates were allowed) and
`test_delivery_and_receipt_are_saved_together` (the valid path worked; only the failure path was unsafe).

Old behaviour seen in the failing run: an award with no stored comparison, for a quotation left out of the
comparison, or after a price changed, created a PO (201); a second award on the same request created a second PO;
8 concurrent awards created 8 POs; 4 concurrent deliveries all returned 200 and wrote 4 "deliver" history entries; a
delivery with a duplicate receipt line left the PO "delivered" with no receipt (the 409 came after the status had
been written); a correction to `supplier.name` made every untouched arithmetic mismatch a "confirmed supplier
error"; with no GST basis known, raw totals were ranked on price (1.0 vs 0.0) and one was recommended.

## Results

| Run | Result |
|---|---|
| `tests/test_edge_case_audit.py` before any fix | 18 failed, 6 passed |
| Same file after the fixes | 24 passed |
| Related suites (analytics, analytics cache, communications, delivery dates, discounts, Drive, monitor agent, purchase orders, scoring follow-up, sourcing graph, supervisor, scorecard, edge-case audit), run alone | first run after the fixes: 13 failed, 117 passed (tests asserting the old behaviour, listed below); after updating those: **130 passed** |
| Full backend suite | not run in this round (stopped on request); the complete run in the third round below covers it: 8,574 passed, 60 skipped, 0 failed |
| Frontend `tsc --noEmit -p .` | no errors |
| Frontend `vite build` | built |

## Findings

| # | Issue | Correction | Regression test(s) | Result |
|---|---|---|---|---|
| E1 | Award with no comparison, for a quotation not in it, or from a stale one | Award refuses (409): no stored comparison; quotation not among its rows; stored `input_fingerprint` differs from the current one (SHA-256 of the request's items and currency and of every quotation on the request: data, matching, status, findings, confirmations, text). Comparisons saved before this change have no fingerprint and must be recomputed once | `test_award_without_a_comparison_is_refused`, `test_award_of_a_quotation_left_out_of_the_comparison_is_refused`, `test_award_from_a_stale_comparison_is_refused_until_recomputed`, `test_a_quotation_arriving_after_the_comparison_makes_it_stale` | passed |
| E2 | Duplicate POs for one request; no atomic or idempotent protection | One live PO per request (split awards are not supported). An awarded PO carries `award_key` = request id under a unique partial index (`uniq_live_award`), so the database lets exactly one concurrent insert through; cancelling removes the key so the request can be awarded again. Repeating the same award returns the existing PO (200); another quotation gets 409 naming the PO. The supervisor agent's PO step uses the same guard | `test_a_second_award_for_the_same_request_is_refused`, `test_repeating_the_same_award_returns_the_existing_order`, `test_concurrent_awards_create_exactly_one_order` (8 parallel, 1 PO), `test_a_cancelled_award_frees_the_request_for_a_new_award`, `test_the_agent_path_cannot_create_a_second_order` | passed |
| E3 | OTIF not partial when only some delivered orders had receipts; coverage overstated | Each factor has an `evidence` share and `coverage` = sum of weight x evidence. OTIF evidence = (receipted + 1/2 on-time-only) / delivered. Orders without a receipt are left out of the score, neither success nor failure, and the reason says so; partial whenever evidence < 1 | `test_partly_receipted_otif_is_partial_and_coverage_counts_the_gap` (evidence 0.75, coverage 0.525), `test_missing_receipts_are_neither_successes_nor_failures`, `test_fully_receipted_otif_is_not_partial` | passed |
| E4 | A defaulted rejected quantity of 0 counted as an inspection | API: `rejected_quantity` optional; left out = not inspected. Stored per line: `inspected`, `rejected_quantity` and `accepted_quantity` (both null when not inspected); receipt-level `inspected`. Quality uses inspected lines only; evidence = inspected orders / delivered. Receipts stored before the flag count as inspected only when they record a rejection (a stored 0 may be the old default). In-full on an uninspected line uses the quantity received. Purchase orders page: "Rejected" starts blank ("not inspected"); a "Not yet inspected" badge | `test_receipts_not_yet_inspected_give_no_quality_evidence`, `test_inspected_with_zero_rejected_is_real_quality_evidence`, `test_legacy_receipts_with_a_defaulted_zero_are_not_inspection_evidence`, `test_api_receipt_without_a_rejected_quantity_is_recorded_as_not_inspected` | passed |
| E5 | Any user correction confirmed every unrelated arithmetic mismatch | A supplier error needs an explicit, field-specific confirmation: `POST /quotations/{id}/issue-confirmations` with `{field, code}` (409 unless that arithmetic finding is on the quotation), stored in `confirmed_issues`. A later correction of the same field withdraws it. Quotation review screen: an "It is on the document (supplier's error)" button per arithmetic finding | `test_an_unrelated_correction_does_not_confirm_arithmetic_errors`, `test_only_the_explicitly_confirmed_field_is_the_suppliers_error`, `test_correcting_the_field_after_confirming_withdraws_the_confirmation`, `test_confirming_a_supplier_error_through_the_api` | passed |
| E6 | With every GST basis unknown, raw totals were ranked as comparable prices | No price ranking: each such quotation scores neutral 0.5 on price, `data_available` false, with a deduction showing its quoted total; each `requires_review` ("Confirm whether the quoted total includes GST..."); no recommendation; a result warning says the totals are not ranked. Quoted totals stay visible (`landed_cost`) | `test_when_no_quotation_shows_its_gst_basis_raw_totals_are_not_ranked` | passed |
| E7 | Delivery state written before the receipt was validated; concurrent actions all applied | The receipt is validated before any write and saved in the same update as the delivery (`combine()`: one `$set`, both history entries). Every PO action and receipt save is a compare-and-set on the status that was read (`raw_update(..., expected={"status": ...})`): of concurrent actions only the first applies, the others get 409 | `test_an_invalid_receipt_leaves_the_order_undelivered` (duplicate line, missing line, rejected > received: status stays issued, no receipt, no delivery date, no history entry), `test_delivery_and_receipt_are_saved_together`, `test_concurrent_deliveries_are_recorded_once` (4 parallel: 200, 409, 409, 409) | passed |

`reliability.VERSION` is now 4, so stored scorecards are recomputed once at startup.

## Existing tests changed because they asserted the old behaviour

* Several orders on one request: `test_analytics.py::delivered_po`, `test_supplier_scorecard.py::_issued_po` and
  `test_purchase_orders.py::test_unmatched_items_are_warned_and_numbers_are_sequential` awarded repeatedly on the
  fixture's single request. They now open a new round per order (`tests/rounds.py`: same items and quotations, a new
  request, its comparison run). Their assertions are unchanged.
* `test_delivery_dates.py::test_issuing_a_po_uses_the_quoted_delivery_date` changed a quotation after the fixture's
  comparison and then awarded; that is now a stale comparison, so the test recomputes it first.
* `test_supplier_scorecard.py::po()` built receipts with `rejected_quantity` 0 and no flag, which now reads as "not
  inspected"; the helper marks its lines `inspected: True`, which is what those tests meant.
* `test_receipted_orders_decide_otif_and_unreceipted_ones_are_not_counted_as_in_full` asserted `partial is False`
  with 2 of 5 orders unreceipted; it now asserts partial with evidence 0.8.
* `test_broken_receipts_count_as_missing_never_as_good`: a legacy receipt line with rejected 0 now gives
  `(2, 2, None)` (not inspected) instead of `(2, 2, 0)`.
* `test_ocr_validation_errors_do_not_cost_the_supplier_points` used a correction of `delivery.delivery_days` to
  confirm a line-total error; it now asserts that this confirms nothing, and that an explicit confirmation does.

## Remaining limitations (this round)

* **Split awards are not supported.** A request has one live PO; ordering from two suppliers needs two requests.
* **A delivered or closed PO keeps the request's award.** Re-ordering the same items is a new request.
* **Staleness does not cover supplier scorecards or weights.** A supplier's score changing after the comparison does
  not make it stale.
* **Comparisons saved before this change have no fingerprint** and refuse award until recomputed once.
* **PO numbers can skip** when two awards race: the loser has already taken a number from the counter.
* **POs created before this change carry no `award_key`.** The award route still refuses a second award on such a
  request (it looks for any non-cancelled PO), but two awards racing on it are protected by that check only, not by
  the index.
* **Receipts recorded before this change** with rejected 0 count as not inspected; re-saving the receipt with 0
  entered records the inspection.
* **The frontend changes were type-checked and built, not exercised in a browser** this round.


---

# Final quality review (third round, 28 November 2026)

Scope: mixed GST basis, line-level inspection coverage, comparison freshness, round-specific RFQ matching, and a
release check. Earlier fixes were kept as they were.

**Method:** each issue was first confirmed in the code (unknown basis beside known ones only warned; an order counted
as inspected if any line was, and kg, litres and pieces were summed; the fingerprint had no scorecards, weights or
version; one untimed upload cleared silence for every round of its request). `backend/tests/test_final_quality_review.py`
(13 tests) was then run against the unchanged code: **12 failed, 1 passed** (the passing one is the control: an
unchanged comparison still awards). After the corrections: **13 passed**.

## Results

| Run | Result |
|---|---|
| `tests/test_final_quality_review.py` before any fix | 12 failed, 1 passed |
| Same file after the fixes | 13 passed |
| Related suites (as in the second round, plus this file), run alone | 143 passed |
| **Complete backend suite**, run alone (no other pytest process on the test database) | **8,574 passed, 60 skipped, 0 failed** (6 min 44 s) |
| Frontend `tsc --noEmit -p .` | no errors (exit 0) |
| Frontend `vite build` | built |

This complete run covers the second round too: its "not run this round" entry above is superseded by this result.
No existing test had to change in this round.

## Findings

| # | Issue | Correction | Regression test(s) | Result |
|---|---|---|---|---|
| F1 | A quotation with unknown GST basis beside known ones was only warned about, and could be recommended or awarded | It now `requires_review` ("Confirm whether this quoted total includes GST before awarding..."), so it is never the recommendation and an award needs `confirm_review` (recorded in PO history) | `test_unknown_gst_basis_beside_known_ones_needs_review_and_is_not_recommended` (inclusive, exclusive, unknown), `test_unknown_gst_quotation_cannot_be_awarded_without_confirmation` (409, then 201 with confirmation) | passed |
| F2 | Inspection counted per order; quantities in different units summed | Evidence is line-level: inspected lines / all lines of delivered orders (`lines_inspected`, `lines_total`). Aggregation (`method`): `value_weighted` (rejected value / received value at PO unit prices) when every inspected line has a price; `quantity_weighted` when prices are missing but one unit; `line_average` (mean line rate) when units differ and prices are missing. Documented in `_quality` | `test_one_inspected_line_does_not_make_the_order_inspected` (evidence 6/9), `test_rejections_in_different_units_are_weighted_by_value_not_summed` (0.6667, not 0.99), `test_without_prices_mixed_units_fall_back_to_the_mean_line_rate` (0.5), `test_one_unit_without_prices_stays_quantity_weighted` | passed |
| F3 | Fingerprint ignored supplier scorecards, active weights and the scoring version | `comparison_fingerprint()` now also covers `COMPARISON_VERSION` (2), the configured default weights, and each quoting supplier's scorecard (method, version, score, status, coverage, band). A change to any of them makes award refuse until the comparison is recomputed | `test_a_changed_supplier_scorecard_makes_the_comparison_stale`, `test_changed_default_weights_make_the_comparison_stale`, `test_a_new_scoring_algorithm_version_makes_the_comparison_stale`, `test_unchanged_inputs_still_award` | passed |
| F4 | One untimed upload suppressed the no-reply penalty for every round of its request | A manual upload is placed at its upload time and closes only the round open then (not timed, not silence); later rounds are judged on their own, and an upload before any send answers nothing | `test_an_untimed_upload_answers_only_its_own_round`, `test_mixed_sends_replies_reminders_and_uploads` (two requests, reminder, email replies, upload, silence: (0.75 + 0 + 1.0) / 3), `test_an_upload_before_any_send_answers_nothing` | passed |

`reliability.VERSION` is now 5, so stored scorecards are recomputed once at startup; comparisons stored before this
change no longer match the fingerprint and must be recomputed before award.

## Remaining limitations (this round)

* **Value weighting uses the PO unit price** (taxable, after any GST back-out). Lines without a price in a mixed-unit
  order fall back to the mean line rate, which treats a small line like a large one.
* **An upload's time is an upper bound** on when the supplier answered: the round it closes is not timed at all.
* **Weight overrides chosen for one comparison run are part of its result, not its inputs;** only the configured
  defaults are in the fingerprint.
* **Gmail end to end is still not verified** with a real mailbox (waiting on the team to send one quotation as an
  attachment from another address). Drive filing is verified.
