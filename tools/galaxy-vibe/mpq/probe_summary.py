#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 tier100_live_probe.py 的 JSON 输出压成一行摘要（阶梯实验用）。

用法：<probe 命令> 2>&1 | python probe_summary.py <label>
"""
import json
import sys

label = sys.argv[1] if len(sys.argv) > 1 else "?"
raw = sys.stdin.read()
i = raw.find("{")
if i < 0:
    print(f"[{label}] NO-JSON\n{raw[-1500:]}")
    raise SystemExit(2)
try:
    j = json.loads(raw[i:])
except json.JSONDecodeError as e:
    print(f"[{label}] JSON-FAIL {e}\n{raw[-1500:]}")
    raise SystemExit(2)

v = j.get("verdict", {})
c = j.get("calls", {})
p = j.get("probes", {})


def gen_raw(k):
    r = (c.get(k) or {}).get("raw", "")
    if not r:
        return (c.get(k) or {}).get("error", "-")
    try:
        d = json.loads(r)
        return f"{d.get('error_code')}|{str(d.get('payload'))[:80]}"
    except json.JSONDecodeError:
        return r[:90]


print(f"[{label}] reg={p.get('registration')} p0={v.get('p0_pass')} "
      f"ping={(c.get('system_ping') or {}).get('acks')}/"
      f"{(c.get('system_ping') or {}).get('runs')} "
      f"spawn={(c.get('vibe_unit_spawn') or {}).get('ok')} "
      f"obs_delta={(c.get('observation_delta') or {}).get('delta')} "
      f"tier100={v.get('tier100_pass')}")
print(f"      gen.1      -> {gen_raw('gen_1_invoke')}")
print(f"      gen.noarg  -> {gen_raw('gen_noarg_invoke')}")
se = v.get("script_error", {})
print(f"      scripterr={se.get('gate')} {se.get('files')}")
if j.get("errors"):
    print(f"      errors={j['errors']}")
