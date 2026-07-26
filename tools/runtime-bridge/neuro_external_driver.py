"""Gary/Neuro 外部动作驱动辅助工具。

这个入口只负责两件事：
1. 构造 NeuroIntegration.SC2Bank 的 `do_action.chat_message` 请求并 bump `game_state.active`。
2. 写回 bank 后轮询 `chat_message` flag 是否被运行中的 SC2 清为 0。

如果运行中的 SC2 没有重新读取外部写入的 bank，命令会返回 1，并把该结果作为
`CMRE-RUNTIME-003` 的证据，而不是误报成功。
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from html import escape
from pathlib import Path


DEFAULT_BANK_PATH = Path.home() / "Documents" / "StarCraft II" / "Banks" / "NeuroIntegration.SC2Bank"
FILE_OPS_WRITE_BIN = Path("c:/Users/22448/.trae-cn/skills/file-ops/scripts/trae-write-bin.ps1")


@dataclass(frozen=True)
class PreparedAction:
    old_active: int
    new_active: int
    message: str


def replace_or_insert_section(content: str, section_name: str, section_body: str) -> str:
    """替换指定 bank section；不存在时插入到 `</Bank>` 前。"""
    pattern = re.compile(
        rf'<Section name="{re.escape(section_name)}">.*?</Section>',
        re.DOTALL,
    )
    if pattern.search(content):
        return pattern.sub(section_body, content, count=1)
    if "</Bank>" not in content:
        raise ValueError("bank XML 缺少 </Bank> 结束标签")
    return content.replace("</Bank>", f"    {section_body}\n</Bank>", 1)


def bump_active(content: str) -> tuple[str, int, int]:
    """递增 `game_state.active`，用于触发 NeuroIntegration 的动作处理窗口。"""
    match = re.search(r'<Key name="active">\s*<Value int="(-?\d+)"\s*/?>', content)
    if not match:
        raise ValueError("bank XML 缺少 game_state.active")
    old_value = int(match.group(1))
    new_value = old_value + 1 if old_value < 2_000_000_000 else 1
    old_block = match.group(0)
    new_block = old_block.replace(f'<Value int="{old_value}"', f'<Value int="{new_value}"')
    return content.replace(old_block, new_block, 1), old_value, new_value


def build_action_section(action_name: str, args: list[str]) -> str:
    """生成一个 NeuroIntegration ``do_action`` 请求 section。"""
    if not re.fullmatch(r"[A-Za-z0-9_]+", action_name):
        raise ValueError("动作名只能包含字母、数字和下划线")
    keys = [
        f'        <Key name="{action_name}">\n'
        '            <Value flag="1"/>\n'
        '        </Key>'
    ]
    for index, value in enumerate(args, start=1):
        keys.append(
            f'        <Key name="{action_name}_arg_{index}">\n'
            f'            <Value string="{escape(value, quote=True)}"/>\n'
            '        </Key>'
        )
    return '<Section name="do_action">\n' + '\n'.join(keys) + '\n    </Section>'


def build_chat_action_section(message: str) -> str:
    """保留聊天请求构造，供旧调用方与测试使用。"""
    return build_action_section("chat_message", [message])


def prepare_chat_action(content: str, message: str) -> tuple[str, PreparedAction]:
    """返回写入 chat 动作后的 bank XML 与 active 变更摘要。"""
    with_action = replace_or_insert_section(content, "do_action", build_chat_action_section(message))
    updated, old_active, new_active = bump_active(with_action)
    return updated, PreparedAction(old_active=old_active, new_active=new_active, message=message)


def read_action_flag(content: str, action_name: str) -> str | None:
    """读取 ``do_action.<action_name>`` flag。"""
    match = re.search(
        rf'<Section name="do_action">.*?<Key name="{re.escape(action_name)}">\s*<Value flag="(\d)"',
        content,
        re.DOTALL,
    )
    return match.group(1) if match else None


def read_chat_flag(content: str) -> str | None:
    """读取 `do_action.chat_message` flag，返回 `"1"`、`"0"` 或 `None`。"""
    return read_action_flag(content, "chat_message")


def write_bank_via_file_ops(bank_path: Path, content: str) -> None:
    """通过 file-ops 二进制写入包装脚本写回最终 bank 文件。"""
    if not FILE_OPS_WRITE_BIN.exists():
        raise FileNotFoundError(f"file-ops 写入脚本不存在: {FILE_OPS_WRITE_BIN}")
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".xml") as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(FILE_OPS_WRITE_BIN),
            str(bank_path),
            "-FromTmp",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"trae-write-bin.ps1 写入失败: {result.stderr.strip()}")


def poll_action_consumed(bank_path: Path, action_name: str, timeout_seconds: float, interval_seconds: float = 0.5) -> bool:
    """轮询 bank，直到指定动作 flag 被 SC2 清为 0 或超时。"""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        time.sleep(interval_seconds)
        content = bank_path.read_text(encoding="utf-8")
        if read_action_flag(content, action_name) == "0":
            return True
    return False


def command_bank_chat(args: argparse.Namespace) -> int:
    bank_path = Path(args.bank)
    if not bank_path.exists():
        print(f"bank 文件不存在: {bank_path}", file=sys.stderr)
        return 2
    content = bank_path.read_text(encoding="utf-8")
    updated, prepared = prepare_chat_action(content, args.message)
    write_bank_via_file_ops(bank_path, updated)
    print(f"已写入 chat_message，active {prepared.old_active} -> {prepared.new_active}")
    if poll_action_consumed(bank_path, "chat_message", args.poll_seconds):
        print("chat_message flag 已被 SC2 清为 0，外部动作被消费。")
        return 0
    print("chat_message flag 未在时限内清为 0，运行中 SC2 可能没有消费外部 bank 写入。")
    return 1


def command_bank_order(args: argparse.Namespace) -> int:
    bank_path = Path(args.bank)
    if not bank_path.exists():
        print(f"bank 文件不存在: {bank_path}", file=sys.stderr)
        return 2
    content = bank_path.read_text(encoding="utf-8")
    section = build_action_section("issue_order", [args.unit_type, args.ability, args.target])
    updated = replace_or_insert_section(content, "do_action", section)
    updated, old_active, new_active = bump_active(updated)
    write_bank_via_file_ops(bank_path, updated)
    print(f"已写入 issue_order，active {old_active} -> {new_active}，unit={args.unit_type} ability={args.ability} target={args.target}")
    if poll_action_consumed(bank_path, "issue_order", args.poll_seconds):
        print("issue_order flag 已被 CMRE 清为 0，指令已由地图端接收。")
        return 0
    print("issue_order flag 未在时限内清为 0，运行中的 CMRE 可能未加载命令桥接库。")
    return 1


def command_status(args: argparse.Namespace) -> int:
    bank_path = Path(args.bank)
    if not bank_path.exists():
        print(f"bank 文件不存在: {bank_path}", file=sys.stderr)
        return 2
    content = bank_path.read_text(encoding="utf-8")
    active_match = re.search(r'<Key name="active">\s*<Value int="(-?\d+)"', content)
    active = active_match.group(1) if active_match else "?"
    print(f"active={active} chat_message={read_chat_flag(content)} mtime={os.path.getmtime(bank_path):.0f}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NeuroIntegration 外部动作驱动辅助工具")
    sub = parser.add_subparsers(dest="command", required=True)

    bank_chat = sub.add_parser("bank-chat", help="写入 do_action.chat_message 并轮询是否被 SC2 消费")
    bank_chat.add_argument("--bank", default=str(DEFAULT_BANK_PATH), help="NeuroIntegration.SC2Bank 路径")
    bank_chat.add_argument("--message", required=True, help="要发送的聊天内容")
    bank_chat.add_argument("--poll-seconds", type=float, default=6.0, help="等待 SC2 清 flag 的秒数")
    bank_chat.set_defaults(func=command_bank_chat)

    bank_order = sub.add_parser("bank-order", help="向 CMRE 玩家一的同类型单位下发点目标技能指令")
    bank_order.add_argument("--bank", default=str(DEFAULT_BANK_PATH), help="NeuroIntegration.SC2Bank 路径")
    bank_order.add_argument("--unit-type", required=True, help="目标单位的 catalog type，例如 Marine")
    bank_order.add_argument("--ability", required=True, help="技能 catalog id，例如 move、attack 或建造技能")
    bank_order.add_argument("--target", required=True, help='目标坐标，格式为 "x y"')
    bank_order.add_argument("--poll-seconds", type=float, default=6.0, help="等待地图端消费的秒数")
    bank_order.set_defaults(func=command_bank_order)

    status = sub.add_parser("status", help="打印 bank active 与 chat_message flag")
    status.add_argument("--bank", default=str(DEFAULT_BANK_PATH), help="NeuroIntegration.SC2Bank 路径")
    status.set_defaults(func=command_status)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
