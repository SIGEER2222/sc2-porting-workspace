import xml.etree.ElementTree as ET, os, time, glob, sys

BASE = os.path.join(os.environ['USERPROFILE'], "Documents", "StarCraft II", "Banks")
KEYS = ["map_init_entered", "bridge_heartbeat_started", "bridge_heartbeat",
        "runtime_listener_started", "runtime_listener_ready",
        "initialization_gate_started", "initialization_complete",
        "initialization_building_ready_p1", "initialization_building_ready_p2",
        "initialization_units_ready_p1", "initialization_units_ready_p2",
        "reborn_adapter_initialized", "world_cover_dialog_visible_p1"]

def read_bank():
    best = {}
    cands = [os.path.join(BASE, "CMRERebornDebug.SC2Bank")] + sorted(glob.glob(os.path.join(BASE, "*", "CMRERebornDebug.SC2Bank")))
    for p in cands:
        if not os.path.exists(p):
            continue
        try:
            t = ET.parse(p); r = t.getroot()
        except Exception:
            continue
        for sec in r.findall("Section"):
            if sec.get("name") != "debug":
                continue
            for k in sec.findall("Key"):
                kn = k.get("name")
                v = k.find("Value")
                val = int(v.get("int")) if (v is not None and v.get("int") is not None) else 0
                # take max across files (launcher reads max too)
                best[kn] = max(best.get(kn, 0), val)
    return best

def main():
    dur = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    deadline = time.time() + dur
    first_hb = None
    print(f"[monitor] polling CMRERebornDebug bank for {dur}s ...", flush=True)
    while time.time() < deadline:
        b = read_bank()
        hb = b.get("bridge_heartbeat", 0)
        if first_hb is None and hb > 0:
            first_hb = hb
        inc = (hb > first_hb) if first_hb is not None else False
        print(f"  t={int(deadline-time.time())}s hb={hb} map_init={b.get('map_init_entered',0)} "
              f"listener_ready={b.get('runtime_listener_ready',0)} init_complete={b.get('initialization_complete',0)} "
              f"reborn_init={b.get('reborn_adapter_initialized',0)} hb_increasing={inc}", flush=True)
        if inc and b.get("initialization_complete",0) > 0 and b.get("runtime_listener_ready",0) > 0:
            print("[monitor] GATE PASS: heartbeat increasing + init markers set", flush=True)
            return 0
        time.sleep(5)
    b = read_bank()
    print("[monitor] final:", {k: b.get(k,0) for k in KEYS}, flush=True)
    return 1

if __name__ == "__main__":
    sys.exit(main())
