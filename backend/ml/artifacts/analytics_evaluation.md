# Analytics evaluation (USAID SCMS)

Generated 2026-11-20T10:43:23+00:00 by `python -m ml.evaluate_analytics` from the verified SCMS file
(see `ml/data/README.md`).

## Price anomaly detection

**There are no ground-truth labels.** SCMS does not say which prices were wrong, so this
section reports how often prices are flagged and shows examples, not an accuracy figure.

Method: for every product (`Molecule/Test Type`) with at least 8 positive unit prices,
each price is assessed with `assess_price` against all the product's other prices
(leave-one-out). A price is only assessed when those other prices number at least
8. 103 shipments with a unit price of zero or below are excluded.

The thresholds are the 10th and 2nd percentiles of the past prices' own anomaly scores, so
roughly one price in ten is expected to be flagged even when nothing is wrong. Treat the flags
as "worth a second look", not as errors.

| Scope | Products | Prices assessed | Flagged POSSIBLE_ANOMALY | Flagged HIGH_ANOMALY | Flagged either |
|---|---:|---:|---:|---:|---:|
| All eligible products | 48 | 10,120 | 1.1% | 0.5% | 1.6% |

### By product

| Product | Prices assessed | POSSIBLE_ANOMALY | HIGH_ANOMALY |
|---|---:|---:|---:|
| Efavirenz | 1,122 | 0.0% | 0.0% |
| Nevirapine | 875 | 0.0% | 0.6% |
| Lamivudine/Nevirapine/Zidovudine | 705 | 0.0% | 0.0% |
| Lamivudine/Zidovudine | 688 | 6.7% | 0.0% |
| Lopinavir/Ritonavir | 628 | 0.0% | 0.3% |
| Lamivudine | 591 | 0.0% | 0.0% |
| HIV 1/2, Determine Complete HIV Kit | 569 | 0.0% | 2.1% |
| Zidovudine | 527 | 0.0% | 0.2% |
| Abacavir | 448 | 0.0% | 0.0% |
| HIV 1/2, Uni-Gold HIV Kit | 368 | 0.0% | 1.9% |
| Tenofovir Disoproxil Fumarate | 317 | 0.0% | 0.0% |
| Lamivudine/Tenofovir Disoproxil Fumarate | 301 | 2.0% | 1.0% |
| Lamivudine/Nevirapine/Stavudine | 286 | 6.6% | 1.4% |
| Efavirenz/Lamivudine/Tenofovir Disoproxil Fumarate | 285 | 0.0% | 1.8% |
| Stavudine | 282 | 0.0% | 0.0% |
| Didanosine | 260 | 0.0% | 0.0% |
| Emtricitabine/Tenofovir Disoproxil Fumarate | 254 | 0.0% | 0.0% |
| Lamivudine/Stavudine | 152 | 9.2% | 0.0% |
| Efavirenz/Emtricitabine/Tenofovir Disoproxil Fumarate | 139 | 0.0% | 0.0% |
| HIV 1/2, Determine HIV Kit, without Lancets | 139 | 3.6% | 0.0% |
| Abacavir/Lamivudine | 136 | 0.0% | 0.0% |
| Ritonavir | 135 | 0.0% | 0.0% |
| HIV 1/2, Stat-Pak HIV, Kit | 98 | 0.0% | 1.0% |
| HIV 1/2, Bioline 3.0 Kit, Lancets, Capillary pipets, Alcohol swabs included | 86 | 12.8% | 0.0% |
| HIV 1/2, Colloidal Gold, Diagnostic Kit, Antibody | 69 | 0.0% | 0.0% |
| Atazanavir/Ritonavir | 54 | 0.0% | 0.0% |
| Saquinavir | 52 | 0.0% | 3.8% |
| HIV 1/2, OraQuick Advance HIV Rapid Antibody Kit | 47 | 0.0% | 2.1% |
| Raltegravir | 44 | 0.0% | 0.0% |
| Darunavir | 42 | 0.0% | 4.8% |
| Didanosine EC | 41 | 0.0% | 2.4% |
| Chase Buffer, Determine, 100 Tests, 2.5ml x 1 Vial | 39 | 0.0% | 5.1% |
| Indinavir | 36 | 13.9% | 0.0% |
| HIV 1/2, Capillus HIV Kit | 35 | 0.0% | 5.7% |
| HIV, Capillary Tubes, for Determine, EDTA, 50uL,100 Pcs | 34 | 2.9% | 0.0% |
| Etravirine | 32 | 0.0% | 0.0% |
| Atazanavir | 31 | 0.0% | 3.2% |
| Abacavir/Lamivudine/Zidovudine | 28 | 0.0% | 0.0% |
| HIV, Genie II HIV-1/HIV-2 Kit | 23 | 0.0% | 0.0% |
| HIV 1/2, Bioline 3.0 Kit (no accessories) | 19 | 0.0% | 5.3% |
| HIV 1/2, Clearview Complete Kit | 19 | 0.0% | 0.0% |
| HIV 1/2, Stat-Pak Dipstick Assay Kit | 15 | 6.7% | 0.0% |
| HIV 1/2/O, First Response HIV 1-2.0, v.3.0 Cards Kit | 14 | 0.0% | 0.0% |
| Sulfadoxine/Pyrimethamine | 13 | 0.0% | 0.0% |
| Artemether/Lumefantrine | 12 | 0.0% | 0.0% |
| HIV, OraQuick Controls Kit, 3 Vials | 11 | 0.0% | 0.0% |
| Nelfinavir (as mesilate) | 10 | 0.0% | 0.0% |
| HIV 1/2, Determine Kit without Lancets, Buffer or Capillary Tubes, 100 Tests | 9 | 0.0% | 11.1% |

