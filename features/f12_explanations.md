# f12 — Evidence-grounded AI explanations, dedupe, baseline comparison

**Status:** Built (merged to main; see docs/FEATURE_MAP.md) | **Owner:** Sonnet `intelligence`

## Owns
`api/app/analyzer/explain.py`, `api/app/analyzer/dedupe.py`, `api/tests/analyzer/test_explain.py`, `test_dedupe.py`, and a small
hook in `api/app/pipeline.py` (dedupe before scoring; explain after scoring, best-effort, 30 s total budget).

## Behavior
- Dedupe: merge same-`rule_id` static findings in a run (e.g. 5× `sec.exported_component` → one finding listing the components;
  max severity; union evidence capped at 10). Runtime findings dedupe by (rule_id, profile_id, crash signature).
- Baseline comparison: runtime findings on non-baseline profiles get a description suffix comparing to baseline metrics when present.
- Explain: for the top 8 findings by score, call the LLM (OpenAI-compatible; settings `llm_base_url`/`llm_model`/`llm_api_key`,
  default Sarvam `https://api.sarvam.ai/v1`, `sarvam-105b`, auth header per `api/app/voice/SARVAM_NOTES.md`) with ONLY the finding
  JSON + evidence excerpts. Ask for strict JSON `{probable_cause, suggested_fix, developer_explanation}`. Reject output that names
  classes/files/URLs absent from the evidence; keep deterministic text on failure. Store as
  `Evidence(kind="note", excerpt=...)` labelled "AI explanation (based on the evidence above)"; update `probable_cause` /
  `suggested_fix` only when valid. Never invent results. If `llm_*` settings don't exist yet (f09 adds them), read
  `sarvam_api_key` and use the Sarvam defaults directly.

## Acceptance
pytest (LLM mocked with respx) + ruff; live run on the F-Droid APK with the real key shows explanations.
