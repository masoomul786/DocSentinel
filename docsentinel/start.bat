@echo off
title DocSentinel — Agentic Document Intelligence
color 0B
setlocal EnableDelayedExpansion

echo.
echo  ██████╗  ██████╗  ██████╗███████╗███████╗███╗   ██╗████████╗██╗███╗   ██╗███████╗██╗
echo  ██╔══██╗██╔═══██╗██╔════╝██╔════╝██╔════╝████╗  ██║╚══██╔══╝██║████╗  ██║██╔════╝██║
echo  ██║  ██║██║   ██║██║     ███████╗█████╗  ██╔██╗ ██║   ██║   ██║██╔██╗ ██║█████╗  ██║
echo  ██║  ██║██║   ██║██║     ╚════██║██╔══╝  ██║╚██╗██║   ██║   ██║██║╚██╗██║██╔══╝  ██║
echo  ██████╔╝╚██████╔╝╚██████╗███████║███████╗██║ ╚████║   ██║   ██║██║ ╚████║███████╗███████╗
echo  ╚═════╝  ╚═════╝  ╚═════╝╚══════╝╚══════╝╚═╝  ╚═══╝   ╚═╝   ╚═╝╚═╝  ╚═══╝╚══════╝╚══════╝
echo.
echo                        Self-Healing Multimodal Document Intelligence
echo                        100%% Offline ^| ARM Ready ^| Powered by Actian VectorAI DB
echo.
echo ══════════════════════════════════════════════════════════════════════════════════════════
echo.

:: ── Save root directory (absolute, no trailing slash) ─────────────────────────
set "ROOT_DIR=%~dp0"
set "ROOT_DIR=%ROOT_DIR:~0,-1%"

:: ── [1/5] Check Python ────────────────────────────────────────────────────────
echo [1/5] Checking Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Install Python 3.10+ from https://python.org
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version 2^>^&1') do echo       Found: %%i
echo.

:: ── [2/5] Check/Start Actian VectorAI DB ──────────────────────────────────────
echo [2/5] Checking Actian VectorAI DB...
curl -s http://localhost:6333/healthz >nul 2>&1
if %errorlevel% equ 0 (
    echo       Actian VectorAI DB already running on port 6333
    goto :qdrant_done
)

echo       Not running — attempting to start...

:: Try native qdrant binary
where qdrant >nul 2>&1
if %errorlevel% equ 0 (
    start "Actian VectorAI DB" /min qdrant
    echo       Waiting for native qdrant...
    call :wait_for_qdrant
    goto :qdrant_done
)

:: Try Docker
docker --version >nul 2>&1
if %errorlevel% neq 0 (
    echo       [WARN] Neither qdrant nor Docker found. Running in mock mode.
    echo       Install Docker Desktop: https://www.docker.com/products/docker-desktop
    echo       Or native qdrant:       https://github.com/qdrant/qdrant/releases
    goto :qdrant_done
)

:: Check Docker daemon is alive
docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo       [WARN] Docker installed but not running.
    echo       Start Docker Desktop, then re-run this script.
    echo       Running in mock mode for now...
    goto :qdrant_done
)

:: Remove any previous stopped container (this was the root cause of the bug)
echo       Removing any previous actian-vectorai container...
docker rm -f actian-vectorai >nul 2>&1

:: Ensure data directory exists (quoted path handles spaces)
if not exist "%ROOT_DIR%\actian_data" mkdir "%ROOT_DIR%\actian_data"

:: Pull image (silent, only downloads if missing)
echo       Pulling qdrant/qdrant image (skipped if cached)...
docker pull qdrant/qdrant:latest

echo       Starting Actian VectorAI DB via Docker...
docker run -d ^
    --name actian-vectorai ^
    --restart unless-stopped ^
    -p 6333:6333 ^
    -p 6334:6334 ^
    -v "%ROOT_DIR%\actian_data:/qdrant/storage:z" ^
    qdrant/qdrant:latest

if %errorlevel% neq 0 (
    echo       [WARN] docker run failed. Running in mock mode.
    goto :qdrant_done
)

echo       Waiting for Actian VectorAI DB to be ready...
call :wait_for_qdrant

:qdrant_done
echo.