### Ten most extreme flagged prices

Ranked by how far the price is from the product's median (ratio above or below 1).

| Product | Unit price (USD) | Median of other prices | Ratio | Status |
|---|---:|---:|---:|---|
| Zidovudine | 14.04 | 0.12 | 117.00x | HIGH_ANOMALY |
| HIV 1/2, Stat-Pak HIV, Kit | 0.07 | 1.45 | 0.05x | HIGH_ANOMALY |
| Nevirapine | 0.68 | 0.04 | 17.00x | HIGH_ANOMALY |
| Atazanavir | 5.03 | 0.43 | 11.70x | HIGH_ANOMALY |
| Nevirapine | 0.4 | 0.04 | 10.00x | HIGH_ANOMALY |
| Nevirapine | 0.39 | 0.04 | 9.75x | HIGH_ANOMALY |
| Nevirapine | 0.38 | 0.04 | 9.50x | HIGH_ANOMALY |
| Nevirapine | 0.38 | 0.04 | 9.50x | HIGH_ANOMALY |
| Lopinavir/Ritonavir | 1.51 | 0.18 | 8.39x | HIGH_ANOMALY |
| Saquinavir | 1.98 | 0.29 | 6.83x | HIGH_ANOMALY |

Unit prices are per unit of the product's pack (tablet, test, bottle...), and one product name
can cover several strengths, dosage forms and pack sizes, which can explain large ratios.

## Demand forecasting

Monthly quantity (`Line Item Quantity`, summed by scheduled delivery month) for the two
largest product groups. Each method is backtested once on the last `holdout` months
(min(6, months // 4)); the method with the lower sMAPE (percent, 0-200) is chosen and
refitted on the full series to forecast the next 3 months.

| Product group | Shipments | Series | Holdout months | Error Croston | Error linear trend | Chosen | Forecast (range) |
|---|---:|---|---:|---:|---:|---|---|
| ARV | 8,520 | 2006-08 to 2015-08 (109 months, 0 with no shipments) | 6 | 33% | 36% | croston_sba (rough) | 2015-09: 2,460,045 (1,694,957 to 4,676,044), 2015-10: 2,460,045 (1,694,957 to 4,676,044), 2015-11: 2,460,045 (1,694,957 to 4,676,044) |
| HRDT | 1,728 | 2006-05 to 2015-08 (112 months, 0 with no shipments) | 6 | 62% | 74% | croston_sba (poor) | 2015-09: 39,513 (9,349 to 55,335), 2015-10: 39,513 (9,349 to 55,335), 2015-11: 39,513 (9,349 to 55,335) |

Limitations: a single holdout of a few months is a small test; monthly shipment quantities
are lumpy (large one-off orders), which neither a trend line nor last year's value can
anticipate; the series end in 2015-08,
so the forecast months are historical, not current demand.
