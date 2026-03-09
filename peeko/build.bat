@echo off
echo Building peeko.exe ...
pyinstaller --onefile --name peeko --console peeko\__main__.py
echo Done. Output: dist\peeko.exe
pause
