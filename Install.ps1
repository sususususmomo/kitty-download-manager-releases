#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$InstallDir,
    [switch]$NonInteractive
)
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

function Resolve-KittyDirectory([string]$Directory) {
    $Directory = [Environment]::ExpandEnvironmentVariables($Directory.Trim().Trim('"'))
    if ($Directory -notmatch '^[A-Za-z]:[\\/]') {
        throw 'Indique un dossier absolu sur un disque local, par exemple D:\KittyDownloadManager.'
    }
    foreach ($part in ($Directory.Substring(3) -split '[\\/]')) {
        if ($part -match '[<>:"|?*\x00-\x1f]' -or $part.EndsWith('.') -or $part.EndsWith(' ') -or
            $part -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)') { throw 'Nom de dossier Windows invalide.' }
    }
    $path = [IO.Path]::GetFullPath($Directory).TrimEnd('\', '/')
    $volume = [IO.Path]::GetPathRoot($path)
    if ($path.TrimEnd('\') -eq $volume.TrimEnd('\')) { throw 'Choisis un sous-dossier dedie a Kitty, pas la racine du disque.' }
    $cursor = $path
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                throw 'Le chemin contient un fichier, un lien ou une jonction.'
            }
        }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
    $drive = New-Object IO.DriveInfo($volume)
    if (-not $drive.IsReady -or $drive.DriveType -eq [IO.DriveType]::Network) { throw 'Disque local indisponible.' }
    if ($drive.DriveFormat -notin @('NTFS', 'ReFS')) { throw 'Utilise un disque NTFS ou ReFS pour proteger les donnees Kitty.' }
    if ($drive.AvailableFreeSpace -lt 2GB) {
        throw ('Espace insuffisant sur ' + $volume + ' : au moins 2 Go libres sont requis pour la preparation. Choisis un autre disque.')
    }
    if (Test-Path -LiteralPath $path) {
        $children = @(Get-ChildItem -LiteralPath $path -Force)
        $recognized = $false
        foreach ($name in @('current.json', 'installation.json')) {
            $marker = Join-Path $path $name
            if (Test-Path -LiteralPath $marker -PathType Leaf) {
                $data = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
                if ($data.app -eq 'KittyDownloadManager') { $recognized = $true }
            }
        }
        # Legacy default installs and their preserved data predate the marker.
        $legacy = Join-Path $env:LOCALAPPDATA 'KittyDownloadManager'
        if ($children.Count -and -not $recognized -and $path -ne $legacy) {
            throw 'Ce dossier contient deja des fichiers. Choisis un dossier vide dedie a Kitty.'
        }
    }
    return $path
}

$stage = $null
$bootstrap = $null
$savedTemp = $env:TEMP
$savedTmp = $env:TMP
try {
    if ($env:OS -ne 'Windows_NT') { throw 'Cet installateur est reserve a Windows.' }
    if ([Environment]::OSVersion.Version.Major -lt 10) { throw 'Windows 10 ou 11 est requis.' }
    $architecture = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
    if ($architecture -ne 'AMD64') { throw 'Cette distribution est pour Windows x64 (Intel/AMD), pas ARM64 ou x86.' }
    if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA est indisponible.' }
    $previousRoot = $null
    $registry = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::CurrentUser, [Microsoft.Win32.RegistryView]::Registry64)
    try {
        $key = $registry.OpenSubKey('Software\Microsoft\Windows\CurrentVersion\Uninstall\KittyDownloadManager')
        if ($key) {
            try { $previousRoot = [string]$key.GetValue('InstallLocation') } finally { $key.Dispose() }
        }
    } finally { $registry.Dispose() }
    $defaultRoot = if ($previousRoot) { $previousRoot } else { Join-Path $env:LOCALAPPDATA 'KittyDownloadManager' }
    if (-not $InstallDir -and -not $NonInteractive) {
        Write-Host 'Choisis le dossier d installation (exemple : D:\KittyDownloadManager).'
        Write-Host 'Python, FFmpeg, Deno et les fichiers temporaires seront prepares sur ce disque.'
        Write-Host ('Dossier propose : ' + $defaultRoot)
        $InstallDir = Read-Host 'Dossier (Entree pour conserver le dossier propose)'
    }
    if (-not $InstallDir) { $InstallDir = $defaultRoot }
    $appRoot = Resolve-KittyDirectory $InstallDir
    if ($previousRoot -and $previousRoot -ne $appRoot) {
        $previousRoot = [IO.Path]::GetFullPath($previousRoot).TrimEnd('\', '/')
        if ($appRoot.StartsWith($previousRoot + '\', [StringComparison]::OrdinalIgnoreCase) -or
            $previousRoot.StartsWith($appRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Les dossiers Kitty source et destination doivent etre distincts, sans imbrication.'
        }
    }
    $sourceRoot = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\', '/')
    if ($appRoot -eq $sourceRoot -or $sourceRoot.StartsWith($appRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Le dossier installe doit etre distinct du dossier contenant cet installateur.'
    }
    [IO.Directory]::CreateDirectory($appRoot) | Out-Null
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
    $metadata = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'backend.json') -Raw | ConvertFrom-Json
    $version = [string]$metadata.version
    if ($version -notmatch '^[0-9]+(?:\.[0-9]+)+$') { throw 'Version backend invalide.' }
    $versions = Join-Path $appRoot 'versions'
    if (Test-Path -LiteralPath $versions) {
        $item = Get-Item -LiteralPath $versions -Force
        if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'Le dossier des versions contient un fichier, un lien ou une jonction.'
        }
    }
    [IO.Directory]::CreateDirectory($versions) | Out-Null
    # This unique directory is not active until the Python transaction commits.
    # Never rename a directory containing executables that Windows has opened.
    $stage = Join-Path $versions ($version + '-' + [Guid]::NewGuid().ToString('N'))
    [IO.Directory]::CreateDirectory($stage) | Out-Null
    $temporary = Join-Path $stage 'temp'
    [IO.Directory]::CreateDirectory($temporary) | Out-Null
    $env:TEMP = $temporary
    $env:TMP = $temporary
    $runtime = Join-Path $stage 'runtime'
    $packages = Join-Path $stage 'packages'
    [IO.Directory]::CreateDirectory($runtime) | Out-Null
    [IO.Directory]::CreateDirectory($packages) | Out-Null

    Write-Host ('Kitty Download Manager V' + $version + ' - Windows x64')
    Write-Host ('Installation dans : ' + $appRoot)
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
    Write-Host 'Verification de yt-dlp, des modules YouTube et des postprocessors...'
    & $python -I -B (Join-Path $PSScriptRoot 'native-host\runtime_check.py') --packages $packages --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Paquets Python absents, incomplets ou charges depuis un autre emplacement. Le backend precedent est conserve.' }
    # Keep setup independent of the prepared runtime, including failure cleanup.
    $bootstrap = Join-Path $appRoot ('kitty-setup-' + [Guid]::NewGuid().ToString('N'))
    [IO.Directory]::CreateDirectory($bootstrap) | Out-Null
    Set-Acl -LiteralPath $bootstrap -AclObject $acl
    Copy-Item -LiteralPath $runtime -Destination (Join-Path $bootstrap 'runtime') -Recurse
    Copy-Item -LiteralPath $packages -Destination (Join-Path $bootstrap 'packages') -Recurse
    $setupPython = Join-Path $bootstrap 'runtime\python.exe'
    # Remove pip's temporary files before publishing the version.
    Remove-Item -LiteralPath $temporary -Recurse -Force
    $env:TEMP = $bootstrap
    $env:TMP = $bootstrap
    $arguments = @('-I', '-u', '-B', (Join-Path $PSScriptRoot 'native-host\windows_install.py'), 'install', '--source', $PSScriptRoot, '--stage', $stage, '--root', $appRoot)
    if ($previousRoot -and $previousRoot -ne $appRoot) { $arguments += @('--previous-root', $previousRoot) }
    & $setupPython @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Installation Kitty interrompue; consulter le message ci-dessus.' }
    # The prepared directory is now the active version; finally must retain it.
    $stage = $null
    Write-Host ''
    Write-Host 'Installation terminee. Dossier :' $appRoot
    Write-Host 'Rouvre Kitty dans Firefox et clique sur Verifier la connexion dans les reglages.'
    exit 0
} catch {
    Write-Host ('ERREUR : ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
} finally {
    $env:TEMP = $savedTemp
    $env:TMP = $savedTmp
    if ($stage -and (Test-Path -LiteralPath $stage)) {
        Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($bootstrap -and (Test-Path -LiteralPath $bootstrap)) {
        Remove-Item -LiteralPath $bootstrap -Recurse -Force -ErrorAction SilentlyContinue
    }
}
