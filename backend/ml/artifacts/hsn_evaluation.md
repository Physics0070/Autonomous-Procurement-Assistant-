# HSN heading suggestion — evaluation on Indian data

Generated 21 Sep 2026 by `python -m ml.hsn dev test` (text matching) — rerun with `--llm` once
`OPENROUTER_API_KEY` is set to measure the model stage.

## The task

Indian GST invoices must carry an HSN code. Buyers write items the way the trade does
("MS Plate 10mm IS 2062", "Toor Dal", "4C x 16 sqmm armoured cable"); the official HSN master
uses legal wording ("FLAT-ROLLED PRODUCTS OF IRON OR NON-ALLOY STEEL"). The system suggests the
4-digit heading for a quotation line.

## Data

- **Official master:** the GST portal's HSN directory
  (`https://tutorial.gst.gov.in/downloads/HSN_SAC.xlsx`, 21,935 codes, 1,000+ headings),
  stored at `ml/data/india/HSN_SAC.xlsx`.
- **Benchmark:** `ml/data/india/hsn_benchmark.csv` — 114 quotation-style item names from Indian
  SME purchasing (steel, fasteners, pipes, electrical, chemicals, food staples, packaging, IT,
  furniture), each labelled with its 4-digit heading and **checked against the official master**.
  Split once before any tuning: **29 dev** (used to tune the abbreviation list) and **85 test**
  (measured once, below).
- **Data-quality finding:** in the official file, heading 8539's own text is 8538's ("parts
  suitable for… 8535, 8536"), while the detailed rows beneath 8539 (e.g. `85395000` LED lamps)
  are correct. The matcher therefore uses every detailed row, not the heading text alone.

## Method

1. **Text matching (shortlist).** Each heading becomes one document containing all of its
   official text; items are normalised (sizes and numbers removed, Indian trade shorthand such as
   MS, GI, SS, TMT, ERW, OPC, MCB and sqmm expanded); character and word TF-IDF with cosine
   similarity ranks all headings.
2. **Model (decision).** A language model reads the item and the top 30 candidates' official
   descriptions and picks one, or names a heading it knows the shortlist missed. Its answer must
   exist in the official master, so it cannot invent a code; anything else falls back to
   text matching.

## Results

| Split | Items | Method | Heading top-1 | Chapter top-1 | Text top-3 | Right answer in shortlist of 30 |
|---|---:|---|---:|---:|---:|---:|
| dev (tuning) | 29 | text matching | 37.9% | 65.5% | 58.6% | 82.8% |
| **test (held out)** | **85** | **text matching** | **54.1%** | **76.5%** | **68.2%** | **97.6%** |
| test (held out) | 85 | text matching + model | *not yet measured — needs an API key* | | | |

**Text matching alone does not reach 90%** (54.1% top-1 on the held-out set). Its job is the
shortlist, and there it does well: the correct heading is among the 30 candidates the model
reviews for 97.6% of held-out items, and the model may also name a heading outside them. So the
model stage *can* exceed 90%, but that is a ceiling, not a result, until it is measured.

## Caveats

- The benchmark was written and labelled for this project. Labels are verified against the
  official master, but a set labelled by an independent GST practitioner is the stronger proof.
- 85 test items give roughly ±5 percentage points of uncertainty at these accuracy levels.
- Headings, not full 6/8-digit codes: the 8-digit tariff line depends on specifications a
  quotation line often omits.
