"""DryRun test for launch-cmre-alenger.ps1 with buff patch params."""
import subprocess
from pathlib import Path

ps1_content = """$ErrorActionPreference = 'Stop'
$scriptPath = 'e:\\Code\\MyMod\\SC2VibeTools\\sc2-porting-workspace\\tools\\launchers\\launch-cmre-alenger.ps1'
& $scriptPath -MapName '亡者之夜.SC2Map' -Commander 'TerranRaynor' -NoLaunch -EnableBuffPatch -Buffs 'P1,P3' -Masteries '30,30,30,0,0,0'
Write-Host \"ExitCode: $LASTEXITCODE\"
"""

script_path = Path(r"C:\Users\22448\AppData\Local\Temp\test-buff-dryrun.ps1")
script_path.write_text(ps1_content, encoding="utf-8-sig")
print(f"Wrote {script_path}")

result = subprocess.run(
    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path)],
    capture_output=True, text=True, encoding="gbk", errors="replace"
)
print(f"ExitCode: {result.returncode}")
print(f"STDOUT:\n{result.stdout[-3000:]}")
if result.stderr:
    print(f"STDERR:\n{result.stderr[:2000]}")
