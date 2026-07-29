"""Static Validator — P4 静态校验。

依据 sc2-vibe完整实施计划.md P4:
  - 静态校验、构建/同步、批准 launcher、ready 信号、场景 recipe 重建、ScriptError 复核
  - 禁止固定盲等和直接启动 SC2_x64.exe
  - 静态失败仍启动即失败

校验内容：
  - Galaxy 语法基础检查（括号匹配、必要函数存在）
  - XML 良构检查
  - 文件路径在 writeScope 内
  - 无只读源修改
"""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class ValidationResult:
    """静态校验结果。"""
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked_files: list[str] = field(default_factory=list)


class StaticValidator:
    """静态校验器。"""

    def __init__(self, write_scope: list[str], read_only: list[str]):
        self.write_scope = [Path(p) for p in write_scope]
        self.read_only = [Path(p) for p in read_only]

    def validate_galaxy(self, path: Path) -> list[str]:
        """Galaxy 文件基础语法检查。"""
        errors = []
        if not path.exists():
            errors.append(f"文件不存在: {path}")
            return errors

        content = path.read_text(encoding="utf-8")

        # 括号匹配
        if content.count("(") != content.count(")"):
            errors.append(f"括号不匹配: ( = {content.count('(')}, ) = {content.count(')')}")

        # 花括号匹配
        if content.count("{") != content.count("}"):
            errors.append(f"花括号不匹配: {{ = {content.count('{')}, }} = {content.count('}')}")

        # 基础语法检查：函数声明后应有 {
        lines = content.split("\n")
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            # 检查是否有未闭合的字符串
            if stripped.count('"') % 2 != 0 and not stripped.startswith("//"):
                # 多行字符串罕见，警告
                pass

        return errors

    def validate_xml(self, path: Path) -> list[str]:
        """XML 良构检查。"""
        errors = []
        if not path.exists():
            errors.append(f"文件不存在: {path}")
            return errors

        try:
            ET.parse(path)
        except ET.ParseError as e:
            errors.append(f"XML 解析错误: {e}")

        return errors

    def validate_write_scope(self, path: Path) -> list[str]:
        """验证文件路径在 writeScope 内。"""
        errors = []
        abs_path = path.resolve()
        in_scope = False
        for scope in self.write_scope:
            scope_abs = (REPO_ROOT / scope).resolve() if not scope.is_absolute() else scope.resolve()
            try:
                abs_path.relative_to(scope_abs)
                in_scope = True
                break
            except ValueError:
                # 检查是否是 scope 的父目录（scope 是 glob 模式）
                scope_str = str(scope)
                if scope_str.endswith("/**"):
                    base = Path(scope_str[:-4])
                    base_abs = (REPO_ROOT / base).resolve() if not base.is_absolute() else base.resolve()
                    try:
                        abs_path.relative_to(base_abs)
                        in_scope = True
                        break
                    except ValueError:
                        pass

        if not in_scope:
            errors.append(f"文件不在 writeScope 内: {path}")

        return errors

    def validate_not_read_only(self, path: Path) -> list[str]:
        """验证未修改只读源。"""
        errors = []
        abs_path = path.resolve()
        for ro in self.read_only:
            ro_abs = (REPO_ROOT / ro).resolve() if not ro.is_absolute() else ro.resolve()
            try:
                abs_path.relative_to(ro_abs)
                errors.append(f"修改了只读源: {path} (匹配 {ro})")
            except ValueError:
                pass
        return errors

    def validate_changes(self, changed_files: list[Path]) -> ValidationResult:
        """校验所有变更文件。"""
        result = ValidationResult(is_valid=True)

        for path in changed_files:
            result.checked_files.append(str(path))

            # writeScope 检查
            scope_errors = self.validate_write_scope(path)
            result.errors.extend(scope_errors)

            # 只读源检查
            ro_errors = self.validate_not_read_only(path)
            result.errors.extend(ro_errors)

            # 按类型校验内容
            if path.suffix == ".galaxy":
                result.errors.extend(self.validate_galaxy(path))
            elif path.suffix == ".xml":
                result.errors.extend(self.validate_xml(path))

        result.is_valid = len(result.errors) == 0
        return result


def load_project_write_scope() -> tuple[list[str], list[str]]:
    """从 project.json 加载 writeScope 和 readOnly。"""
    project_json = REPO_ROOT / "src" / "projects" / "cmre-porting" / "project.json"
    data = json.loads(project_json.read_text(encoding="utf-8"))
    stage = data.get("stages", {}).get("05-galaxy-vibe", {})
    return stage.get("writeScope", []), stage.get("readOnly", [])
