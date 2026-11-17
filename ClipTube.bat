@echo off
rem ============================================================
rem  ClipTube - de dois cliques neste arquivo para abrir o app.
rem
rem  Na PRIMEIRA vez ele instala tudo o que o ClipTube precisa
rem  (Python, bibliotecas, yt-dlp, FFmpeg e gallery-dl) e depois
rem  abre o app. Nas proximas vezes abre direto.
rem  Funciona de qualquer pasta onde voce colocar o projeto.
rem ============================================================
setlocal EnableExtensions
cd /d "%~dp0"
title ClipTube

rem --- 1) Python -------------------------------------------------
call :achar_python
if not defined PY goto instalar_python

:python_ok
rem --- 2) Bibliotecas e programas (so instala o que estiver faltando) ---
"%PY%" "%~dp0preparo.py" --verificar >nul 2>nul
if not errorlevel 1 goto abrir
"%PY%" "%~dp0preparo.py" --instalar
if errorlevel 1 pause

:abrir
rem --- 3) Atalho "ClipTube" com o icone do app (criado so uma vez) ---
if exist "%~dp0ClipTube.lnk" goto iniciar
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -Command "$p=(Get-Command '%PYW%').Source; $s=(New-Object -ComObject WScript.Shell).CreateShortcut('%~dp0ClipTube.lnk'); $s.TargetPath=$p; $s.Arguments='\"%~dp0app.py\"'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%~dp0assets\icone.ico,0'; $s.Description='ClipTube'; $s.Save()" >nul 2>nul
:iniciar

rem --- 4) Abre o app (sem janela de terminal) ---
start "" "%PYW%" "%~dp0app.py"
exit /b 0


:achar_python
set "PY="
set "PYW="
call :testar python pythonw
if defined PY goto :eof
call :testar py pyw
goto :eof

:testar
rem %1 = Python, %2 = Python sem janela. Precisa ser 3.10 ou mais novo e ter o tkinter.
%1 -c "import sys, tkinter; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 goto :eof
set "PY=%1"
set "PYW=%2"
goto :eof


:instalar_python
echo.
echo  O ClipTube precisa do Python e ele nao foi encontrado neste computador.
echo  Vou instalar o Python agora (precisa de internet; pode levar alguns minutos)...
echo.
where winget >nul 2>nul
if errorlevel 1 goto sem_winget
call winget install --id Python.Python.3.12 --exact --silent --accept-package-agreements --accept-source-agreements
if not defined CLIPTUBE_PYDIR set "CLIPTUBE_PYDIR=%LocalAppData%\Programs\Python\Python312"
if not exist "%CLIPTUBE_PYDIR%\python.exe" goto falhou_python
set "PY=%CLIPTUBE_PYDIR%\python.exe"
set "PYW=%CLIPTUBE_PYDIR%\pythonw.exe"
goto python_ok

:sem_winget
echo  Nao encontrei o winget neste computador, entao nao consigo instalar o Python sozinho.
echo.
echo  Instale o Python pelo site python.org (marque a opcao "Add python.exe to PATH")
echo  e depois de dois cliques em ClipTube.bat de novo.
echo.
pause
exit /b 1

:falhou_python
echo.
echo  Nao consegui instalar o Python automaticamente.
echo.
echo  Instale pelo site python.org (marque a opcao "Add python.exe to PATH")
echo  e depois de dois cliques em ClipTube.bat de novo.
echo.
pause
exit /b 1
