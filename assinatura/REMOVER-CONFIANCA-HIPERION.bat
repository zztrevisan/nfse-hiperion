@echo off
setlocal
echo Este arquivo remove a confianca interna da Hiperion deste usuario.
certutil -user -delstore Root "Hiperion Assessoria Contabil - Aplicativos Internos"
certutil -user -delstore TrustedPublisher "Hiperion Assessoria Contabil - Aplicativos Internos"
echo Operacao concluida.
pause
