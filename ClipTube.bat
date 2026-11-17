@echo off
rem ============================================================
rem  ClipTube - de dois cliques neste arquivo para abrir o app.
rem  Funciona de qualquer pasta (onde voce baixou/clonou o projeto).
rem ============================================================
setlocal
cd /d "%~dp0"

rem Procura o Python (pythonw abre o app sem janela de terminal).
set "PYW="
where pythonw >nul 2>nul && set "PYW=pythonw"
if not defined PYW where pyw >nul 2>nul && set "PYW=pyw"
if not defined PYW goto sem_python

rem Primeira vez: cria o atalho "ClipTube" (com o icone do app) nesta pasta.
rem Depois voce pode usar esse atalho, ou fixa-lo na barra de tarefas.
if not exist "%~dp0ClipTube.lnk" powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=(Get-Command %PYW%).Source; $s=(New-Object -ComObject WScript.Shell).CreateShortcut('%~dp0ClipTube.lnk'); $s.TargetPath=$p; $s.Arguments='\"%~dp0app.py\"'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%~dp0assets\icone.ico,0'; $s.Description='ClipTube'; $s.Save()" >nul 2>nul

start "" %PYW% "%~dp0app.py"
exit /b 0

:sem_python
echo.
echo  O ClipTube precisa do Python, e ele nao foi encontrado neste computador.
echo.
echo  Instale com o comando abaixo (ou pelo site python.org, marcando
echo  a opcao "Add python.exe to PATH"):
echo.
echo      winget install Python.Python.3.12
echo.
echo  Depois de instalar, feche esta janela e de dois cliques em ClipTube.bat de novo.
echo.
pause
exit /b 1
