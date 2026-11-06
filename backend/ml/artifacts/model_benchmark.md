# Which AI model for which task — measured

Run on 6 Nov 2026 with `python -m ml.model_benchmark <vendor:model> <slug>` (raw results in
`model_benchmark/*.json`). Seven models were tested in parallel on the free tiers, each on four tasks of this project,
then the four finalists on tool calling. **Small samples** (5 quotations, 43 HSN items, 5 routing decisions, 4 emails):
treat the numbers as evidence for a choice, not as precise accuracies.

| Model | Extraction fields right (5 real quotations) | HSN heading accuracy (43 held-out items) | Routing: valid / agrees with policy | Leaked a competitor in 4 tempting emails | Notes |
|---|---:|---:|---:|---:|---|
| Gemini 3.1 Flash-Lite | 98.2% (55/56), 2.7 s | **100%** (43/43 answered), 4.8 s | 5/5, 3/5 (16 s) | not measured (calls rate-limited) | **Cannot call tools** on its OpenAI-compatible endpoint |
| Groq Qwen 3.8 27B | 100% on the 3 files it answered (2 rate-limited) | 97.7%, 3.1 s | 5/5, 4/5 (0.3 s) | 0/4 | Tool calls 3/3 |
| Groq gpt-oss-20b | 98.2% (55/56), 1.2 s | 81.4% | 5/5, 4/5 (0.6 s) | 0/4 | Tool calls 3/3 in 1.1 s |
| NVIDIA Nemotron 3.5 Bolt | 96.4% (54/56), 8.2 s | 86.0% | 5/5, 3/5 (0.7 s) | 0/4 | Tool calls 3/3 in 1.3 s |
| NVIDIA Nemotron 3 Ultra | 98.2%, **58.8 s** | invalid: model answered 15/43 (timeouts) | 3/5 valid | 0/3 | Too slow and unreliable |
| NVIDIA Nemotron 3.5 Lightning | invalid: 0/5 answered, 103 s | invalid: 0/43 answered | 0/5 | none produced | Unusable |
| Groq gpt-oss-120b | **invalid**: 0/5 answered | **invalid**: 1/43 answered | invalid | invalid | Daily token limit (200,000) already used up by earlier testing |

"Valid" counts only items the model actually answered; a rate-limited run silently falls back to text matching and
must not be read as the model's accuracy. Text matching alone scores 48.8% on this HSN subset.

## Decision

| Task | Model | Why |
|---|---|---|
| Extraction | Gemini 3.1 Flash-Lite | 98.2%, 2.7 s, all 5 answered by the model |
| HSN codes | Gemini 3.1 Flash-Lite | 100% on 43 items (98.8% on the full 85 earlier) |
| Supervisor routing and negotiation (tools, leak-safe) | Groq gpt-oss-20b | 0.6 s routing, 3/3 tool use, 0 leaks, its own token budget |
| Assistant (tools) | NVIDIA Nemotron 3.5 Bolt | 3/3 tool use in 1.3 s, no token ceiling seen |
| Council members | gpt-oss-20b, Nemotron Bolt, Gemini Flash-Lite | Three vendors; full council 2.6–3.2 s in three runs |
| Council monitor | Groq Qwen 3.8 27B | Fastest and steady, and different from every member |

## Limits found
- Groq free tier: 8,000 tokens/min and 200,000 tokens/day **per model**, 1,000 requests/day. gpt-oss-120b was drained
  by testing; a rolling window restores it.
- Gemini rejects tool-calling requests, so it is marked text-only and agents fall back instead of failing.
- Not tested here: the leak test for Gemini, and any model on documents beyond the five samples.
