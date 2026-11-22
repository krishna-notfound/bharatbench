# f17 - Multilingual agent

**Status:** Built (merged to main) | **Written after build (retro-spec)** | **Commits:** 077d24f

> This spec was written after the code, from the code and git history, on 2026-11-22. It records what exists, not
> what was planned. Anything not listed under Verified is not verified.

## What it does
The voice agent replies in the language of each message: 11 Sarvam STT and TTS languages plus Hinglish, with per-message detection and a language reminder after the history.

## Owned files
`api/app/voice/languages.py`, `api/app/voice/prompts.py`, `api/tests/voice/test_multilang.py`, `api/tests/voice/test_language_directive.py`

## Behaviour and invariants
- Explicit user preference wins over detection; technical terms stay in English.
- The language note is placed after the history so earlier turns cannot override it.

## Tests
`api/tests/voice/test_multilang.py` (10), `test_language_directive.py` (7).

## Verified / not verified
Verified: detection and directive logic. Not measured: STT/TTS quality per language.

## Status Log
- 2026-11-22 - retro-spec written; code and tests were already merged.
