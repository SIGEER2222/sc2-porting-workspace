[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Path)
$bytes = [System.IO.File]::ReadAllBytes($Path)
if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
    Write-Host "BOM already present: $Path"
    exit 0
}
$content = [System.IO.File]::ReadAllText($Path, [System.Text.UTF8Encoding]::new($false))
$utf8WithBom = New-Object System.Text.UTF8Encoding($true)
[System.IO.File]::WriteAllText($Path, $content, $utf8WithBom)
Write-Host "BOM added: $Path"
