"""Histórico de cotas do Monitor de cotas (antes: dados/britech/Historico_Cotas.csv)."""
import pandas as pd

from app.database.db import abrirTransacao, consultarUm, consultarTodos

COLUNAS_HISTORICO = ["Data", "IdCarteira", "CotaBruta", "PLFechamento", "QuantidadeFechamento"]


def _valorOuNulo(valor):
    return None if pd.isna(valor) else valor


def substituirHistorico(df_historico):
    """Troca TODO o histórico pelo DataFrame (colunas COLUNAS_HISTORICO, Data como 'AAAA-MM-DD'), numa transação."""
    lista_parametros = [
        (str(linha.IdCarteira).strip(), str(linha.Data)[:10], _valorOuNulo(linha.CotaBruta),
         _valorOuNulo(linha.PLFechamento), _valorOuNulo(linha.QuantidadeFechamento))
        for linha in df_historico[COLUNAS_HISTORICO].itertuples(index=False)]
    with abrirTransacao() as cursor:
        cursor.execute("DELETE FROM tb_britech_historico_cota")
        if lista_parametros:
            cursor.executemany(
                "INSERT INTO tb_britech_historico_cota (id_carteira, dt_cota, vl_cota_bruta, vl_pl_fechamento, "
                "vl_quantidade_fechamento) VALUES (%s, %s, %s, %s, %s) "
                "ON DUPLICATE KEY UPDATE vl_cota_bruta = VALUES(vl_cota_bruta), vl_pl_fechamento = VALUES(vl_pl_fechamento), "
                "vl_quantidade_fechamento = VALUES(vl_quantidade_fechamento), dt_atualizacao = CURRENT_TIMESTAMP",
                lista_parametros)
    return len(lista_parametros)


def lerHistorico():
    """DataFrame com as mesmas colunas e tipos do antigo CSV (Data texto, IdCarteira inteiro se todos numéricos, valores float)."""
    lista_linhas = consultarTodos(
        "SELECT dt_cota, id_carteira, vl_cota_bruta, vl_pl_fechamento, vl_quantidade_fechamento "
        "FROM tb_britech_historico_cota ORDER BY id_carteira, dt_cota")
    df_historico = pd.DataFrame(
        [(linha["dt_cota"].strftime("%Y-%m-%d"), linha["id_carteira"], linha["vl_cota_bruta"],
          linha["vl_pl_fechamento"], linha["vl_quantidade_fechamento"]) for linha in lista_linhas],
        columns=COLUNAS_HISTORICO)
    for coluna in ["CotaBruta", "PLFechamento", "QuantidadeFechamento"]:
        df_historico[coluna] = pd.to_numeric(df_historico[coluna], errors="coerce").astype(float)
    if df_historico["IdCarteira"].str.isdigit().all():
        df_historico["IdCarteira"] = df_historico["IdCarteira"].astype("int64")
    return df_historico


def existeHistorico():
    return consultarUm("SELECT 1 AS ic_tem FROM tb_britech_historico_cota LIMIT 1") is not None


def versaoHistorico():
    """(quantidade de linhas, última gravação): muda a cada busca nova; entra na chave do cache. None se vazio."""
    linha = consultarUm("SELECT COUNT(*) AS qt_linhas, MAX(dt_atualizacao) AS dt_ultima FROM tb_britech_historico_cota")
    if not linha["qt_linhas"]:
        return None
    return (int(linha["qt_linhas"]), linha["dt_ultima"])


def dataAtualizacaoHistorico():
    linha = consultarUm("SELECT MAX(dt_atualizacao) AS dt_ultima FROM tb_britech_historico_cota")
    return linha["dt_ultima"]
