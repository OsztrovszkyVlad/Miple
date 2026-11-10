# Miple installer for Windows.
#
#   irm https://raw.githubusercontent.com/OsztrovszkyVlad/Miple/main/install.ps1 | iex
#   .\install.ps1                    # from a checkout
#   .\install.ps1 -Uninstall         # remove Miple (keeps your notes and settings)
#
# Options: -NoAutostart  -NoLaunch  -Uninstall  -Branch <name>
# Installs per-user into %LOCALAPPDATA%\Miple; no administrator rights needed.
[CmdletBinding()]
param(
    [switch]$NoAutostart,
    [switch]$NoLaunch,
    [switch]$Uninstall,
    [string]$Branch = $(if ($env:MIPLE_BRANCH) { $env:MIPLE_BRANCH } else { 'main' })
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Repo        = 'OsztrovszkyVlad/Miple'
$MipleHome   = Join-Path $env:LOCALAPPDATA 'Miple'
$AppDir      = Join-Path $MipleHome 'app'
$VenvDir     = Join-Path $MipleHome 'venv'
$StartMenu   = Join-Path ([Environment]::GetFolderPath('Programs')) 'Miple.lnk'
$StartupLink = Join-Path ([Environment]::GetFolderPath('Startup')) 'Miple.lnk'

function Invoke-Native([scriptblock]$Command) {
    # Windows PowerShell 5.1 turns any stderr output of a native program into a
    # terminating error under 'Stop'; native tools are judged by exit code instead.
    $ErrorActionPreference = 'Continue'
    & $Command
}

function Say($msg)  { Write-Host "==> $msg" -ForegroundColor Magenta }
function Warn($msg) { Write-Host "!!  $msg" -ForegroundColor Yellow }

function Stop-Miple {
    $procs = Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -like "*$AppDir*main.py*" }
    foreach ($p in $procs) {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        Wait-Process -Id $p.ProcessId -Timeout 10 -ErrorAction SilentlyContinue
    }
}

function Remove-Folder($path) {
    # Windows can hold a folder for a moment after the process using it exits.
    for ($i = 0; $i -lt 10 -and (Test-Path $path); $i++) {
        Remove-Item -Recurse -Force $path -ErrorAction SilentlyContinue
        if (Test-Path $path) { Start-Sleep -Milliseconds 500 }
    }
    if (Test-Path $path) { throw "Could not replace $path - close Miple and run the installer again." }
}

if ($Uninstall) {
    Say 'Removing Miple'
    Stop-Miple
    Remove-Item -Recurse -Force $MipleHome, $StartMenu, $StartupLink -ErrorAction SilentlyContinue
    Say 'Done. Your notes (Documents\miple-notes) and settings were kept.'
    Say 'Ollama and its models were left installed; remove them from Settings > Apps if you like.'
    return
}

# ---------------------------------------------------------------------------
# Python 3.11+
# ---------------------------------------------------------------------------
function Find-Python {
    # Never call `py -3.x`: the new Python install manager *downloads* missing
    # versions when asked for one. Instead ask each candidate for its real path.
    $ErrorActionPreference = 'Continue'   # failed probes write to stderr
    $candidates = @()
    foreach ($name in 'python', 'python3', 'py') {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { $candidates += $cmd.Source }
    }
    foreach ($pattern in "$env:LOCALAPPDATA\Python\pythoncore-3*\python.exe",
                         "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
                         "$env:ProgramFiles\Python3*\python.exe") {
        $candidates += Get-ChildItem $pattern -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending | ForEach-Object { $_.FullName }
    }
    $probe = 'import sys; sys.exit(1) if sys.version_info < (3, 11) else print(sys.executable)'
    foreach ($c in $candidates) {
        # Store "python" stubs exit non-zero when given arguments, so they're skipped.
        $out = (& $c -c $probe 2>$null | Select-Object -Last 1)
        if ($LASTEXITCODE -eq 0 -and $out -and (Test-Path ([string]$out).Trim())) {
            return ([string]$out).Trim()
        }
    }
    return $null
}

