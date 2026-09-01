param([string]$Python = "")
$ErrorActionPreference = "Stop"
$Project = Split-Path -Parent $MyInvocation.MyCommand.Path
$BuildPython = Join-Path $Project ".buildvenv-gui\Scripts\python.exe"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$WorkPath = Join-Path $Project ".packaging\$Stamp"
$ReleasePath = Join-Path $Project "release"
$AssetsPath = Join-Path $Project "assets"
$LauncherPath = Join-Path $Project "launcher.py"

Set-Location $Project
if (-not (Test-Path -LiteralPath $BuildPython)) {
    if (-not $Python) {
        if (Get-Command py -ErrorAction SilentlyContinue) { $Python = "py" }
        elseif (Get-Command python -ErrorAction SilentlyContinue) { $Python = "python" }
        else { throw "Python 3 não encontrado. Execute build.ps1 -Python C:\\caminho\\python.exe" }
    }
    if ($Python -eq "py") { & $Python -3 -m venv .buildvenv-gui }
    else { & $Python -m venv .buildvenv-gui }
}

& $BuildPython -m pip install --disable-pip-version-check -r requirements.txt pyinstaller
& $BuildPython -m unittest discover -s tests -v

$Args = @(
    "--noconfirm", "--onefile", "--windowed",
    "--name", "NFSe-Hiperion-1.4.0",
    "--workpath", $WorkPath,
    "--distpath", $ReleasePath,
    "--specpath", $WorkPath,
    "--add-data", "$AssetsPath;assets",
    "--collect-submodules", "cryptography",
    "--hidden-import", "cryptography.hazmat.bindings._rust",
    $LauncherPath
)

$Icon = Join-Path $Project "assets\app.ico"
if (Test-Path -LiteralPath $Icon) {
    $Args = @("--icon", $Icon) + $Args
}

& $BuildPython -m PyInstaller @Args
if ($LASTEXITCODE -ne 0) { throw "Falha ao gerar o executável." }
$Output = Join-Path $ReleasePath "NFSe-Hiperion-1.4.0.exe"
if (-not (Test-Path -LiteralPath $Output)) { throw "Executável final não encontrado." }
Write-Host "Pacote gerado em: $Output"
