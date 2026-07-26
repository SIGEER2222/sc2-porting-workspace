"""Create a syntax check script for launch-cmre-alenger.ps1 and run it."""
import subprocess
from pathlib import Path

ps1_content = """$ErrorActionPreference = 'Stop'
$scriptPath = 'e:\\Code\\MyMod\\SC2VibeTools\\sc2-porting-workspace\\tools\\launchers\\launch-cmre-alenger.ps1'
$tokens = $null
$errors = $null
[System.Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$tokens, [ref]$errors) | Out-Null
if ($errors.Count -gt 0) {
    Write-Host 'Syntax errors:'
    foreach ($e in $errors) {
        Write-Host ("  {0}:{1} {2}" -f $e.Extent.StartLineNumber, $e.Extent.StartColumnNumber, $e.Message)
    }
    exit 1
}
Write-Host 'Syntax OK'
"""

script_path = Path(r"C:\Users\22448\AppData\Local\Temp\test-buff-syntax.ps1")
script_path.write_text(ps1_content, encoding="utf-8-sig")  # UTF-8 with BOM for PS 5.x
print(f"Wrote {script_path}")

result = subprocess.run(
    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path)],
    capture_output=True, text=True, encoding="gbk", errors="replace"
)
print(f"ExitCode: {result.returncode}")
print(f"STDOUT:\n{result.stdout}")
if result.stderr:
    print(f"STDERR:\n{result.stderr[:2000]}")
