# Analytics evaluation (USAID SCMS)

Generated 2026-09-18T03:03:01+00:00 by `python -m ml.evaluate_analytics` from the verified SCMS file
(see `ml/data/README.md`).

## Price anomaly detection

**There are no ground-truth labels.** SCMS does not say which prices were wrong, so this
section reports how often prices are flagged and shows examples, not an accuracy figure.

Method: for every product (`Molecule/Test Type`) with at least 20 positive unit prices,
each price is assessed with `assess_price` against all the product's other prices
(leave-one-out). A price is only assessed when those other prices number at least
20. 103 shipments with a unit price of zero or below are excluded.

The thresholds are the 10th and 2nd percentiles of the past prices' own anomaly scores, so
roughly one price in ten is expected to be flagged even when nothing is wrong. Treat the flags
as "worth a second look", not as errors.

| Scope | Products | Prices assessed | Flagged POSSIBLE_ANOMALY | Flagged HIGH_ANOMALY | Flagged either |
|---|---:|---:|---:|---:|---:|
| All eligible products | 39 | 9,998 | 7.5% | 1.8% | 9.3% |

### By product

| Product | Prices assessed | POSSIBLE_ANOMALY | HIGH_ANOMALY |
|---|---:|---:|---:|
| Efavirenz | 1,122 | 8.6% | 2.0% |
| Nevirapine | 875 | 7.5% | 1.9% |
| Lamivudine/Nevirapine/Zidovudine | 705 | 7.8% | 1.3% |
| Lamivudine/Zidovudine | 688 | 6.7% | 1.7% |
| Lopinavir/Ritonavir | 628 | 7.6% | 2.1% |
| Lamivudine | 591 | 9.0% | 1.5% |
| HIV 1/2, Determine Complete HIV Kit | 569 | 5.3% | 2.1% |
| Zidovudine | 527 | 9.3% | 0.8% |
| Abacavir | 448 | 9.8% | 1.3% |
| HIV 1/2, Uni-Gold HIV Kit | 368 | 0.0% | 1.9% |
| Tenofovir Disoproxil Fumarate | 317 | 9.8% | 2.5% |
| Lamivudine/Tenofovir Disoproxil Fumarate | 301 | 6.3% | 3.0% |
| Lamivudine/Nevirapine/Stavudine | 286 | 8.4% | 1.4% |
| Efavirenz/Lamivudine/Tenofovir Disoproxil Fumarate | 285 | 5.3% | 1.8% |
| Stavudine | 282 | 9.2% | 0.0% |
| Didanosine | 260 | 11.5% | 1.5% |
| Emtricitabine/Tenofovir Disoproxil Fumarate | 254 | 7.9% | 4.3% |
| Lamivudine/Stavudine | 152 | 9.2% | 0.0% |
| Efavirenz/Emtricitabine/Tenofovir Disoproxil Fumarate | 139 | 10.1% | 2.9% |
| HIV 1/2, Determine HIV Kit, without Lancets | 139 | 3.6% | 2.2% |
| Abacavir/Lamivudine | 136 | 5.9% | 4.4% |
| Ritonavir | 135 | 8.1% | 1.5% |
| HIV 1/2, Stat-Pak HIV, Kit | 98 | 8.2% | 2.0% |
| HIV 1/2, Bioline 3.0 Kit, Lancets, Capillary pipets, Alcohol swabs included | 86 | 0.0% | 0.0% |
| HIV 1/2, Colloidal Gold, Diagnostic Kit, Antibody | 69 | 0.0% | 0.0% |
| Atazanavir/Ritonavir | 54 | 5.6% | 0.0% |
| Saquinavir | 52 | 9.6% | 3.8% |
| HIV 1/2, OraQuick Advance HIV Rapid Antibody Kit | 47 | 0.0% | 2.1% |
| Raltegravir | 44 | 6.8% | 0.0% |
| Darunavir | 42 | 0.0% | 9.5% |
| Didanosine EC | 41 | 12.2% | 0.0% |
| Chase Buffer, Determine, 100 Tests, 2.5ml x 1 Vial | 39 | 0.0% | 5.1% |
| Indinavir | 36 | 13.9% | 0.0% |
| HIV 1/2, Capillus HIV Kit | 35 | 8.6% | 5.7% |
| HIV, Capillary Tubes, for Determine, EDTA, 50uL,100 Pcs | 34 | 2.9% | 0.0% |
| Etravirine | 32 | 0.0% | 0.0% |
| Atazanavir | 31 | 19.4% | 3.2% |
| Abacavir/Lamivudine/Zidovudine | 28 | 10.7% | 7.1% |
| HIV, Genie II HIV-1/HIV-2 Kit | 23 | 13.0% | 0.0% |

### Ten most extreme flagged prices

Ranked by how far the price is from the product's median (ratio above or below 1).

| Product | Unit price (USD) | Median of other prices | Ratio | Status |
|---|---:|---:|---:|---|
| Zidovudine | 14.04 | 0.12 | 117.00x | HIGH_ANOMALY |
| Zidovudine | 2.73 | 0.12 | 22.75x | HIGH_ANOMALY |
| Zidovudine | 2.73 | 0.12 | 22.75x | HIGH_ANOMALY |
| Zidovudine | 2.5 | 0.12 | 20.83x | HIGH_ANOMALY |
| HIV 1/2, Stat-Pak HIV, Kit | 0.07 | 1.45 | 0.05x | HIGH_ANOMALY |
| Nevirapine | 0.68 | 0.04 | 17.00x | POSSIBLE_ANOMALY |
| Atazanavir | 5.03 | 0.43 | 11.70x | HIGH_ANOMALY |
| Nevirapine | 0.4 | 0.04 | 10.00x | HIGH_ANOMALY |
| Nevirapine | 0.39 | 0.04 | 9.75x | HIGH_ANOMALY |
| Nevirapine | 0.38 | 0.04 | 9.50x | HIGH_ANOMALY |

Unit prices are per unit of the product's pack (tablet, test, bottle...), and one product name
can cover several strengths, dosage forms and pack sizes, which can explain large ratios.

## Demand forecasting

Monthly quantity (`Line Item Quantity`, summed by scheduled delivery month) for the two
largest product groups. Each method is backtested once on the last `holdout` months
(min(6, months // 4)); the method with the lower sMAPE (percent, 0-200) is chosen and
refitted on the full series to forecast the next 3 months.

| Product group | Shipments | Series | Holdout months | sMAPE linear_trend | sMAPE seasonal_naive | Chosen | Forecast |
|---|---:|---|---:|---:|---:|---|---|
| ARV | 8,550 | 2006-08 to 2015-12 (113 months, 1 with no shipments) | 6 | 147.4 | 137.7 | seasonal_naive | 2016-01: 2,464,205, 2016-02: 4,180,775, 2016-03: 2,940,312 |
| HRDT | 1,728 | 2006-05 to 2015-08 (112 months, 0 with no shipments) | 6 | 66.9 | 83.9 | linear_trend | 2015-09: 50,323, 2015-10: 50,566, 2015-11: 50,809 |

Limitations: a single holdout of a few months is a small test; monthly shipment quantities
are lumpy (large one-off orders), which neither a trend line nor last year's value can
anticipate; the series end in 2015-08 and 2015-12,
so the forecast months are historical, not current demand.
