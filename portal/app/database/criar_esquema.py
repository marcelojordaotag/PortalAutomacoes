"""Cria o schema (se faltar) e as tabelas do portal. Uso, dentro de portal/:  APP_ENV=local python -m app.database.criar_esquema"""
from pathlib import Path

import mysql.connector

from app.ambiente import config_ambiente
from app.ambiente.config_ambiente import obterVariavel

ARQUIVO_ESQUEMA = Path(__file__).resolve().with_name("esquema.sql")


def separarComandos(tx_sql):
    # tira os comentários (o texto deles pode ter ponto e vírgula) antes de separar os comandos
    linhas_sem_comentario = [linha.split("--")[0].rstrip() for linha in tx_sql.splitlines()]
    tx_limpo = "\n".join(linha for linha in linhas_sem_comentario if linha.strip())
    return [comando.strip() for comando in tx_limpo.split(";") if comando.strip()]


def criarEsquema():
    nm_banco = obterVariavel("BANCO_BKO_NOME")
    conexao = mysql.connector.connect(
        host=obterVariavel("BANCO_BKO_HOST"), port=int(obterVariavel("BANCO_BKO_PORTA") or 3306),
        user=obterVariavel("BANCO_BKO_USUARIO"), password=obterVariavel("BANCO_BKO_SENHA"),
    )
    cursor = conexao.cursor()
    cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{nm_banco}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
    cursor.execute(f"USE `{nm_banco}`")
    lista_comandos = separarComandos(ARQUIVO_ESQUEMA.read_text(encoding="utf-8"))
    for comando in lista_comandos:
        cursor.execute(comando)
    conexao.commit()
    cursor.execute("SHOW TABLES LIKE 'portal\\_%'")  # o schema é da área inteira: conta só as tabelas do portal
    print(f"{len(cursor.fetchall())} tabelas do portal em {nm_banco} ({len(lista_comandos)} comandos executados)")
    cursor.close()
    conexao.close()


if __name__ == "__main__":
    criarEsquema()
