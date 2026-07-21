$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

Write-Host "[1/6] Generating application icon assets"
python .\tools\generate_assets.py

Write-Host "[2/6] Running tests"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed." }

Write-Host "[3/6] Building windowed application"
python -m PyInstaller --noconfirm --clean .\CodexUsageIndicator.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

$AppExe = Join-Path $ProjectRoot "dist\CodexUsageIndicator\CodexUsageIndicator.exe"
if (-not (Test-Path -LiteralPath $AppExe)) { throw "Built application not found: $AppExe" }

Write-Host "[4/6] Smoke testing packaged application"
$Smoke = Start-Process -FilePath $AppExe -ArgumentList "--smoke-test" -PassThru -WindowStyle Hidden
$Smoke | Wait-Process -Timeout 30 -ErrorAction SilentlyContinue
$Smoke.Refresh()
if (-not $Smoke.HasExited) {
    Stop-Process -Id $Smoke.Id -Force
    throw "Packaged application smoke test timed out after 30 seconds."
}
if ($Smoke.ExitCode -ne 0) { throw "Packaged application smoke test failed with exit code $($Smoke.ExitCode)." }

Write-Host "[5/6] Locating Inno Setup compiler"
$IsccCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 7\ISCC.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 7\ISCC.exe")
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
$Iscc = $IsccCandidates | Select-Object -First 1
if (-not $Iscc) {
    $IsccCommand = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($IsccCommand) { $Iscc = $IsccCommand.Source }
}
if (-not $Iscc) {
    throw "Inno Setup 6 is required. Install with: winget install --id JRSoftware.InnoSetup -e"
}

Write-Host "[6/6] Building installer"
& $Iscc ".\installer\CodexUsageIndicator.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed." }

$Installer = Join-Path $ProjectRoot "dist\CodexUsageIndicatorSetup-0.1.0.exe"
if (-not (Test-Path -LiteralPath $Installer)) { throw "Installer not found: $Installer" }
$Hash = (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
$ChecksumPath = "$Installer.sha256"
"$Hash  CodexUsageIndicatorSetup-0.1.0.exe" | Set-Content -LiteralPath $ChecksumPath -Encoding ascii

Write-Host "Build complete"
Write-Host "Installer: $Installer"
Write-Host "SHA256: $Hash"
