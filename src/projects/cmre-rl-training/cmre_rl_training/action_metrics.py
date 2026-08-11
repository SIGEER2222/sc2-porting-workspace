"""Action distribution and illegal-action metrics for RL reports.

The autonomous-completion plan requires every training / live report to include
the policy's action distribution, illegal-action rate, and related summary
statistics. An action is *illegal* when the policy selects it but the per-step
action mask disallows it (no owned actor / unaffordable / no target). Illegal
actions are expected to be rare because :func:`collect_rollout` already masks
them before sampling; a non-zero rate indicates a mask/grounding regression.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Mapping, Sequence

from .action_space import ACTION_NAMES, NUM_ACTIONS


def summarize_rollout_actions(
    buffer: Any,
    *,
    action_names: Sequence[str] = ACTION_NAMES,
) -> dict[str, Any]:
    """Summarize the action choices recorded in a :class:`RolloutBuffer`.

    Parameters
    ----------
    buffer
        Object exposing ``_steps`` (a list of ``_Step`` with ``action`` and
        ``mask`` ndarrays). ``RolloutBuffer`` satisfies this contract.
    action_names
        Names indexed by action id; used to label the distribution.

    Returns a dict with the distribution, normalized distribution, illegal-action
    count/rate, distinct actions used, empirical action entropy (nats), and the
    top actions by frequency.
    """

    steps: Sequence[Any] = list(getattr(buffer, "_steps", ()))
    n = len(steps)
    names = list(action_names)
    dist: dict[str, int] = {name: 0 for name in names}

    illegal = 0
    for step in steps:
        action_arr = getattr(step, "action", None)
        if action_arr is None:
            continue
        idx = int(getattr(action_arr, "flatten", lambda: action_arr)().tolist()[0]) \
            if hasattr(action_arr, "flatten") else int(action_arr)
        name = names[idx] if 0 <= idx < len(names) else str(idx)
        dist[name] = dist.get(name, 0) + 1
        mask = getattr(step, "mask", None)
        if mask is not None and (idx < 0 or idx >= len(mask) or not bool(mask[idx])):
            illegal += 1

    normalized = {key: (count / n if n else 0.0) for key, count in dist.items()}
    distinct = sum(1 for count in dist.values() if count > 0)

    entropy = 0.0
    if n:
        for value in normalized.values():
            if value > 0.0:
                entropy -= value * math.log(value)

    top = sorted(
        ((name, count) for name, count in dist.items() if count > 0),
        key=lambda kv: kv[1],
        reverse=True,
    )[:5]

    return {
        "n_steps": n,
        "action_distribution": dist,
        "action_distribution_normalized": normalized,
        "illegal_action_count": illegal,
        "illegal_action_rate": (illegal / n) if n else 0.0,
        "distinct_actions_used": distinct,
        "total_action_slots": len(names),
        "action_entropy_nats": entropy,
        "top_actions": [{"action": name, "count": count} for name, count in top],
    }


def aggregate_action_summaries(
    summaries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Merge several per-run summaries into one aggregated summary.

    Counts are summed; rates and entropy are recomputed from the merged counts.
    """

    total_steps = 0
    total_illegal = 0
    merged: dict[str, int] = {}
    top_actions: list[dict[str, Any]] = []

    for summary in summaries:
        total_steps += int(summary.get("n_steps", 0))
        total_illegal += int(summary.get("illegal_action_count", 0))
        for name, count in (summary.get("action_distribution") or {}).items():
            merged[name] = merged.get(name, 0) + int(count)

    normalized = {key: (count / total_steps if total_steps else 0.0) for key, count in merged.items()}
    distinct = sum(1 for count in merged.values() if count > 0)
    entropy = 0.0
    if total_steps:
        for value in normalized.values():
            if value > 0.0:
                entropy -= value * math.log(value)
    top = sorted(
        ((name, count) for name, count in merged.items() if count > 0),
        key=lambda kv: kv[1],
        reverse=True,
    )[:5]

    return {
        "n_steps": total_steps,
        "action_distribution": merged,
        "action_distribution_normalized": normalized,
        "illegal_action_count": total_illegal,
        "illegal_action_rate": (total_illegal / total_steps) if total_steps else 0.0,
        "distinct_actions_used": distinct,
        "total_action_slots": len(merged) or NUM_ACTIONS,
        "action_entropy_nats": entropy,
        "top_actions": [{"action": name, "count": count} for name, count in top],
    }


def summarize_action_trace(trace: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize live dispatch success and failed/illegal action attempts."""

    entries = [entry for entry in trace if isinstance(entry, Mapping)]
    total = len(entries)
    distribution: dict[str, int] = {name: 0 for name in ACTION_NAMES}
    for entry in entries:
        name = str(entry.get("action_id", "unknown"))
        distribution[name] = distribution.get(name, 0) + 1
    success_count = sum(bool(entry.get("success")) for entry in entries)
    failure_count = total - success_count
    translated_failures = sum(entry.get("translated") is False for entry in entries)
    error_count = sum(
        bool(entry.get("error")) or bool(entry.get("errors")) for entry in entries
    )
    return {
        "attempt_count": total,
        "success_count": success_count,
        "failure_count": failure_count,
        "translated_failure_count": translated_failures,
        "error_count": error_count,
        "action_success_rate": (success_count / total) if total else 0.0,
        "illegal_action_count": failure_count,
        "illegal_action_rate": (failure_count / total) if total else 0.0,
        "action_distribution": distribution,
    }


__all__ = [
    "ACTION_NAMES",
    "aggregate_action_summaries",
    "summarize_action_trace",
    "summarize_rollout_actions",
]
