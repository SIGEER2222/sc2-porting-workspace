import socket, time, subprocess, sys

PORT = 5000
PY = r"C:/Users/22448/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
CLIENT = r"e:/Code/MyMod/SC2VibeTools/sc2-porting-workspace/src/lib/cmlib_runtime_test.py"

opened = False
for i in range(100):
    try:
        s = socket.socket()
        s.settimeout(1.5)
        s.connect(("127.0.0.1", PORT))
        s.close()
        opened = True
        print(f"[runner] API port {PORT} OPEN after ~{i*2}s", flush=True)
        break
    except Exception:
        time.sleep(2)

if not opened:
    print("[runner] PORT NEVER OPENED — SC2 likely stuck on auth/crash", flush=True)
    try:
        print("--- sc2api.log tail ---")
        print(open("/tmp/sc2api.log", "r", errors="ignore").read()[-1500:])
    except Exception as e:
        print("log read err", e)
    sys.exit(2)

time.sleep(3)  # grace for API readiness
print("[runner] launching client...", flush=True)
r = subprocess.run([PY, CLIENT])
print(f"[runner] client exit code = {r.returncode}", flush=True)
sys.exit(r.returncode)
