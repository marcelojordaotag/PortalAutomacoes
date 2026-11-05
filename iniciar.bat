@echo off
pushd "%~dp0portal"
set APP_ENV=local
set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
    echo Python nao encontrado. Instale o Python 3 e marque Add to PATH.
    pause
    exit /b 1
)
%PY% iniciar.py
popd
pause
