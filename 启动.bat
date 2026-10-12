@echo off
cd /d "%~dp0"

set "PY="

rem 1) you can pin your own python: put its full path in python_path.txt
if exist "python_path.txt" set /p PY=<python_path.txt
if defined PY if not exist "%PY%" set "PY="

rem 2) Windows Python Launcher (py -3)
if not defined PY (
  py -3 -c "import sys" >nul 2>&1
  if not errorlevel 1 for /f "delims=" %%i in ('py -3 -c "import sys;print(sys.executable)"') do set "PY=%%i"
)

rem 3) python.exe on PATH
if not defined PY for %%P in (python.exe) do set "PY=%%~$PATH:P"

rem 4) usual install locations
if not defined PY for /d %%d in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%d\python.exe" set "PY=%%d\python.exe"
if not defined PY for /d %%d in (C:\Python3*) do if exist "%%d\python.exe" set "PY=%%d\python.exe"
if not defined PY if exist "C:\ProgramData\Anaconda3\python.exe" set "PY=C:\ProgramData\Anaconda3\python.exe"
if not defined PY if exist "%USERPROFILE%\anaconda3\python.exe" set "PY=%USERPROFILE%\anaconda3\python.exe"
if not defined PY if exist "%USERPROFILE%\miniconda3\python.exe" set "PY=%USERPROFILE%\miniconda3\python.exe"
if not defined PY if exist "%USERPROFILE%\AppData\Local\miniforge3\python.exe" set "PY=%USERPROFILE%\AppData\Local\miniforge3\python.exe"

rem 5) WorkBuddy bundled python
if not defined PY if exist "%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe" set "PY=%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe"

if not defined PY (
  echo.
  echo   Python not found.
  echo   Install Python 3.8+ from https://www.python.org and tick "Add python.exe to PATH".
  echo   Or create a file named python_path.txt in this folder,
  echo   containing the full path to your python.exe, then run me again.
  echo.
  pause
  exit /b 1
)

echo Using %PY%
"%PY%" --version
echo Starting shuaci ...
"%PY%" server.py
pause
