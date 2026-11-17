"""Conexão com o banco MySQL do portal (variáveis BANCO_BKO_*, carregadas por config_ambiente).

Usa um pool de conexões: cada chamada pega uma conexão, executa e devolve ao pool. O Streamlit roda
cada sessão em uma thread, então não existe conexão global compartilhada.
"""
import os
from contextlib import contextmanager

from mysql.connector import HAVE_CEXT, pooling

from app.ambiente import config_ambiente  # noqa: F401  (garante que os .env já foram carregados)

TAMANHO_POOL = 5

pool_conexoes = None


def obterPool():
    global pool_conexoes
    if pool_conexoes is None:
        pool_conexoes = pooling.MySQLConnectionPool(
            pool_name="portal_bko",
            pool_size=TAMANHO_POOL,
            host=os.getenv("BANCO_BKO_HOST"),
            port=int(os.getenv("BANCO_BKO_PORTA") or 3306),
            database=os.getenv("BANCO_BKO_NOME"),
            user=os.getenv("BANCO_BKO_USUARIO"),
            password=os.getenv("BANCO_BKO_SENHA"),
            charset="utf8mb4",
            use_pure=not HAVE_CEXT,  # conector em C quando existir (bem mais rápido); senão Python puro, como antes
            autocommit=True,  # leitura não precisa de COMMIT (1 ida e volta a menos); escrita abre transação explícita
            pool_reset_session=False,  # não reenvia SET de sessão a cada devolução ao pool (nenhum código muda variáveis de sessão)
        )
    return pool_conexoes


@contextmanager
def abrirTransacao():
    """Entrega um cursor (linhas como dict) dentro de uma transação: commit ao sair, rollback se der erro."""
    conexao = obterPool().get_connection()
    cursor = conexao.cursor(dictionary=True, buffered=True)
    try:
        conexao.start_transaction()
        yield cursor
        conexao.commit()
    except Exception:
        conexao.rollback()
        raise
    finally:
        cursor.close()
        conexao.close()  # devolve ao pool


def consultarTodos(sql, parametros=()):
    """Leitura simples: uma ida e volta ao banco (conexão em autocommit, sem transação nem COMMIT)."""
    conexao = obterPool().get_connection()
    cursor = conexao.cursor(dictionary=True, buffered=True)
    try:
        cursor.execute(sql, parametros)
        return cursor.fetchall()
    finally:
        cursor.close()
        conexao.close()  # devolve ao pool


def consultarUm(sql, parametros=()):
    lista_linhas = consultarTodos(sql, parametros)
    return lista_linhas[0] if lista_linhas else None


def executar(sql, parametros=()):
    """INSERT/UPDATE/DELETE. Devolve o id gerado (auto incremento) ou 0."""
    with abrirTransacao() as cursor:
        cursor.execute(sql, parametros)
        return cursor.lastrowid


def executarVarios(sql, lista_parametros):
    if not lista_parametros:
        return
    with abrirTransacao() as cursor:
        cursor.executemany(sql, lista_parametros)
