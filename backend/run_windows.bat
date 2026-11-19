@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo  AMI - Avito Market Intelligence
echo  Backend launcher
echo ============================================
echo.

set "PYTHON=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

echo [Python] %PYTHON%
"%PYTHON%" --version
if errorlevel 1 goto :no_python

"%PYTHON%" -c "import fastapi, sqlalchemy, alembic, multipart" >nul 2>nul
if errorlevel 1 goto :no_deps

echo.
echo [1/2] Applying database migrations...
"%PYTHON%" -m alembic upgrade head
if errorlevel 1 goto :migrate_failed

echo.
echo [2/2] Starting API: http://127.0.0.1:8000
echo Docs: http://127.0.0.1:8000/docs
echo Stop: Ctrl+C
echo.
"%PYTHON%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
goto :end

:no_python
echo.
echo [ERROR] Python not found.
echo Create virtual environment:
echo   cd /d C:\Users\SystemX\AMI
echo   "C:\Users\SystemX\AppData\Local\Programs\Python\Python312\python.exe" -m venv .venv
echo   .venv\Scripts\python.exe -m pip install -r backend\requirements.txt
goto :pause_end

:no_deps
echo.
echo [ERROR] Backend dependencies are not installed.
echo Run:
echo   .venv\Scripts\python.exe -m pip install -r backend\requirements.txt
goto :pause_end

:migrate_failed
echo.
echo [ERROR] Migrations failed. See messages above.
goto :pause_end

:pause_end
echo.
pause

:end
endlocal
