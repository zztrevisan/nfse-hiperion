@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Preparando o aplicativo pela primeira vez...
  py -3 -m venv .venv
  if errorlevel 1 goto :erro
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
  if errorlevel 1 goto :erro
)
".venv\Scripts\python.exe" -m app.main
if errorlevel 1 goto :erro
exit /b 0

:erro
  echo.
  echo Nao foi possivel iniciar. Confira a internet e instale o Python 3.11 ou superior.
  pause
exit /b 1
