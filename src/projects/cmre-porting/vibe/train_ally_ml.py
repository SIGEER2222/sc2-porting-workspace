"""Train and validate the bounded P2 ally imitation model.

The command deliberately has two gates:

1. held-out public-observation classification, with a seed split;
2. a real full-game deterministic simulator run using the loaded checkpoint.

Neither gate claims that a single-client SC2 Computer slot is externally
controlled. Native runtime evidence remains a separate launcher concern.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from .ladder_ai import run_ladder_batch, run_ladder_game
from .ml_policy import (
    FEATURE_NAMES,
    MODE_LABELS,
    MLPModeModel,
    make_public_expert_dataset,
    samples_from_records,
)
from .ml.encoder import FEATURE_SCHEMA, feature_schema_hash
from .ml.model import MODEL_SCHEMA, load_checkpoint
from .ml.training import train_pytorch_policy


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "artifacts"
    / "projects"
    / "cmre-porting"
    / "stage25-ai-ally-capability-completion"
    / "ml-ally-policy-20260803"
)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n")


def train_and_validate(
    output_dir: str | Path = DEFAULT_OUTPUT,
    *,
    train_seeds: tuple[int, ...] = (42, 7),
    holdout_seeds: tuple[int, ...] = (99,),
    samples_per_seed: int = 180,
    epochs: int = 120,
    max_loops: int = 6000,
) -> dict:
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    records = make_public_expert_dataset(
        (*train_seeds, *holdout_seeds), samples_per_seed=samples_per_seed
    )
    train_records = [record for record in records if record["seed"] in train_seeds]
    holdout_records = [record for record in records if record["seed"] in holdout_seeds]
    train_samples = samples_from_records(train_records)
    holdout_samples = samples_from_records(holdout_records)

    model = MLPModeModel(hidden_dim=40, seed=7)
    train_metrics = model.fit(train_samples, epochs=epochs, learning_rate=0.08, seed=7)
    train_eval = model.evaluate(train_samples)
    holdout_eval = model.evaluate(holdout_samples)
    checkpoint = model.save(output / "ally-mode-mlp.json")
    _write_jsonl(output / "expert-public-observations.jsonl", records)

    simulator = run_ladder_game(
        seed=holdout_seeds[0],
        max_loops=max_loops,
        replay_dir=output / "simulator-replay",
        mode_model=MLPModeModel.load(checkpoint),
    )
    simulator_report = simulator.to_dict()
    simulator_multiseed = run_ladder_batch(
        seeds=(42, 7, 99),
        max_loops=max_loops,
        replay_dir=output / "simulator-multiseed",
        mode_model=MLPModeModel.load(checkpoint),
    )
    simulator_runs = list(simulator_multiseed.get("runs", ()))
    checks = {
        "feature_schema_stable": len(FEATURE_NAMES) == 28,
        "label_schema_stable": tuple(MODE_LABELS) == (
            "follow", "regroup", "defend_base", "assist_attack", "retreat", "hold"
        ),
        "loss_decreased": bool(train_metrics["loss_decreased"]),
        "heldout_accuracy": float(holdout_eval["accuracy"]) >= 0.80,
        "model_inference_used": int(simulator.ml_decision_count) > 0,
        "simulator_victory": bool(simulator.victory),
        "simulator_no_dispatch_errors": not bool(simulator.error_breakdown),
        "simulator_multiseed_victory": bool(simulator_multiseed.get("status") == "PASS"),
        "simulator_multiseed_model_used": all(
            int(run.get("ml_decision_count", 0)) > 0 for run in simulator_runs
        ),
    }
    report = {
        "schema": "cmre-ally-ml-training-report.v1",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "evidence_type": "simulator",
        "runtime_claim": "simulator only; native SC2 Computer control is not claimed",
        "model": {
            "schema": model.schema,
            "checkpoint": str(checkpoint.relative_to(REPO_ROOT)).replace("\\", "/"),
            "weights_sha256": model.to_dict()["weights_sha256"],
            "feature_names": list(FEATURE_NAMES),
            "labels": list(MODE_LABELS),
            "training": train_metrics,
        },
        "dataset": {
            "source": "public_observation_expert_rollout",
            "train_seeds": list(train_seeds),
            "holdout_seeds": list(holdout_seeds),
            "train_samples": len(train_samples),
            "holdout_samples": len(holdout_samples),
            "train_eval": train_eval,
            "holdout_eval": holdout_eval,
        },
        "simulator": {
            "seed": int(holdout_seeds[0]),
            "ml_decision_count": int(simulator.ml_decision_count),
            "status": simulator.status,
            "victory": simulator.victory,
            "end_loop": simulator.end_loop,
            "end_reason": simulator.end_reason,
            "error_breakdown": simulator.error_breakdown,
            "replay_path": simulator.replay_path,
            "replay_html_path": simulator.replay_html_path,
        },
        "simulator_multiseed": {
            "seeds": [42, 7, 99],
            "status": simulator_multiseed.get("status"),
            "runs": [
                {
                    "seed": run.get("pressure_summary", {}).get("seed", seed),
                    "status": run.get("status"),
                    "victory": run.get("victory"),
                    "end_loop": run.get("end_loop"),
                    "ml_decision_count": run.get("ml_decision_count"),
                    "error_breakdown": run.get("error_breakdown"),
                }
                for seed, run in zip((42, 7, 99), simulator_runs)
            ],
        },
        "checks": checks,
    }
    (output / "training-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def train_and_validate_pytorch(
    output_dir: str | Path = DEFAULT_OUTPUT.parent / "ml-ally-policy-pytorch",
    *,
    train_seeds: tuple[int, ...] = (42, 7),
    holdout_seeds: tuple[int, ...] = (99,),
    samples_per_seed: int = 180,
    epochs: int = 48,
    max_loops: int = 6000,
) -> dict:
    """Train the selected multi-head PyTorch policy and validate the simulator path."""

    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    records = make_public_expert_dataset(
        (*train_seeds, *holdout_seeds), samples_per_seed=samples_per_seed
    )
    train_records = [record for record in records if record["seed"] in train_seeds]
    holdout_records = [record for record in records if record["seed"] in holdout_seeds]
    checkpoint = output / "ally-intent.pt"
    model, training = train_pytorch_policy(
        train_records,
        holdout_records,
        epochs=epochs,
        checkpoint_path=str(checkpoint),
    )
    loaded_model = load_checkpoint(checkpoint)
    _write_jsonl(output / "expert-public-observations.jsonl", records)
    simulator = run_ladder_game(
        seed=holdout_seeds[0],
        max_loops=max_loops,
        replay_dir=output / "simulator-replay",
        mode_model=loaded_model,
    )
    simulator_multiseed = run_ladder_batch(
        seeds=(42, 7, 99),
        max_loops=max_loops,
        replay_dir=output / "simulator-multiseed",
        mode_model=loaded_model,
    )
    simulator_runs = list(simulator_multiseed.get("runs", ()))
    holdout = training["holdout"]
    checks = {
        "feature_schema_stable": feature_schema_hash() and FEATURE_SCHEMA == "cmre-ally-observation.v2",
        "model_schema_stable": MODEL_SCHEMA == "cmre-ally-intent-pytorch.v2",
        "loss_decreased": bool(training["loss_decreased"]),
        "all_heads_present": all(
            f"{head}_accuracy" in holdout for head in ("economy", "production", "tactical", "command")
        ),
        "holdout_accuracy": float(holdout["accuracy_mean"]) >= 0.80,
        "model_inference_used": int(simulator.ml_decision_count) > 0,
        "simulator_victory": bool(simulator.victory),
        "simulator_no_dispatch_errors": not bool(simulator.error_breakdown),
        "simulator_multiseed_victory": bool(simulator_multiseed.get("status") == "PASS"),
        "simulator_multiseed_model_used": all(
            int(run.get("ml_decision_count", 0)) > 0 for run in simulator_runs
        ),
    }
    report = {
        "schema": "cmre-ally-pytorch-training-report.v2",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "evidence_type": "simulator",
        "runtime_claim": "simulator only; native SC2 Computer control is not claimed",
        "framework": {
            "name": "PyTorch",
            "version": __import__("torch").__version__,
            "device": "cpu",
        },
        "model": {
            "schema": MODEL_SCHEMA,
            "feature_schema": FEATURE_SCHEMA,
            "feature_schema_hash": feature_schema_hash(),
            "checkpoint": str(checkpoint.relative_to(REPO_ROOT)).replace("\\", "/"),
            "checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
            "training": training,
        },
        "dataset": {
            "source": "public_observation_expert_rollout",
            "train_seeds": list(train_seeds),
            "holdout_seeds": list(holdout_seeds),
            "train_samples": len(train_records),
            "holdout_samples": len(holdout_records),
            "episode_split": True,
        },
        "simulator": {
            "seed": int(holdout_seeds[0]),
            "ml_decision_count": int(simulator.ml_decision_count),
            "status": simulator.status,
            "victory": simulator.victory,
            "end_loop": simulator.end_loop,
            "end_reason": simulator.end_reason,
            "error_breakdown": simulator.error_breakdown,
            "replay_path": simulator.replay_path,
            "replay_html_path": simulator.replay_html_path,
        },
        "simulator_multiseed": {
            "seeds": [42, 7, 99],
            "status": simulator_multiseed.get("status"),
            "runs": [
                {
                    "seed": run.get("pressure_summary", {}).get("seed", seed),
                    "status": run.get("status"),
                    "victory": run.get("victory"),
                    "end_loop": run.get("end_loop"),
                    "ml_decision_count": run.get("ml_decision_count"),
                    "error_breakdown": run.get("error_breakdown"),
                }
                for seed, run in zip((42, 7, 99), simulator_runs)
            ],
        },
        "checks": checks,
    }
    (output / "training-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train and validate the P2 ally policy")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--samples-per-seed", type=int, default=180)
    parser.add_argument("--epochs", type=int, default=48)
    parser.add_argument("--max-loops", type=int, default=6000)
    parser.add_argument("--backend", choices=("pytorch", "legacy"), default="pytorch")
    parser.add_argument("--quick", action="store_true", help="smaller training set and simulator budget")
    args = parser.parse_args(argv)
    if args.quick:
        args.samples_per_seed = min(args.samples_per_seed, 48)
        args.epochs = min(args.epochs, 45)
        args.max_loops = min(args.max_loops, 1200)
    if args.backend == "legacy":
        report = train_and_validate(
            args.out,
            samples_per_seed=max(12, args.samples_per_seed),
            epochs=max(1, args.epochs),
            max_loops=max(1, args.max_loops),
        )
    else:
        report = train_and_validate_pytorch(
            args.out,
            samples_per_seed=max(12, args.samples_per_seed),
            epochs=max(1, args.epochs),
            max_loops=max(1, args.max_loops),
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
