# USAID SCMS Delivery History Dataset

**File:** `SCMS_Delivery_History_Dataset.csv`
**Publisher:** USAID Supply Chain Management System (SCMS), published on data.usaid.gov as
dataset `a3rc-nmf6`.

## Source

The official data.usaid.gov portal and the data.world mirror were both unavailable in
September 2026, so the file was taken from a public GitHub copy of the raw export:

<https://raw.githubusercontent.com/jrcinco/supply-chain-shipment-price-data/master/SCMS_Delivery_History_Dataset.csv>

## Checksum

SHA-256: `918b992dd3e8d4b64d2a727b2c4ea607603d0c58f19484e73f7b78528c6a8673`

`ml.scms.load_scms()` recomputes this checksum on every load and raises `ValueError` if the
file differs. To check it by hand:

```bash
sha256sum SCMS_Delivery_History_Dataset.csv
```

## Verification

The copy was cross-checked against an independent mirror,
<https://github.com/Prashant-Abbi/Supply-Chain-Management>: shipment IDs, scheduled,
delivered and delivery-recorded dates, weights, freight costs and late-delivery labels are
identical. That mirror has cleaned text placeholders and stripped accents, so the raw file
above is the one kept here.

## Contents

- 10,324 rows (one per shipment line), 33 columns
- 73 vendors (including "SCMS from RDC", SCMS's own regional distribution centres), 43 countries
- Scheduled delivery dates from 2006 to 2015
- 11.49% of shipments delivered after the scheduled date
- Encoding: UTF-8 with a byte-order mark; line endings are carriage returns only.
- Several numeric columns contain text placeholders ("Freight Included in Commodity Cost",
  "Weight Captured Separately", "See ASN-... (ID#:...)"); the loader turns them into NaN.

## Licence

U.S. federal government data; U.S. government works are not subject to copyright in the
United States (17 U.S.C. §105).
