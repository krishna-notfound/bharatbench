# Metrics

## Counted (reproducible)

- API tests collected: 306. Harness tests collected: 123. Web unit tests: 0.
- Agent tools: 13 (`api/app/voice/tools.py` `TOOL_SCHEMAS`). Profiles: see `api/app/profiles.py`.

## Measured (single observations, not benchmarks)

| What | Observation | How |
| :--- | :--- | :--- |
| Voice first audio, production, no tools | about 0.8 s | live WSS tests |
| Voice first audio, production, with tools | about 1.3-1.7 s | live WSS tests |
| 2-condition F-Droid run | 204 s before crawler v2, 167 s after | deployed stack |
| 3-condition NewPipe run | 342 s | deployed stack |

## Not measured

Finding precision/recall, false-positive rate, LLM explanation accuracy, STT/TTS accuracy per language, agent-test
pass/fail accuracy, real-user impact scores (`users_exposed` are assumptions), concurrency, cost.
