#requires -Version 5.1
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

function Get-VerifiedFile([string]$Url, [string]$Destination, [string]$Sha256) {
    if ($Sha256 -notmatch '^[0-9a-fA-F]{64}$') { throw 'SHA-256 absent ou invalide.' }
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Destination -TimeoutSec 300
    if ((Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash -ne $Sha256) {
        Remove-Item -LiteralPath $Destination -Force
        throw "Telechargement corrompu : $Url"
    }
}

$stage = $null
$bootstrap = $null
try {
    if ($env:OS -ne 'Windows_NT') { throw 'Cet installateur est reserve a Windows.' }
    if ([Environment]::OSVersion.Version.Major -lt 10) { throw 'Windows 10 ou 11 est requis.' }
    $architecture = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
    if ($architecture -ne 'AMD64') { throw 'Cette distribution est pour Windows x64 (Intel/AMD), pas ARM64 ou x86.' }
    if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA est indisponible.' }
    $appRoot = Join-Path $env:LOCALAPPDATA 'KittyDownloadManager'
    if (Test-Path -LiteralPath $appRoot) {
        if ((Get-Item -LiteralPath $appRoot).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'Le dossier Kitty est un lien ou une jonction; installation interrompue.'
        }
    }
    New-Item -ItemType Directory -Path $appRoot -Force | Out-Null
    # Private user data and authentication cookies: POSIX chmod is ineffective on Windows.
    $acl = New-Object System.Security.AccessControl.DirectorySecurity
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $rule = New-Object System.Security.AccessControl.FileSystemAccessRule($sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
    $systemSid = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-18')
    $systemRule = New-Object System.Security.AccessControl.FileSystemAccessRule($systemSid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
    $acl.SetOwner($sid)
    $acl.SetAccessRuleProtection($true, $false)
    $acl.AddAccessRule($rule)
    $acl.AddAccessRule($systemRule)
    Set-Acl -LiteralPath $appRoot -AclObject $acl
    $stage = Join-Path $appRoot ('stage-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $stage | Out-Null
    $runtime = Join-Path $stage 'runtime'
    $packages = Join-Path $stage 'packages'
    New-Item -ItemType Directory -Path $runtime, $packages | Out-Null

    Write-Host 'Kitty Download Manager V8.30 - Windows x64'
    Write-Host 'Preparation de Python prive (aucune installation systeme requise)...'
    $pythonZip = Join-Path $stage 'python.zip'
    # Official Python 3.13.16 release manifest, checked on 2026-10-03.
    Get-VerifiedFile 'https://www.python.org/ftp/python/3.13.16/python-3.13.16-embeddable-amd64.zip' $pythonZip '589dc1e9d02549ca5f680710307ff9b77f6e3ffc4aa3efccd7fa54eeeafac94b'
    Expand-Archive -LiteralPath $pythonZip -DestinationPath $runtime
    Remove-Item -LiteralPath $pythonZip
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText((Join-Path $runtime 'python313._pth'), "python313.zip`n.`n../backend`n../packages`n", $utf8)
    $python = Join-Path $runtime 'python.exe'
    Write-Host 'Preparation de pip prive...'
    $meta = Invoke-RestMethod -Uri 'https://pypi.org/pypi/pip/json' -TimeoutSec 30
    $wheel = @($meta.urls | Where-Object { $_.packagetype -eq 'bdist_wheel' -and $_.filename -like '*-py3-none-any.whl' })
    if ($wheel.Count -ne 1 -or ([Uri]$wheel[0].url).Host -ne 'files.pythonhosted.org') { throw 'Metadonnees pip inattendues.' }
    $pipZip = Join-Path $stage 'pip.zip'
    Get-VerifiedFile $wheel[0].url $pipZip $wheel[0].digests.sha256
    Expand-Archive -LiteralPath $pipZip -DestinationPath $packages
    Remove-Item -LiteralPath $pipZip
    Write-Host 'Installation de yt-dlp, Mutagen et du support Windows...'
    & $python -I -m pip --isolated install --index-url 'https://pypi.org/simple' --no-cache-dir --disable-pip-version-check --no-warn-script-location --no-compile --only-binary=:all: --target $packages --report (Join-Path $stage 'python-dependencies.json') 'yt-dlp[default]' mutagen psutil
    if ($LASTEXITCODE -ne 0) { throw 'Installation des dependances Python echouee.' }
    # Run setup OUTSIDE the directory being renamed. Windows can hold loaded
    # executables/DLLs open; no running Python may reside inside the stage.
    $bootstrap = Join-Path ([IO.Path]::GetTempPath()) ('kitty-setup-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $bootstrap | Out-Null
    Set-Acl -LiteralPath $bootstrap -AclObject $acl
    Copy-Item -LiteralPath $runtime -Destination (Join-Path $bootstrap 'runtime') -Recurse
    Copy-Item -LiteralPath $packages -Destination (Join-Path $bootstrap 'packages') -Recurse
    $setupPython = Join-Path $bootstrap 'runtime\python.exe'
    $arguments = @('-I', '-u', '-B', (Join-Path $PSScriptRoot 'native-host\windows_install.py'), 'install', '--source', $PSScriptRoot, '--stage', $stage)
    & $setupPython @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Installation Kitty interrompue; consulter le message ci-dessus.' }
    Write-Host ''
    Write-Host 'Installation terminee. Dossier :' $appRoot
    Write-Host 'Firefox : about:debugging > Ce Firefox > Charger un module temporaire.'
    Write-Host 'Selectionner :' (Join-Path $appRoot 'extension\manifest.json')
    Write-Host 'Le XPI fourni doit etre signe par Mozilla pour une installation permanente.'
    exit 0
} catch {
    Write-Host ('ERREUR : ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
} finally {
    if ($stage -and (Test-Path -LiteralPath $stage)) {
        Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($bootstrap -and (Test-Path -LiteralPath $bootstrap)) {
        Remove-Item -LiteralPath $bootstrap -Recurse -Force -ErrorAction SilentlyContinue
    }
}
