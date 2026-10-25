@echo off
cd /d "%~dp0"
set PY=
if exist "%USERPROFILE%\miniconda3\python.exe" set PY="%USERPROFILE%\miniconda3\python.exe"
if not defined PY where py >NUL 2>NUL && set PY=py -3
if not defined PY where python >NUL 2>NUL && set PY=python
if not defined PY (echo No encontre Python. Instalalo o agregalo al PATH. & pause & exit /b 1)
%PY% -c "import xxhash, zstandard" 2>NUL || %PY% -m pip install -q -r requirements.txt
%PY% server.py
pause
