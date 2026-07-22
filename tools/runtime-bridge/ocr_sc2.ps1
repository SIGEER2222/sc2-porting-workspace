# OCR the SC2 window screenshot using Windows.Media.Ocr API
param(
    [Parameter(Mandatory=$true)][int64]$WindowHandle
)

$ErrorActionPreference = "Stop"

# Step 1: capture screenshot
$shot = "$env:TEMP\ocr_sc2_shot.png"
& "c:\Users\22448\.trae-cn\skills\screenshot\scripts\take_screenshot.ps1" -Path $shot -WindowHandle $WindowHandle | Out-Null

if (-not (Test-Path $shot)) {
    Write-Host "Capture failed"
    exit 1
}
Write-Host "Screenshot: $shot"

# Step 2: OCR via Windows.Media.Ocr
Add-Type -AssemblyName "Windows.Foundation"
Add-Type -AssemblyName "Windows.Media.Ocr"

# Load required WinRT types
[Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime] | Out-Null
[Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime] | Out-Null
[Windows.Storage.FileAccessMode, Windows.Storage, ContentType=WindowsRuntime] | Out-Null

function Await($WinRtTask, $ResultType) {
    $asTask = $WinRtTask.AsTask()
    $asTask.Wait()
    return $asTask.Result
}

$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($shot)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) {
    $langs = [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages
    if ($langs.Count -gt 0) { $engine = [Windows.Media.Ocr.OcrEngine]::CreateAsync($langs[0]) }
}
if ($null -eq $engine) { Write-Host "No OCR engine"; exit 1 }

$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
Write-Host "===OCR Result==="
Write-Host $result.Text
