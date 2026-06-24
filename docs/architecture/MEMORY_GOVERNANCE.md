# Memory Governance

The system uses several complementary techniques to keep LLM context windows manageable, prevent memory-store corruption, and maintain agent coherence over long sessions.

## Governance Layer

[`MemoryGovernance`](../../src/agent/memory/governance/memory_governance.py) is a pure validation and consistency-check layer that wraps the four memory stores (subgoal, segment, plan, drift):

- **Schema validation** — every write is checked for structural validity before it reaches the store.
- **State-transition rules** — subgoals must follow legal lifecycle transitions (e.g. `active → closed`, never `closed → active`).
- **Cross-store consistency** — segments, plans, and drift events all reference existing subgoal IDs; dangling references are rejected.
- **Normalisation** — timestamps and other free-form fields are coerced to canonical formats on write.
- **Periodic audit** — `check_consistency()` runs a full cross-store scan to detect latent corruption.

## Compaction Pipeline

[`CompactionOrchestrator`](../../src/agent/memory/compaction/compaction_orchestrator.py) reduces conversation-history token count by replacing older turns with an LLM-generated summary. It fires on one of three triggers:

| Trigger | Default threshold | Description |
|---|---|---|
| **Context pressure** | ≥ 80 % of context limit | Fires when input tokens approach the model's limit |
| **Turn count** | ≥ 10 user+assistant turn pairs | Periodic compaction on conversation length |
| **Subgoal closed** | Any newly CLOSED subgoal | Compacts when a sub-goal completes |

Once fired the pipeline:

1. Splits history into *compactable* (older turns) and *recent* (last N turns, default 4).
2. Checks a **SHA256 fingerprint** of the compactable portion — if unchanged since last compaction, the LLM call is skipped entirely (staleness guard).
3. Sends compactable turns to the LLM for summarisation (prose or structured JSON state extraction).
4. Replaces compactable entries with the summary.
5. Verifies **net token reduction** — if tokens didn't decrease, the original history is restored (rollback). This prevents pointless or lossy compactions.
6. Notifies the eviction orchestrator about any subgoals whose episodes were compacted.

## Eviction Pipeline

[`EvictionOrchestrator`](../../src/agent/memory/eviction/eviction_orchestrator.py) removes stale or completed entries from memory stores. Triggers include drift-buffer overflow, subgoal completion, and post-compaction subgoal cleanup.

## Configuration

All thresholds are configurable via YAML (see `CompactionConfig` in [compaction_types.py](../../src/agent/memory/compaction/compaction_types.py)) or by passing a config dictionary at composition-root setup.
