<#
.SYNOPSIS
Build the GridLens Windows bundle and its per-user installer.

.DESCRIPTION
Creates .venv-packaging, installs GridLens with the dev and analysis extras
(the analysis extra installs the CPU stack on Windows, since RAPIDS has no
Windows wheels), renders the icon, runs PyInstaller, signs the executables
when a certificate is configured, and builds the installer with Inno Setup.

Run it from any folder in PowerShell 5.1 or later:

    powershell -ExecutionPolicy Bypass -File packaging\windows\build_windows.ps1

Environment variables:
    GRIDLENS_PYTHON                 Python 3.11 or later to build with
                                    (default: python).
    GRIDLENS_PACKAGE_VENV           Build virtual environment
                                    (default: .venv-packaging).
    GRIDLENS_SKIP_BUNDLE_BUILD      Set to 1 to reuse dist\GridLens and
                                    build\gridlens.ico.
    GRIDLENS_SIGN_CERT_THUMBPRINT   SHA-1 thumbprint of an Authenticode
                                    certificate in the certificate store.
                                    Without it, nothing is signed.
    GRIDLENS_SIGN_TIMESTAMP_URL     RFC 3161 timestamp server
                                    (default: http://timestamp.digicert.com).
    GRIDLENS_ISCC                   Path to ISCC.exe, if Inno Setup 6 is not
                                    on PATH or in its default folders.

.PARAMETER Version
The version to stamp on the installer; defaults to pyproject.toml's.
#>
param([string]$Version = "")

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-Checked {
    # Run a native program and stop the build when it fails, which
    # $ErrorActionPreference does not do for native programs.
    param([string]$FilePath, [string[]]$Arguments)
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath exited with code $LASTEXITCODE"
    }
}

function Invoke-Signing {
    # Sign files with the configured certificate, or say why they are not.
    param([string[]]$Paths)
    if (-not $env:GRIDLENS_SIGN_CERT_THUMBPRINT) {
        Write-Host "Not signing: set GRIDLENS_SIGN_CERT_THUMBPRINT to sign."
        return
    }
    $Timestamp = "http://timestamp.digicert.com"
    if ($env:GRIDLENS_SIGN_TIMESTAMP_URL) {
        $Timestamp = $env:GRIDLENS_SIGN_TIMESTAMP_URL
    }
    $Arguments = @("sign", "/sha1", $env:GRIDLENS_SIGN_CERT_THUMBPRINT,
                   "/fd", "SHA256", "/tr", $Timestamp, "/td", "SHA256")
    Invoke-Checked "signtool.exe" ($Arguments + $Paths)
}

function Find-InnoSetup {
    # Return ISCC.exe from GRIDLENS_ISCC, PATH, or Inno Setup's folders.
    if ($env:GRIDLENS_ISCC) {
        return $env:GRIDLENS_ISCC
    }
    $OnPath = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
    if ($OnPath) {
        return $OnPath.Source
    }
    $Candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
    )
    foreach ($Candidate in $Candidates) {
        if (Test-Path -LiteralPath $Candidate) {
            return $Candidate
        }
    }
    throw "Inno Setup 6 was not found. Install it, or set GRIDLENS_ISCC."
}

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root
$Python = "python"
if ($env:GRIDLENS_PYTHON) {
    $Python = $env:GRIDLENS_PYTHON
}
$Venv = Join-Path $Root ".venv-packaging"
if ($env:GRIDLENS_PACKAGE_VENV) {
    $Venv = $env:GRIDLENS_PACKAGE_VENV
}
$VenvPython = Join-Path $Venv "Scripts\python.exe"

if ($env:GRIDLENS_SKIP_BUNDLE_BUILD -ne "1") {
    Invoke-Checked $Python @("-m", "venv", $Venv)
    Invoke-Checked $VenvPython @("-m", "pip", "install", "--upgrade",
                                 "pip", "setuptools", "wheel")
    Invoke-Checked $VenvPython @("-m", "pip", "install", "-e",
                                 "${Root}[dev,analysis]")
    Invoke-Checked $VenvPython @("packaging\windows\make_icon.py",
                                 "build\gridlens.ico")
    Invoke-Checked $VenvPython @("-m", "PyInstaller", "--clean",
                                 "--noconfirm",
                                 "packaging\pyinstaller\gridlens.spec")
}

$Bundle = Join-Path $Root "dist\GridLens"
foreach ($Name in @("GridLens.exe", "gridlens-cli.exe")) {
    if (-not (Test-Path -LiteralPath (Join-Path $Bundle $Name))) {
        throw "PyInstaller output not found: $Bundle\$Name"
    }
}
if (-not $Version) {
    $VersionPython = $Python
    if (Test-Path -LiteralPath $VenvPython) {
        $VersionPython = $VenvPython
    }
    $Version = (& $VersionPython "scripts\package_version.py").Trim()
}

Invoke-Signing @((Join-Path $Bundle "GridLens.exe"),
                 (Join-Path $Bundle "gridlens-cli.exe"))
Invoke-Checked (Find-InnoSetup) @("/DAppVersion=$Version",
                                  "packaging\windows\gridlens.iss")
$Installer = Join-Path $Root "dist\GridLens-$Version-setup.exe"
Invoke-Signing @($Installer)
Write-Host "Created $Installer"
