@echo off
setlocal
cd /d "%~dp0"
echo Instalando a assinatura interna da Hiperion para este usuario...
certutil -user -addstore Root "Hiperion-Assinatura-Interna.cer"
if errorlevel 1 goto erro
certutil -user -addstore TrustedPublisher "Hiperion-Assinatura-Interna.cer"
if errorlevel 1 goto erro
echo.
echo Assinatura instalada. Agora voce pode abrir o aplicativo.
pause
exit /b 0
:erro
echo.
echo Nao foi possivel instalar. Solicite ajuda ao responsavel de TI.
pause
exit /b 1
