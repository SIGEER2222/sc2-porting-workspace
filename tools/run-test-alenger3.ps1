[CmdletBinding()]
param()
$ErrorActionPreference = "Stop"
# Both this helper and the launch script have UTF-8 BOM so Chinese path
# literals (e.g. the map name and the legacy mod root) survive PS 5.x parsing.
$launchScript = Join-Path $PSScriptRoot "launch-cmre-alenger.ps1"
& $launchScript -MapName "亡者之夜.SC2Map" -Commander "TerranAlenger3"
