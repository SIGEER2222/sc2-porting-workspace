"""Change Classifier — P4 变更分类器。

依据 sc2-vibe完整实施计划.md P4:
  - 任意 Galaxy/XML/Layout/资产/地形修改都属于冷循环
  - 分类变更类型决定冷循环处理方式

变更类型：
  - galaxy: .galaxy 文件修改（需重新编译 mod/map）
  - xml: GameData/*.xml 修改（需重新编译）
  - actor: Actor 相关 XML 修改（需重新编译）
  - layout: UI Layout 文件修改（需重新编译）
  - asset: 资产文件（贴图/模型/声音）修改（需重新打包）
  - terrain: 地形文件修改（需重新编辑器处理）
  - config: 配置文件修改（可能不需要冷循环）
  - unknown: 未识别类型
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


class ChangeType(str, Enum):
    GALAXY = "galaxy"
    XML = "xml"
    ACTOR = "actor"
    LAYOUT = "layout"
    ASSET = "asset"
    TERRAIN = "terrain"
    CONFIG = "config"
    UNKNOWN = "unknown"


class ColdHotClassification(str, Enum):
    """变更是否需要冷循环。"""
    COLD = "cold"  # 需要冷循环（重启 SC2 + 重新编译）
    HOT = "hot"    # 热循环即可（运行时操作）


@dataclass
class ChangeRecord:
    """单个文件变更记录。"""
    path: Path
    change_type: ChangeType
    classification: ColdHotClassification
    detail: str = ""


class ChangeClassifier:
    """变更分类器：根据文件路径和扩展名判断变更类型。"""

    # 扩展名到变更类型的映射
    EXTENSION_MAP = {
        ".galaxy": ChangeType.GALAXY,
        ".xml": ChangeType.XML,
        ".layout": ChangeType.LAYOUT,
        ".tga": ChangeType.ASSET,
        ".dds": ChangeType.ASSET,
        ".png": ChangeType.ASSET,
        ".m3": ChangeType.ASSET,
        ".ogg": ChangeType.ASSET,
        ".wav": ChangeType.ASSET,
        ".txt": ChangeType.CONFIG,
        ".json": ChangeType.CONFIG,
        ".SC2Map": ChangeType.TERRAIN,
        ".SC2Mod": ChangeType.UNKNOWN,
    }

    # 路径关键词到变更类型的映射（优先于扩展名）
    PATH_KEYWORD_MAP = {
        "ActorData": ChangeType.ACTOR,
        "Actor": ChangeType.ACTOR,
        "GameData": ChangeType.XML,
        "Layout": ChangeType.LAYOUT,
        "TriggerLibs": ChangeType.GALAXY,
        "Triggers": ChangeType.GALAXY,
        "t3Terrain": ChangeType.TERRAIN,
        "t3HeightMap": ChangeType.TERRAIN,
    }

    def classify(self, file_path: Path) -> ChangeRecord:
        """分类单个文件变更。"""
        path_str = str(file_path)
        ext = file_path.suffix

        # 1. 先按路径关键词分类
        change_type = ChangeType.UNKNOWN
        for keyword, ctype in self.PATH_KEYWORD_MAP.items():
            if keyword in path_str:
                change_type = ctype
                break

        # 2. 如果路径关键词没匹配，按扩展名分类
        if change_type == ChangeType.UNKNOWN:
            change_type = self.EXTENSION_MAP.get(ext, ChangeType.UNKNOWN)

        # 3. 判定冷/热
        # 所有文件修改都是冷循环（依据计划"任意 Galaxy/XML/Layout/资产/地形修改都属于冷循环"）
        classification = ColdHotClassification.COLD

        return ChangeRecord(
            path=file_path,
            change_type=change_type,
            classification=classification,
            detail=f"ext={ext} type={change_type.value}",
        )

    def classify_batch(self, paths: list[Path]) -> list[ChangeRecord]:
        """批量分类。"""
        return [self.classify(p) for p in paths]

    def needs_cold_reload(self, changes: list[ChangeRecord]) -> bool:
        """判断是否需要冷循环。"""
        return any(c.classification == ColdHotClassification.COLD for c in changes)

    def get_cold_changes(self, changes: list[ChangeRecord]) -> list[ChangeRecord]:
        """获取需要冷循环的变更。"""
        return [c for c in changes if c.classification == ColdHotClassification.COLD]


# ---- Galaxy fixture 与 XML fixture 定义 ----

def get_galaxy_fixture() -> dict:
    """Galaxy 冷循环 fixture：修改 Galaxy 文件后重新编译。"""
    return {
        "fixture_type": "galaxy",
        "description": "Galaxy 脚本修改冷循环 fixture",
        "example_changes": [
            "tools/galaxy-vibe/kernel/LibVibeKernel.galaxy",
        ],
        "requires_recompile": True,
        "requires_sc2_restart": True,
    }


def get_xml_fixture() -> dict:
    """XML 冷循环 fixture：修改 GameData XML 后重新编译。"""
    return {
        "fixture_type": "xml",
        "description": "GameData XML 修改冷循环 fixture",
        "example_changes": [
            "src/projects/cmre-porting/packages/Maps/亡者之夜.SC2Map/Attributes",
        ],
        "requires_recompile": True,
        "requires_sc2_restart": True,
    }


def get_actor_fixture() -> dict:
    """Actor 冷循环 fixture：修改 Actor XML 后重新编译。"""
    return {
        "fixture_type": "actor",
        "description": "Actor XML 修改冷循环 fixture",
        "example_changes": [
            "src/projects/cmre-porting/packages/Mods/Alenger3.SC2Mod/Base.SC2Data/GameData/ActorData.xml",
        ],
        "requires_recompile": True,
        "requires_sc2_restart": True,
    }
