"""Command-line launcher for shared multi-map PPO self-training.

Examples:
    python tools/train_multi_map.py --backend simulator
    python tools/train_multi_map.py --backend fake --iterations 2 --rollout-steps 16
    python tools/train_multi_map.py --resume artifacts/.../map-aware-policy.pt
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT_ROOT = REPO_ROOT / "src" / "projects" / "cmre-rl-training"
CMRE_PORTING_SRC = REPO_ROOT / "src" / "projects" / "cmre-porting"
CMRE_NEURO_SRC = REPO_ROOT / "src" / "projects" / "cmre-neuro-adapter"

for path in (PROJECT_ROOT, CMRE_NEURO_SRC, CMRE_PORTING_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from cmre_rl_training.training_cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
