# Native PowerShell 5.1 path validation, without downloads or registry writes.
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$installer = Join-Path (Split-Path $PSScriptRoot -Parent) 'Install.ps1'
$ast = [Management.Automation.Language.Parser]::ParseFile($installer, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Syntaxe PowerShell invalide.' }
$definition = $ast.Find({ param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Resolve-KittyDirectory'
}, $true)
if (-not $definition) { throw 'Validateur absent.' }
. ([ScriptBlock]::Create($definition.Extent.Text))

function Assert-Rejected([string]$Path) {
    $rejected = $false
    try { $null = Resolve-KittyDirectory $Path } catch { $rejected = $true }
    if (-not $rejected) { throw ('Chemin errone accepte : ' + $Path) }
}

$base = Join-Path $env:TEMP ('kitty-path-tests-' + [Guid]::NewGuid().ToString('N'))
$previousLocal = $env:LOCALAPPDATA
try {
    [IO.Directory]::CreateDirectory($base) | Out-Null
    $env:LOCALAPPDATA = $base
    $path = Join-Path $base 'Kitty Francais & 100% !'
    if ((Resolve-KittyDirectory ('"' + $path + '"')) -ne $path) { throw 'Chemin avec espaces incorrect.' }
    if (Test-Path -LiteralPath $path) { throw 'La validation a cree le dossier.' }
    Assert-Rejected 'relative\Kitty'
    Assert-Rejected ([IO.Path]::GetPathRoot($base))
    Assert-Rejected '\\server\share\Kitty'
    Assert-Rejected (Join-Path $base 'CON')
    Assert-Rejected (Join-Path $base 'bad:stream')
    Assert-Rejected (Join-Path $base 'trailing.')
    $foreign = Join-Path $base 'existing'
    [IO.Directory]::CreateDirectory($foreign) | Out-Null
    [IO.File]::WriteAllText((Join-Path $foreign 'keep.txt'), 'keep')
    Assert-Rejected $foreign
    if ([IO.File]::ReadAllText((Join-Path $foreign 'keep.txt')) -ne 'keep') { throw 'Dossier existant modifie.' }
    [IO.File]::WriteAllText((Join-Path $foreign 'installation.json'), '{"app":"KittyDownloadManager"}')
    if ((Resolve-KittyDirectory $foreign) -ne $foreign) { throw 'Reinstallation refusee.' }
    $junction = Join-Path $base 'junction'
    New-Item -ItemType Junction -Path $junction -Target $foreign | Out-Null
    try { Assert-Rejected (Join-Path $junction 'Kitty') }
    finally { [IO.Directory]::Delete($junction) }
    Write-Host 'PowerShell : validation des chemins, dossiers existants et jonctions reussie.'
} finally {
    $env:LOCALAPPDATA = $previousLocal
    Remove-Item -LiteralPath $base -Recurse -Force -ErrorAction SilentlyContinue
}
