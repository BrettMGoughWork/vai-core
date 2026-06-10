# Release 0.1 Signed‑Off Checklist

Phase 2.18.4 — Verified at 2025‑01‑01 (baseline date).

## 1. All S2 Contract Tests Pass

- [x] `tests/unit/core/planning/contracts/` — 79 tests passing
- [x] `tests/integration/test_s2_s3_roundtrip.py` — S2↔S3 boundary tests
- Verified with: `pytest tests/ -q` → 923 passed, 2 skipped

## 2. All S2 Integration Tests Pass

- [x] `tests/integration/test_full_pipeline.py` — 29 tests, all passing
  - Plan generation, breakage detection, repair, contract serialization, end‑to‑end pipeline
- Verified with: `pytest tests/integration/test_full_pipeline.py -q` → 29 passed

## 3. Manual LLM Tests (3 Representative Prompts)

All three manual tests have been validated with real LLM (`ENABLE_REAL_LLM=True`):

| Test | File | What It Proves |
|------|------|---------------|
| S1 PromptResponse round‑trip | `tests/manual/test_llm_prompt_response_minimal.py` | LLM produces valid PromptResponse JSON |
| S2 plan → LLM → S2 update | `tests/manual/test_tiny_s2_plan_real_llm.py` | Full S1→S2 round‑trip, 1 subgoal, 1 segment |
| S3 runtime smoke | `tests/manual/test_s3_smoke.py` | Capability dispatch and runtime plumbing |

Run manually with:
```bash
python tests/manual/test_llm_prompt_response_minimal.py
python tests/manual/test_tiny_s2_plan_real_llm.py
python tests/manual/test_s3_smoke.py
```

## 4. `ENABLE_REAL_LLM` Kill‑Switch Honoured

- [x] Defaults to `False` in `src/core/planning/s1_contract/s1_real_client.py:26`
- [x] Checked at `call_llm()` (`s1_real_client.py:58`) — raises `RuntimeError` when off
- [x] Checked at `call_s1_backend()` (`s1_client.py:147`) — returns structured error when off
- [x] Verified by test: `tests/e2e/test_llm_on_smoke.py::test_default_kill_switch_is_false`
- [x] Verified by test: `tests/e2e/test_llm_on_smoke.py::test_call_llm_raises_when_kill_switch_off`
- [x] All manual tests restore the kill‑switch after enabling it

## 5. No Regressions in S1 or S3 Pipeline

- [x] Full test suite: `pytest tests/ -q` → 923 passed, 2 skipped, 0 failures
- [x] S1 tests: all passing (core, types, s1_contract, skills)
- [x] S3 tests: all passing (capabilities, runtime, conformance)
- [x] Only known deprecation warning: `datetime.utcnow()` (non‑blocking)

## SLO Baselines (from 2.18.3)

| Operation | Mean (ms) | P95 (ms) | P99 (ms) |
|-----------|-----------|----------|----------|
| plan_generation | 0.273 | 0.461 | 0.547 |
| breakage_detection | 0.024 | 0.024 | 0.037 |
| repair | 0.119 | 0.181 | 0.210 |
| contract_serialization | 0.005 | 0.005 | 0.012 |
| end_to_end_plan_detect | 0.281 | 0.446 | 0.461 |

SLO targets (p95 × 2x headroom):
- Tₚ (plan): < 1.0 ms
- Tₑ (detect): < 0.1 ms
- Tᵣ (repair): < 0.4 ms

## Sign‑Off

- [x] All automated tests passing
- [x] Manual LLM tests documented and runnable
- [x] Kill‑switch verified
- [x] SLO baselines captured
- [x] Performance benchmarks operational

**Release 0.1 S2 pipeline is ready.**
