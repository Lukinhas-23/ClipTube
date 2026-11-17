@echo off
rem Diagnostico do ClipTube: testa leitura, download e clip e grava diagnostico.txt
setlocal
cd /d "%~dp0"
set "PY="
call :testar python
if not defined PY call :testar py
if not defined PY goto sem_python
echo.
echo  Testando o ClipTube neste computador (leva cerca de 1 minuto)...
"%PY%" "%~dp0diagnostico.py"
echo.
echo  Mande o arquivo diagnostico.txt (esta na pasta do ClipTube) para quem estiver ajudando.
pause
exit /b 0

:testar
%1 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 goto :eof
set "PY=%1"
goto :eof

:sem_python
echo.
echo  Python nao encontrado. De dois cliques em ClipTube.bat primeiro (ele instala o Python).
echo.
pause
exit /b 1