$Python = Find-Python
if (-not $Python) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw 'Python 3.11+ is required. Install it from https://www.python.org/downloads/ and run this again.'
    }
    Say 'Installing Python 3.12 (one time, for your user only)'
    Invoke-Native { winget install -e --id Python.Python.3.12 --scope user --silent `
        --accept-package-agreements --accept-source-agreements | Out-Null }
    $Python = Find-Python
    if (-not $Python) { throw 'Python was installed but could not be found. Open a new terminal and run this again.' }
}
Say "Using $(Invoke-Native { & $Python --version }) ($Python)"

# ---------------------------------------------------------------------------
# App files
# ---------------------------------------------------------------------------
Stop-Miple
New-Item -ItemType Directory -Force $MipleHome | Out-Null
$staging = "$AppDir.new"
Remove-Folder $staging
New-Item -ItemType Directory -Force $staging | Out-Null

$here = if ($PSScriptRoot) { $PSScriptRoot } else { $null }
if ($here -and (Test-Path (Join-Path $here 'main.py')) -and (Test-Path (Join-Path $here 'src'))) {
    Say "Installing from $here"
    $skip = @('.git', '.venv', 'venv', 'floorplan', '__pycache__', '.pytest_cache')
    Get-ChildItem -Force $here | Where-Object { $skip -notcontains $_.Name } |
        Copy-Item -Destination $staging -Recurse -Force
    Get-ChildItem -Recurse -Directory -Force $staging -Filter '__pycache__' |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
} else {
    Say "Downloading Miple ($Branch)"
    $zip = Join-Path $env:TEMP "miple-$Branch.zip"
    Invoke-WebRequest -UseBasicParsing "https://codeload.github.com/$Repo/zip/refs/heads/$Branch" -OutFile $zip
    $unpack = Join-Path $env:TEMP "miple-unpack"
    Remove-Item -Recurse -Force $unpack -ErrorAction SilentlyContinue
    Expand-Archive $zip -DestinationPath $unpack -Force
    Get-ChildItem (Get-ChildItem $unpack | Select-Object -First 1).FullName -Force |
        Copy-Item -Destination $staging -Recurse -Force
    Remove-Item -Recurse -Force $zip, $unpack -ErrorAction SilentlyContinue
}
# Replace the app folder's contents rather than the folder itself: an open
# Explorer window or terminal can keep the folder (not its files) in use.
New-Item -ItemType Directory -Force $AppDir | Out-Null
for ($i = 0; $i -lt 10; $i++) {
    Get-ChildItem -Force $AppDir | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    if (-not (Get-ChildItem -Force $AppDir)) { break }
    Start-Sleep -Milliseconds 500
}
if (Get-ChildItem -Force $AppDir) { throw "Could not update $AppDir - close Miple and run the installer again." }
Get-ChildItem -Force $staging | Move-Item -Destination $AppDir
Remove-Folder $staging

# ---------------------------------------------------------------------------
# Python environment
# ---------------------------------------------------------------------------
$VenvPython  = Join-Path $VenvDir 'Scripts\python.exe'
$VenvPythonW = Join-Path $VenvDir 'Scripts\pythonw.exe'
if (-not (Test-Path $VenvPython)) {
    Say 'Creating Python environment'
    Invoke-Native { & $Python -m venv $VenvDir }
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
}
Say 'Installing Python packages (PyQt6, httpx)'
Invoke-Native { & $VenvPython -m pip install --quiet --disable-pip-version-check -r (Join-Path $AppDir 'requirements.txt') }
if ($LASTEXITCODE -ne 0) { throw 'Installing Python packages failed.' }

# ---------------------------------------------------------------------------
# Shortcuts (pythonw = no console window)
# ---------------------------------------------------------------------------
function New-Shortcut($path, $arguments) {
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut($path)
    $lnk.TargetPath = $VenvPythonW
    $lnk.Arguments = "`"$(Join-Path $AppDir 'main.py')`" $arguments".Trim()
    $lnk.WorkingDirectory = $AppDir
    $lnk.Description = 'Miple - your AI, locally'
    $ico = Join-Path $AppDir 'assets\miple.ico'
    if (Test-Path $ico) { $lnk.IconLocation = $ico }
    $lnk.Save()
}
New-Shortcut $StartMenu '--open'
if ($NoAutostart) {
    Remove-Item -Force $StartupLink -ErrorAction SilentlyContinue
} else {
    New-Shortcut $StartupLink ''
}

Say 'Miple is installed.'
Write-Host '    Start it from the Start menu (search "Miple").'
if (-not $NoAutostart) { Write-Host '    It will also start automatically when you sign in.' }
Write-Host '    On first start Miple checks your PC, installs Ollama if needed and downloads'
Write-Host '    the AI model that fits it best - just follow the sidebar.'

if (-not $NoLaunch) {
    Say 'Starting Miple'
    Start-Process -FilePath $VenvPythonW -ArgumentList "`"$(Join-Path $AppDir 'main.py')`"", '--open' -WorkingDirectory $AppDir
}
