[CmdletBinding()]
param()
$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "launch-cmre-alenger.ps1") -MapName "亡者之夜.SC2Map" -Commander "TerranAlenger3" -LegacyRootOverride "E:\Code\MyMod\SC2\合作指挥官-起义狂潮"
