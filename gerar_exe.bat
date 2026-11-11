@echo off
REM Gera o executavel "ClipTube.exe" (com icone) na pasta "dist"
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --name "ClipTube" --icon "assets\icone.ico" --add-data "assets\icone.ico;assets" --add-data "assets\icone.png;assets" --collect-data customtkinter app.py
echo.
echo Pronto! O executavel esta em: %~dp0dist\ClipTube.exe
pause
