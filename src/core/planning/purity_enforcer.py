from __future__ import annotations
from typing import Any, Dict, Iterable

from src.core.types.validation import validate_pure_structure
from src.core.types.errors import ValidationError

CognitiveOutput = Dict[str, Any]

# Structural guards against tool / LLM / side‑effect leakage
_FORBIDDEN_TOOL_KEYS: set[str] = {
    "tool",
    "tool_name",
    "tool_call",
    "tool_calls",
    "arguments",
    "capability",
}

_FORBIDDEN_LLM_KEYS: set[str] = {
    "model",
    "llm",
    "prompt",
    "temperature",
    "max_tokens",
    "top_p",
    "frequency_penalty",
    "presence_penalty",
}

# Things that usually indicate nondeterminism / side effects in cognitive output
_FORBIDDEN_EFFECT_KEYS: set[str] = {
    "timestamp",
    "created_at",
    "updated_at",
    "random_seed",
    "env",
    "environment",
    "file_path",
    "socket",
    "fd",
}


def _scan_for_forbidden_keys(
    obj: Any,
    *,
    path: str = "",
    forbidden_sets: Iterable[set[str]],
) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            for forbidden in forbidden_sets:
                if k in forbidden:
                    raise ValidationError(
                        f"Forbidden key '{k}' in cognitive output at path '{path or '<root>'}'"
                    )
            new_path = f"{path}.{k}" if path else k
            _scan_for_forbidden_keys(v, path=new_path, forbidden_sets=forbidden_sets)
    elif isinstance(obj, list):
        for idx, v in enumerate(obj):
            new_path = f"{path}[{idx}]"
            _scan_for_forbidden_keys(v, path=new_path, forbidden_sets=forbidden_sets)
    else:
        # Scalars are fine; validate_pure_structure will handle type purity.
        return


def enforce_cognitive_purity(output: CognitiveOutput) -> CognitiveOutput:
    """
    Enforce Stratum‑2 purity constraints on a cognitive output.

    Guarantees:
    - JSON‑pure structure (no objects, callables, file handles, etc.)
    - No embedded tool calls or capability envelopes
    - No embedded LLM calls or generation configs
    - No obvious side‑effect / nondeterministic fields (timestamps, env, etc.)

    This function is intentionally structural: it does not execute anything and
    does not mutate the provided output.
    """
    # 1. JSON‑purity: no non‑serialisable types, no callables, no objects.
    try:
        validate_pure_structure(output)
    except Exception as e:
        raise ValidationError(f"Cognitive output is not JSON‑pure: {e}")

    # 2. Structural scan for tool / LLM / side‑effect leakage.
    _scan_for_forbidden_keys(
        output,
        forbidden_sets=(
            _FORBIDDEN_TOOL_KEYS,
            _FORBIDDEN_LLM_KEYS,
            _FORBIDDEN_EFFECT_KEYS,
        ),
    )

    # If we reach here, the output is structurally pure.
    # Immutability + determinism are enforced by:
    # - treating this as a value (never mutating it)
    # - using it only inside immutable StepState / trace structures
    return output