:: ── [3/5] Install Python Dependencies ─────────────────────────────────────────
echo [3/5] Installing Python dependencies...
pushd "%ROOT_DIR%\backend"
python -m pip install --upgrade pip -q 2>nul
python -m pip install -r requirements.txt -q
python -c "import fastapi, uvicorn, httpx, pydantic" >nul 2>&1
if errorlevel 1 pip install fastapi "uvicorn[standard]" httpx pydantic python-multipart websockets aiofiles pypdf python-dotenv qdrant-client Pillow -q 2>nul
if %errorlevel% neq 0 (
    echo       [WARN] Some dependencies failed. Continuing with available packages.
) else (
    echo       Dependencies ready
)
popd
echo.

:: ── [4/5] Check LM Studio ─────────────────────────────────────────────────────
echo [4/5] Checking LM Studio...
curl -s http://localhost:1234/v1/models >nul 2>&1
if %errorlevel% equ 0 (
    echo       LM Studio is running on port 1234
) else (
    echo       [WARN] LM Studio not running.
    echo       For AI inference: open LM Studio and load the Qwen2.5-VL model.
    echo       The UI will run in demo mode without it.
)
echo.

:: ── [5/5] Start Backend ────────────────────────────────────────────────────────
echo [5/5] Starting DocSentinel backend...

:: Free port 8000 if something is already using it
for /f "tokens=5" %%p in ('netstat -ano 2^>nul ^| findstr "0.0.0.0:8000 " ^| findstr LISTENING') do (
    echo       Port 8000 in use by PID %%p — killing it...
    taskkill /f /pid %%p >nul 2>&1
    timeout /t 2 /nobreak >nul
)

:: Start uvicorn from the backend directory using pushd/popd (fixes relative-import bugs)
pushd "%ROOT_DIR%\backend"
set DOCSENTINEL_ROOT=%ROOT_DIR%
start "DocSentinel Backend" /min python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload > "%ROOT_DIR%\backend.log" 2>&1
popd

:: Wait up to 20 seconds for the backend to respond
echo       Waiting for backend to be ready...
set /a "WAIT=0"
:wait_backend
timeout /t 1 /nobreak >nul
curl -s http://localhost:8000/api/health >nul 2>&1
if %errorlevel% equ 0 goto :backend_ready
set /a "WAIT+=1"
if %WAIT% lss 20 goto :wait_backend
echo       [WARN] Backend slow to start — opening UI anyway...

:backend_ready
echo       Backend running on http://localhost:8000
echo.

:: ── Open Frontend ──────────────────────────────────────────────────────────────
echo ══════════════════════════════════════════════════════════════════════════════════════════
echo.
echo  DOCSENTINEL IS READY
echo.
echo  Frontend:    http://localhost:8000
echo  API Docs:    http://localhost:8000/docs
echo  Actian DB:   http://localhost:6333/dashboard
echo.
echo  Stack:
echo    Actian VectorAI DB  ^|  Named Vectors (text + image)
echo    Qwen2.5-VL via LM Studio  ^|  MinerU PDF Parser
echo    Self-Healing Agent Loop  ^|  Full Audit Trail
echo.
echo ══════════════════════════════════════════════════════════════════════════════════════════
echo.

start "" "http://localhost:8000"
echo  Browser opened. Press any key to stop all services.
pause >nul

:: ── Cleanup ────────────────────────────────────────────────────────────────────
echo.
echo  Shutting down...
taskkill /f /fi "WINDOWTITLE eq DocSentinel Backend" >nul 2>&1
docker stop actian-vectorai >nul 2>&1
echo  DocSentinel stopped. Goodbye.
endlocal
exit /b 0


:: ══ Subroutine: wait_for_qdrant (polls /healthz up to 20s) ════════════════════
:wait_for_qdrant
set /a "_QW=0"
:_qdrant_poll
timeout /t 1 /nobreak >nul
curl -s http://localhost:6333/healthz >nul 2>&1
if %errorlevel% equ 0 (
    echo       Actian VectorAI DB is ready ^(port 6333^)
    goto :eof
)
set /a "_QW+=1"
if %_QW% lss 20 goto :_qdrant_poll
echo       [WARN] Actian VectorAI DB did not respond — mock mode active
goto :eof
