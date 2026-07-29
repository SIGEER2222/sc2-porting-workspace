"""Scenario Recipe — P4 场景重建 recipe。

依据 sc2-vibe完整实施计划.md P4:
  - 冷循环后自动重建 recipe -> 截图/状态通过
  - 场景 recipe 重建确保冷循环后测试场景一致

Recipe 定义：
  - 起始单位创建
  - 资源设置
  - 镜头固定
  - 断言序列
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def get_default_scenario_recipe() -> dict[str, Any]:
    """默认场景 recipe：亡者之夜 × TerranAlenger3 基础测试场景。

    冷循环后执行此 recipe 重建测试场景。
    """
    return {
        "recipe_id": "cold-reload-default",
        "description": "冷循环后场景重建 recipe（亡者之夜 × TerranAlenger3）",
        "steps": [
            {"action": "reset", "request_id": "cold-reset"},
            {"action": "set_resource", "player": 1, "resource": "minerals", "value": 5000, "request_id": "cold-set-minerals"},
            {"action": "set_resource", "player": 1, "resource": "vespene", "value": 5000, "request_id": "cold-set-vespene"},
            {"action": "spawn", "unit_type": "Marine", "count": 3, "player": 1, "request_id": "cold-spawn-marine"},
            {"action": "assert", "kind": "exists", "unit_type": "Marine", "player": 1, "request_id": "cold-spawn-marine", "id": "cold-assert-exists", "expected_verdict": "passed"},
            {"action": "assert", "kind": "count", "unit_type": "Marine", "player": 1, "expected": 3, "request_id": "cold-spawn-marine", "id": "cold-assert-count-3", "expected_verdict": "passed"},
        ],
        "expected_outcome": {
            "all_assertions_passed": True,
            "marine_count": 3,
            "p1_minerals": 5000,
            "p1_vespene": 5000,
        },
    }


def get_galaxy_fixture_recipe() -> dict[str, Any]:
    """Galaxy fixture 冷循环 recipe：修改 Galaxy 后验证 Kernel 仍工作。"""
    return {
        "recipe_id": "cold-galaxy-fixture",
        "description": "Galaxy fixture 冷循环验证",
        "fixture_type": "galaxy",
        "pre_reload": {
            "change_files": ["tools/galaxy-vibe/kernel/LibVibeKernel.galaxy"],
            "expected_static_validation": "passed",
        },
        "post_reload_steps": [
            {"action": "reset", "request_id": "galaxy-fixture-reset"},
            {"action": "spawn", "unit_type": "Marine", "count": 1, "player": 1, "request_id": "galaxy-fixture-spawn"},
            {"action": "assert", "kind": "exists", "unit_type": "Marine", "player": 1, "request_id": "galaxy-fixture-spawn", "id": "gf-assert-01", "expected_verdict": "passed"},
            {"action": "ping", "request_id": "galaxy-fixture-ping"},
        ],
        "expected_outcome": {
            "static_validation_passed": True,
            "launcher_exit_code": 0,
            "no_new_script_errors": True,
            "kernel_responsive": True,
        },
    }


def get_xml_fixture_recipe() -> dict[str, Any]:
    """XML fixture 冷循环 recipe：修改 XML 后验证加载正确。"""
    return {
        "recipe_id": "cold-xml-fixture",
        "description": "XML fixture 冷循环验证",
        "fixture_type": "xml",
        "pre_reload": {
            "change_files": ["src/projects/cmre-porting/packages/Maps/亡者之夜.SC2Map/Attributes"],
            "expected_static_validation": "passed",
        },
        "post_reload_steps": [
            {"action": "reset", "request_id": "xml-fixture-reset"},
            {"action": "spawn", "unit_type": "Marine", "count": 1, "player": 1, "request_id": "xml-fixture-spawn"},
            {"action": "assert", "kind": "exists", "unit_type": "Marine", "player": 1, "request_id": "xml-fixture-spawn", "id": "xf-assert-01", "expected_verdict": "passed"},
        ],
        "expected_outcome": {
            "static_validation_passed": True,
            "launcher_exit_code": 0,
            "no_new_script_errors": True,
            "map_loaded_successfully": True,
        },
    }


def save_recipe(recipe: dict[str, Any], out_dir: Path) -> Path:
    """保存 recipe 到文件。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{recipe['recipe_id']}.json"
    path.write_text(json.dumps(recipe, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
