$ErrorActionPreference = 'Stop'

$projectDir = Split-Path -Parent $PSScriptRoot
$venvDir = Join-Path $projectDir '.venv-win'
$venvPython = Join-Path $venvDir 'Scripts/python.exe'

if (-not (Test-Path $venvPython)) {
    python -m venv $venvDir
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create the Windows virtual environment.' }
}

& $venvPython -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Cannot install client dependencies.' }
& $venvPython -m pip install 'pyinstaller>=6.22,<7'
if ($LASTEXITCODE -ne 0) { throw 'Cannot install PyInstaller.' }
& $venvPython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Client dependencies are inconsistent.' }

& $venvPython -m PyInstaller --noconfirm --clean --onefile `
    --name gemini-cli `
    --distpath (Join-Path $projectDir 'dist') `
    --workpath (Join-Path $projectDir 'build') `
    --specpath (Join-Path $projectDir 'build') `
    (Join-Path $projectDir 'main.py')
if ($LASTEXITCODE -ne 0) { throw 'Windows executable build failed.' }

$exe = Join-Path $projectDir 'dist/gemini-cli.exe'
if (-not (Test-Path $exe)) { throw 'Windows executable is missing after the build.' }
Write-Output "Built: $exe"
