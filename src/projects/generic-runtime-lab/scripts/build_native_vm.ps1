param(
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Release'
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
$manifest = Join-Path $repo 'tools\runtime-vm\Cargo.toml'
$llvm = Join-Path $repo 'artifacts\galaxy-vibe\toolchain\llvm-mingw-20260616-ucrt-x86_64'
$target = 'x86_64-pc-windows-gnu'
$profile = if ($Configuration -eq 'Release') { '--release' } else { '' }

if (-not (Test-Path -LiteralPath (Join-Path $llvm 'bin\clang.exe'))) {
    throw "LLVM-MinGW not found: $llvm"
}

$env:Path = "$(Join-Path $llvm 'bin');$env:Path"
$env:CARGO_TARGET_X86_64_PC_WINDOWS_GNU_LINKER = Join-Path $llvm 'bin\x86_64-w64-mingw32-clang.exe'
$env:CARGO_TARGET_X86_64_PC_WINDOWS_GNU_AR = Join-Path $llvm 'bin\x86_64-w64-mingw32-llvm-ar.exe'
$env:RUSTFLAGS = '-C panic=abort -C link-arg=-Wl,-Bstatic -C link-arg=-l:libunwind.a -C link-arg=-Wl,-Bdynamic'
$args = @('build', '--manifest-path', $manifest, '--target', $target)
if ($profile) { $args += $profile }
& cargo @args
if ($LASTEXITCODE -ne 0) { throw "native VM build failed: exit $LASTEXITCODE" }

$cargoProfile = if ($Configuration -eq 'Release') { 'release' } else { 'debug' }
$buildRoot = Join-Path $repo "tools\runtime-vm\target\$target\$cargoProfile"
$artifactRoot = Join-Path $repo 'artifacts\projects\generic-runtime-lab\stage02-inprocess-gsvm-agent\bin'
New-Item -ItemType Directory -Force -Path $artifactRoot | Out-Null
Copy-Item (Join-Path $buildRoot 'gsvm-controller.exe') (Join-Path $artifactRoot 'gsvm-controller.exe') -Force
Copy-Item (Join-Path $buildRoot 'gsvm-fixture-host.exe') (Join-Path $artifactRoot 'gsvm-fixture-host.exe') -Force
Copy-Item (Join-Path $buildRoot 'gsvm_agent.dll') (Join-Path $artifactRoot 'gsvm_agent.dll') -Force
Copy-Item (Join-Path $llvm 'x86_64-w64-mingw32\bin\libunwind.dll') (Join-Path $artifactRoot 'libunwind.dll') -Force
Write-Output "native VM artifacts: $artifactRoot"
