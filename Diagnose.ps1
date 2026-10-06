#requires -Version 5.1
[CmdletBinding()]
param([string]$InstallDir)
$ErrorActionPreference = 'Stop'
try {
    if (-not $InstallDir) {
        $registry = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::CurrentUser, [Microsoft.Win32.RegistryView]::Registry64)
        try {
            $key = $registry.OpenSubKey('Software\Microsoft\Windows\CurrentVersion\Uninstall\KittyDownloadManager')
            if ($key) {
                try { $InstallDir = [string]$key.GetValue('InstallLocation') } finally { $key.Dispose() }
            }
        } finally { $registry.Dispose() }
    }
    if (-not $InstallDir) { $InstallDir = Join-Path $env:LOCALAPPDATA 'KittyDownloadManager' }
    $current = Get-Content -LiteralPath (Join-Path $InstallDir 'current.json') -Raw | ConvertFrom-Json
    if ($current.app -ne 'KittyDownloadManager' -or $current.directory -notmatch '^versions/[0-9.]+-[0-9a-f]{32}$') {
        throw 'Installation Kitty non reconnue.'
    }
    $version = Join-Path $InstallDir ($current.directory.Replace('/', '\'))
    $python = Join-Path $version 'runtime\python.exe'
    Write-Host ('Backend actif : ' + $current.version)
    Write-Host ('Dossier : ' + $InstallDir)
    # Read-only: no download, package modification, queue change or cookies.
    & $python -I -B (Join-Path $PSScriptRoot 'native-host\runtime_check.py') --packages (Join-Path $version 'packages')
    exit $LASTEXITCODE
} catch {
    Write-Host ('ERREUR : ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
