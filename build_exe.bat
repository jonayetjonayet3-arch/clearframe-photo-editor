@echo off
REM Builds ClearFramePhotoEditor.exe (run this on Windows with Python 3.9+ installed)
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --name ClearFramePhotoEditor photo_editor.py
echo.
echo Done. Your exe is here: dist\ClearFramePhotoEditor.exe
pause
