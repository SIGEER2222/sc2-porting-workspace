"""方案 2：NeuroIntegration Bank watchdog 实时监听器。

监听 NeuroIntegration.SC2Bank 文件变化，实时输出 game_context 中的探针数据。
不依赖 SC2 API，与 CMRE mod 完全兼容。
"""
from __future__ import annotations

import argparse
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False


DEFAULT_BANK = Path.home() / "Documents" / "StarCraft II" / "Banks" / "NeuroIntegration.SC2Bank"


def parse_bank(bank_path: Path) -> dict:
    """解析 Bank 文件，返回 {section: {key: value}} 字典。"""
    if not bank_path.exists():
        return {}
    try:
        tree = ET.parse(bank_path)
    except ET.ParseError:
        return {}
    root = tree.getroot()
    parsed = {}
    for section in root.findall("Section"):
        section_name = section.get("name", "")
        if not section_name:
            continue
        section_dict = {}
        for key in section.findall("Key"):
            key_name = key.get("name", "")
            value_node = key.find("Value")
            if value_node is None:
                continue
            if "flag" in value_node.attrib:
                section_dict[key_name] = value_node.attrib["flag"] == "1"
            elif "int" in value_node.attrib:
                try:
                    section_dict[key_name] = int(value_node.attrib["int"])
                except ValueError:
                    section_dict[key_name] = value_node.attrib["int"]
            elif "string" in value_node.attrib:
                section_dict[key_name] = value_node.attrib["string"]
            elif "text" in value_node.attrib:
                section_dict[key_name] = value_node.attrib["text"]
        parsed[section_name] = section_dict
    return parsed


def format_context_output(bank_data: dict, prev_context: dict) -> list[str]:
    """提取 game_context 中新增/变化的 key，输出人类可读文本。"""
    lines = []
    game_context = bank_data.get("game_context", {})
    if not game_context:
        return lines

    # 新增或变化的 key
    for key, value in game_context.items():
        if key.endswith("_new"):
            if value:  # _new=True 表示有新数据
                base = key[:-4]
                silent_key = f"{base}_silent"
                silent = game_context.get(silent_key, False)
                content = game_context.get(base, "")
                if content and not silent:
                    lines.append(f"[{base}] {content}")
        elif not key.endswith("_silent") and not key.endswith("_new"):
            # 普通值变化也输出
            old_val = prev_context.get(key)
            if old_val != value and value:
                lines.append(f"[{key}] {value}")
    return lines


def format_full_dump(bank_data: dict) -> str:
    """完整 dump 所有 section。"""
    lines = []
    for section_name in sorted(bank_data.keys()):
        section = bank_data[section_name]
        if section:
            lines.append(f"\n=== {section_name} ===")
            for k, v in sorted(section.items()):
                lines.append(f"  {k} = {v}")
    return "\n".join(lines)


class BankEventHandler(FileSystemEventHandler):
    def __init__(self, bank_path: Path, prev_state: dict, duration: float, start_time: float):
        self.bank_path = bank_path
        self.prev_state = prev_state
        self.prev_context = {}
        self.duration = duration
        self.start_time = start_time
        self.event_count = 0

    def on_modified(self, event):
        if event.is_directory:
            return
        if Path(event.src_path).name.lower() != self.bank_path.name.lower():
            return
        self._handle_change()

    def on_created(self, event):
        if event.is_directory:
            return
        if Path(event.src_path).name.lower() != self.bank_path.name.lower():
            return
        self._handle_change()

    def _handle_change(self):
        bank_data = parse_bank(self.bank_path)
        if not bank_data:
            return
        self.event_count += 1
        elapsed = time.time() - self.start_time
        print(f"\n--- [事件 #{self.event_count} t={elapsed:.1f}s mtime={time.strftime('%H:%M:%S')}] ---", flush=True)

        # 输出新增/变化的 game_context
        ctx_lines = format_context_output(bank_data, self.prev_context)
        if ctx_lines:
            print("[game_context 新增/变化]:", flush=True)
            for line in ctx_lines:
                print(f"  {line}", flush=True)
        else:
            print("[game_context 无新增数据]", flush=True)

        # 更新 prev_context
        self.prev_context = bank_data.get("game_context", {}).copy()


def command_watch(args):
    if not HAS_WATCHDOG:
        print("错误：缺少 watchdog 依赖。请运行: pip install watchdog", file=sys.stderr)
        return 2

    bank_path = Path(args.bank)
    if not bank_path.exists():
        print(f"Bank 文件不存在: {bank_path}", file=sys.stderr)
        return 2

    print(f"监听 Bank: {bank_path}", flush=True)
    print(f"时长: {args.duration}s (0=无限)", flush=True)
    print("等待 SC2 写入数据... (Ctrl+C 退出)", flush=True)

    # 首次 dump
    initial = parse_bank(bank_path)
    if initial:
        print("\n=== 初始状态 (启动时已存在的数据) ===", flush=True)
        print(format_full_dump(initial), flush=True)

    prev_state = {"context": initial.get("game_context", {}).copy()}
    start_time = time.time()
    handler = BankEventHandler(bank_path, prev_state, args.duration, start_time)
    observer = Observer()
    observer.schedule(handler, str(bank_path.parent), recursive=False)
    observer.start()

    try:
        while True:
            elapsed = time.time() - start_time
            if args.duration > 0 and elapsed > args.duration:
                print(f"\n达到时长 {args.duration}s，退出", flush=True)
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n用户中断", flush=True)
    finally:
        observer.stop()
        observer.join(timeout=2.0)

    # 结束前再 dump 一次最终状态
    final = parse_bank(bank_path)
    if final:
        print("\n=== 最终状态 ===", flush=True)
        print(format_full_dump(final), flush=True)
    print(f"\n总计捕获 {handler.event_count} 次文件变化", flush=True)
    return 0


def command_dump(args):
    """单次 dump 当前 Bank 内容。"""
    bank_path = Path(args.bank)
    if not bank_path.exists():
        print(f"Bank 文件不存在: {bank_path}", file=sys.stderr)
        return 2
    data = parse_bank(bank_path)
    if not data:
        print("Bank 为空或解析失败", file=sys.stderr)
        return 1
    print(format_full_dump(data))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="NeuroIntegration Bank watchdog 监听器")
    sub = parser.add_subparsers(dest="command", required=True)

    watch = sub.add_parser("watch", help="实时监听 Bank 文件变化")
    watch.add_argument("--bank", default=str(DEFAULT_BANK), help="Bank 文件路径")
    watch.add_argument("--duration", type=float, default=30.0, help="监听时长（秒，0=无限）")
    watch.set_defaults(func=command_watch)

    dump = sub.add_parser("dump", help="单次 dump 当前 Bank 内容")
    dump.add_argument("--bank", default=str(DEFAULT_BANK), help="Bank 文件路径")
    dump.set_defaults(func=command_dump)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
