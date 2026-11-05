# Model Usage Report

## Run covered

This report covers the final full-dataset generation performed with:

```bash
python3 code/main.py
```

That entry point uses the local Python identity resolver, evidence indexer, and deterministic audit rules. It does not call Groq, Google Gemini, or another model provider. It reads the already-extracted image evidence cache when present. Therefore the measured model usage and model cost for this 518-request generation run are zero.

| Provider | Model | Calls during full-dataset run | Input tokens | Output tokens | Total tokens | Estimated cost |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| None (local deterministic pipeline) | None | 0 | 0 | 0 | 0 | $0.00 |

Average model usage per request: **0 calls, 0 input tokens, 0 output tokens, and $0.00** across 518 requests. This is model usage only; local CPU time and file I/O are not token usage.

## Cached OCR provenance

The evidence indexer can consume cached OCR JSON under `dataset/evidence/images_extracted/`. The 11 cache files currently contain aggregate Google Gemini API usage metadata of **12,434 prompt tokens** and **7,801 candidate tokens** (20,235 total tokens) from the earlier extraction process. Those API requests were not made during the full-dataset run above. The cache metadata does not record the model name, and the extraction script permits a `GEMINI_MODEL` override, so this repository cannot establish which exact model produced each cache entry or reliably calculate the historical cost. Those historical tokens and costs are intentionally excluded from the full-run totals.

The separate `/api/ai-agent/investigate` and `/api/ai-agent/chat` features may call Groq when configured. They were not invoked by `code/main.py` and are not included in this usage total. Their per-request usage should be captured from provider response metadata before reporting it.

## Reproducibility and credentials

To reproduce the reported full-run usage, run `python3 code/main.py` without invoking image extraction or the interactive AI endpoints. The pipeline requires no model API key. Never put credentials in this report or in the submission archive.
