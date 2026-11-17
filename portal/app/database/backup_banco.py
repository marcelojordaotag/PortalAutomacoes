"""Backup do banco do portal com mysqldump (substitui os backups diários em JSON).

Uso, dentro de portal/:   APP_ENV=local python -m app.database.backup_banco
Grava dados/backups_banco/<banco>_AAAA-MM-DD.sql e mantém os últimos 30 dias. Pode ser agendado no Agendador de Tarefas.
A senha vai para o mysqldump por variável de ambiente (MYSQL_PWD), nunca na linha de comando.
"""
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from app.ambiente.config_ambiente import obterDiretorioDados, obterVariavel

DIAS_MANTIDOS = 30
LISTA_LOCAIS_MYSQLDUMP = [
    r"C:\Program Files\MySQL\MySQL Server 8.4\bin\mysqldump.exe",
    r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe",
]


def localizarMysqldump():
    caminho_env = obterVariavel("MYSQLDUMP_CAMINHO")
    for caminho in ([caminho_env] if caminho_env else []) + LISTA_LOCAIS_MYSQLDUMP:
        if Path(caminho).exists():
            return caminho
    return "mysqldump"  # tenta o PATH


def tabelasDoPortal():
    """Tabelas do portal (prefixo portal_). O schema é compartilhado com a área inteira: o backup nunca leva tabelas de outros projetos."""
    from app.database.db import consultarTodos

    return sorted(list(linha.values())[0] for linha in consultarTodos("SHOW TABLES LIKE 'portal\\_%'"))


def fazerBackup():
    nm_banco = obterVariavel("BANCO_BKO_NOME")
    dir_backups = obterDiretorioDados("backups_banco")
    arq_backup = dir_backups / f"{nm_banco}_{datetime.now():%Y-%m-%d}.sql"
    ambiente = {**os.environ, "MYSQL_PWD": obterVariavel("BANCO_BKO_SENHA")}
    lista_tabelas = tabelasDoPortal()
    if not lista_tabelas:
        print("Backup cancelado: nenhuma tabela portal_* encontrada no banco.")
        return 1
    comando = [localizarMysqldump(), f"--host={obterVariavel('BANCO_BKO_HOST')}", f"--port={obterVariavel('BANCO_BKO_PORTA') or 3306}",
               f"--user={obterVariavel('BANCO_BKO_USUARIO')}", "--single-transaction", "--routines", "--default-character-set=utf8mb4",
               f"--result-file={arq_backup}", nm_banco, *lista_tabelas]  # só as tabelas portal_*: o schema é da área inteira
    resultado = subprocess.run(comando, env=ambiente, capture_output=True, text=True)
    if resultado.returncode != 0:
        arq_backup.unlink(missing_ok=True)
        print("Backup falhou:", resultado.stderr.strip())
        return 1
    for arq_antigo in sorted(dir_backups.glob(f"{nm_banco}_*.sql"))[:-DIAS_MANTIDOS]:
        arq_antigo.unlink()
    print(f"Backup gerado: {arq_backup} ({arq_backup.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(fazerBackup())
