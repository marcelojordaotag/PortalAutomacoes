@echo off
REM Abre o Portal TAG (duplo clique). Usa o Python do PATH para chamar o iniciar.py, que cuida do venv.
cd /d "%~dp0"
if exist "%~dp0..\venv\Scripts\python.exe" (
    "%~dp0..\venv\Scripts\python.exe" iniciar.py
) else (
    python iniciar.py
)
pause
