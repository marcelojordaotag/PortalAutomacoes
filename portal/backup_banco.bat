@echo off
REM Backup diario do banco do portal (agendado no Agendador de Tarefas do Windows).
cd /d "%~dp0"
set "APP_ENV=local"
"%~dp0..\venv\Scripts\python.exe" -m app.database.backup_banco >> "%~dp0dados\backups_banco\backup.log" 2>&1
