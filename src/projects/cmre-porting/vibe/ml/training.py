"""Deterministic PyTorch imitation training and evaluation."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Mapping

import torch
from torch import nn
from torch.utils.data import DataLoader

from .dataset import P2IntentDataset, build_examples
from .model import P2AllyPolicyNet, save_checkpoint
from .schema import HEAD_LABELS


def _evaluate(model: P2AllyPolicyNet, dataset: P2IntentDataset, batch_size: int) -> dict:
    loader = DataLoader(dataset, batch_size=max(1, int(batch_size)), shuffle=False)
    criterion = nn.CrossEntropyLoss()
    totals = defaultdict(float)
    correct = defaultdict(int)
    count = 0
    was_training = model.training
    model.eval()
    with torch.no_grad():
        for features, targets in loader:
            outputs = model(features)
            batch_count = int(features.shape[0])
            count += batch_count
            for head in HEAD_LABELS:
                totals[head] += float(criterion(outputs[head], targets[head]).item()) * batch_count
                correct[head] += int((outputs[head].argmax(dim=-1) == targets[head]).sum().item())
    if was_training:
        model.train()
    metrics = {f"{head}_accuracy": correct[head] / max(1, count) for head in HEAD_LABELS}
    metrics["accuracy_mean"] = sum(metrics.values()) / len(HEAD_LABELS)
    metrics["loss_mean"] = sum(totals.values()) / max(1, count)
    metrics["samples"] = count
    return metrics


def train_pytorch_policy(
    train_records: Iterable[Mapping],
    holdout_records: Iterable[Mapping],
    *,
    epochs: int = 24,
    batch_size: int = 32,
    hidden_dim: int = 128,
    learning_rate: float = 0.001,
    seed: int = 7,
    checkpoint_path: str | None = None,
) -> tuple[P2AllyPolicyNet, dict]:
    torch.manual_seed(int(seed))
    torch.set_num_threads(1)
    train_dataset = P2IntentDataset(build_examples(train_records))
    holdout_dataset = P2IntentDataset(build_examples(holdout_records))
    model = P2AllyPolicyNet(hidden_dim=hidden_dim, seed=seed)
    optimizer = torch.optim.AdamW(model.parameters(), lr=float(learning_rate))
    criterion = nn.CrossEntropyLoss()
    loader = DataLoader(
        train_dataset, batch_size=max(1, int(batch_size)), shuffle=True,
        generator=torch.Generator().manual_seed(int(seed)),
    )
    losses: list[float] = []
    for _epoch in range(max(1, int(epochs))):
        model.train()
        total = 0.0
        samples = 0
        for features, targets in loader:
            optimizer.zero_grad(set_to_none=True)
            outputs = model(features)
            loss = sum(criterion(outputs[head], targets[head]) for head in HEAD_LABELS)
            loss.backward()
            optimizer.step()
            batch_count = int(features.shape[0])
            total += float(loss.item()) * batch_count
            samples += batch_count
        losses.append(total / max(1, samples))
    train_metrics = _evaluate(model, train_dataset, batch_size)
    holdout_metrics = _evaluate(model, holdout_dataset, batch_size)
    metadata = {
        "epochs": max(1, int(epochs)), "batch_size": max(1, int(batch_size)),
        "learning_rate": float(learning_rate), "seed": int(seed),
        "loss_start": float(losses[0]), "loss_end": float(losses[-1]),
        "loss_decreased": bool(losses[-1] < losses[0]),
        "train": train_metrics, "holdout": holdout_metrics,
    }
    if checkpoint_path is not None:
        save_checkpoint(model, checkpoint_path, training=metadata)
    return model, metadata
