$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$uvVersion = '0.13.1'
$uvPath = Join-Path $PSScriptRoot '.tools\uv\uv.exe'
$pythonVersion = (Get-Content -LiteralPath '.python-version' -Raw).Trim()
$previousCache = $env:UV_CACHE_DIR
$previousPythonDir = $env:UV_PYTHON_INSTALL_DIR
$env:UV_CACHE_DIR = Join-Path $PSScriptRoot '.tools\cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $PSScriptRoot '.tools\python'

function Invoke-Uv {
    & $uvPath @args
    if ($LASTEXITCODE -ne 0) {
        throw "uv failed (exit $LASTEXITCODE): $args"
    }
}

try {
    if (-not (Test-Path -LiteralPath $uvPath)) {
        New-Item -ItemType Directory -Path '.tools' -Force | Out-Null
        $archive = Join-Path $PSScriptRoot '.tools\uv.zip'
        Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/astral-sh/uv/releases/download/$uvVersion/uv-x86_64-pc-windows-msvc.zip" -OutFile $archive
        Expand-Archive -LiteralPath $archive -DestinationPath '.tools\uv' -Force
    }
    Invoke-Uv python install $pythonVersion --no-bin --no-registry
    if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
        $pythonPath = Invoke-Uv python find $pythonVersion --system --managed-python
        Invoke-Uv venv .venv --seed --python $pythonPath
    }
    $requirements = if (Test-Path -LiteralPath 'requirements-local-windows.lock.txt') {
        'requirements-local-windows.lock.txt'
    } else {
        'requirements.txt'
    }
    Invoke-Uv pip install --python '.venv\Scripts\python.exe' -r $requirements
    Invoke-Uv pip check --python '.venv\Scripts\python.exe'
    Write-Host 'Ready. Double-click start-local.bat, or use dev.bat for console output.'
} finally {
    $env:UV_CACHE_DIR = $previousCache
    $env:UV_PYTHON_INSTALL_DIR = $previousPythonDir
}
