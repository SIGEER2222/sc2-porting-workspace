"""把 ``reference/sc2-ally-bot/src`` 加入 sys.path，使 ``sc2_simulator`` 可被 import。

本模块不复制 sc2_simulator 源码，只做路径引导（import，非 fork）。
路径以本文件位置相对计算，不写绝对工作区路径到 committed 文件。
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]  # src/projects/cmre-porting/vibe -> repo root
_SIM_SRC = _REPO_ROOT / "reference" / "sc2-ally-bot" / "src"

_ensured = False


def ensure_simulator_on_path() -> None:
    """幂等：把 sc2_simulator 源码目录加入 sys.path。"""
    global _ensured
    if _ensured:
        return
    p = str(_SIM_SRC)
    if p not in sys.path:
        sys.path.insert(0, p)
    _ensured = True


ensure_simulator_on_path()
