"""Acesso ao banco da Solicitação de Extratos: cadastro de fundos/cotistas, rodadas e anexos já salvos.

Antes: dados/extratos/Template_Fundos_Ativos.xlsx, Extratos/_rodadas/*.json e Extratos/<AAAA-MM>/_salvos.json.
"""
import json
import os
import re
from collections import OrderedDict

import numpy as np
import pandas as pd

from app.database.db import abrirTransacao, consultarTodos, consultarUm, executarVarios

COLUNAS_CADASTRO = ["Nome do Fundo", "CNPJ", "COTISTAS", "CPF/CNPJ COTISTAS", "emails"]


# ---------------------------------------------------------------- Cadastro de fundos e cotistas
def obterVersaoCadastro():
    """Consulta barata para invalidar o cache da página quando linhas são incluídas/removidas."""
    linha = consultarUm("SELECT COUNT(*) AS qt_linhas, COALESCE(MAX(id_registro), 0) AS id_maximo FROM tb_extratos_fundo_cotista")
    return int(linha["qt_linhas"]), int(linha["id_maximo"])


def listarFundosCotistas():
    """DataFrame (dtype texto, vazios = NaN) com as mesmas colunas e a mesma ordem da planilha antiga."""
    lista_linhas = consultarTodos(
        "SELECT nm_fundo, nr_cnpj, nm_cotista, nr_doc_cotista, ds_emails FROM tb_extratos_fundo_cotista ORDER BY id_registro"
    )
    df = pd.DataFrame(
        [(linha["nm_fundo"], linha["nr_cnpj"], linha["nm_cotista"], linha["nr_doc_cotista"], linha["ds_emails"]) for linha in lista_linhas],
        columns=COLUNAS_CADASTRO,
        dtype=object,
    )
    df = df.where(df.notna(), np.nan)
    return df.dropna(how="all").reset_index(drop=True)


def chaveCadastro(valor):
    """Só letras e números, em maiúsculas: '48.307.294/0001-25' e '48307294000125' dão a mesma chave (igual à coluna do banco)."""
    return re.sub(r"[^0-9A-Z]", "", str(valor or "").upper())


def listarCadastroExistente():
    """Linhas já cadastradas, com as chaves usadas para achar duplicidade (fundo + cotista)."""
    return consultarTodos(
        "SELECT id_registro, nm_fundo, nr_cnpj, nm_cotista, nr_doc_cotista, ds_emails, ds_chave_fundo, ds_chave_cotista "
        "FROM tb_extratos_fundo_cotista ORDER BY id_registro"
    )


def incluirCadastro(lista_linhas):
    """Insere (nm_fundo, nr_cnpj, nm_cotista, nr_doc_cotista, ds_emails). A chave única do banco ignora o que já existe,
    mesmo que outra pessoa tenha cadastrado a mesma linha no meio do caminho. Devolve quantas linhas entraram."""
    if not lista_linhas:
        return 0
    with abrirTransacao() as cursor:
        cursor.execute("SELECT COUNT(*) AS qt FROM tb_extratos_fundo_cotista")
        qt_antes = cursor.fetchone()["qt"]
        cursor.executemany(
            "INSERT IGNORE INTO tb_extratos_fundo_cotista (nm_fundo, nr_cnpj, nm_cotista, nr_doc_cotista, ds_emails) VALUES (%s,%s,%s,%s,%s)",
            lista_linhas,
        )
        cursor.execute("SELECT COUNT(*) AS qt FROM tb_extratos_fundo_cotista")
        return cursor.fetchone()["qt"] - qt_antes


def excluirCadastro(lista_ids, nm_usuario):
    """Apaga linhas do cadastro. Antes, copia cada uma para tb_extratos_cadastro_excluido (quem apagou e quando), na mesma
    transação: ou faz as duas coisas ou nenhuma. Devolve quantas linhas foram apagadas."""
    if not lista_ids:
        return 0
    ds_marcadores = ",".join(["%s"] * len(lista_ids))
    with abrirTransacao() as cursor:
        cursor.execute(
            "INSERT INTO tb_extratos_cadastro_excluido (nm_usuario, id_registro, nm_fundo, nr_cnpj, nm_cotista, nr_doc_cotista, ds_emails) "
            f"SELECT %s, id_registro, nm_fundo, nr_cnpj, nm_cotista, nr_doc_cotista, ds_emails FROM tb_extratos_fundo_cotista "
            f"WHERE id_registro IN ({ds_marcadores})",
            [nm_usuario, *lista_ids],
        )
        cursor.execute(f"DELETE FROM tb_extratos_fundo_cotista WHERE id_registro IN ({ds_marcadores})", list(lista_ids))
        return cursor.rowcount


def atualizarCadastro(lista_linhas):
    """Atualiza os e-mails de linhas já cadastradas: (ds_emails, id_registro)."""
    executarVarios("UPDATE tb_extratos_fundo_cotista SET ds_emails = %s WHERE id_registro = %s", lista_linhas)


# ---------------------------------------------------------------- Rodadas
def _dtSemMicrossegundos(dt_valor):
    return dt_valor.replace(microsecond=0)


def salvarRodadaBanco(rodada, encerrada=False):
    """Grava a rodada (insere na primeira vez, atualiza depois) e guarda o id em rodada['id_rodada']."""
    dt_inicio = _dtSemMicrossegundos(rodada["inicio"])
    with abrirTransacao() as cursor:
        id_rodada = rodada.get("id_rodada")
        if not id_rodada:
            cursor.execute("SELECT id_rodada FROM tb_extratos_rodada WHERE dt_inicio = %s", (dt_inicio,))
            linha = cursor.fetchone()
            id_rodada = linha["id_rodada"] if linha else None
        if id_rodada:
            cursor.execute(
                "UPDATE tb_extratos_rodada SET dt_inicio = %s, dt_referencia = %s, ic_encerrada = %s, dt_atualizado = NOW() WHERE id_rodada = %s",
                (dt_inicio, rodada["data"], int(bool(encerrada)), id_rodada),
            )
            cursor.execute("DELETE FROM tb_extratos_rodada_item WHERE id_rodada = %s", (id_rodada,))
            cursor.execute("DELETE FROM tb_extratos_rodada_reenvio WHERE id_rodada = %s", (id_rodada,))
        else:
            cursor.execute(
                "INSERT INTO tb_extratos_rodada (dt_inicio, dt_referencia, ic_encerrada) VALUES (%s,%s,%s)",
                (dt_inicio, rodada["data"], int(bool(encerrada))),
            )
            id_rodada = cursor.lastrowid
        for nr_item, elemento in enumerate(rodada["itens"]):
            cursor.execute(
                "INSERT INTO tb_extratos_rodada_item (id_rodada, nr_item, ds_emails, qt_linhas, js_cnpjs) VALUES (%s,%s,%s,%s,%s)",
                (id_rodada, nr_item, elemento["emails"], elemento["linhas"], json.dumps(elemento["cnpjs"], ensure_ascii=False)),
            )
            lista_cotistas = []
            for nm_fundo, cots in elemento["fundos"].items():
                if not cots:
                    # fundo sem cotista: linha marcadora (nm_cotista NULL) para manter o fundo na rodada
                    lista_cotistas.append((id_rodada, nr_item, len(lista_cotistas), nm_fundo, None, None))
                for cotista, doc in cots:
                    lista_cotistas.append((id_rodada, nr_item, len(lista_cotistas), nm_fundo, cotista, doc))
            if lista_cotistas:
                cursor.executemany(
                    """INSERT INTO tb_extratos_rodada_cotista (id_rodada, nr_item, nr_ordem, nm_fundo, nm_cotista, nr_doc_cotista)
                       VALUES (%s,%s,%s,%s,%s,%s)""",
                    lista_cotistas,
                )
        for nr_item, dt_reenvio in rodada.get("reenvios", {}).items():
            cursor.execute(
                "INSERT INTO tb_extratos_rodada_reenvio (id_rodada, nr_item, dt_reenvio) VALUES (%s,%s,%s)",
                (id_rodada, int(nr_item), _dtSemMicrossegundos(dt_reenvio)),
            )
    rodada["id_rodada"] = id_rodada


def carregarRodadaAberta():
    """(rodada mais recente aberta ou None, quantidade de outras abertas). A rodada vem sem a chave 'invalidos'."""
    lista_abertas = consultarTodos(
        "SELECT id_rodada, dt_inicio, dt_referencia FROM tb_extratos_rodada WHERE ic_encerrada = 0 ORDER BY dt_atualizado DESC, id_rodada DESC"
    )
    if not lista_abertas:
        return None, 0
    linha_rodada = lista_abertas[0]
    id_rodada = linha_rodada["id_rodada"]
    itens = OrderedDict()
    for linha in consultarTodos(
        "SELECT nr_item, ds_emails, qt_linhas, js_cnpjs FROM tb_extratos_rodada_item WHERE id_rodada = %s ORDER BY nr_item", (id_rodada,)
    ):
        js_cnpjs = linha["js_cnpjs"]
        itens[linha["nr_item"]] = {
            "emails": linha["ds_emails"] or "",
            "linhas": linha["qt_linhas"] or 0,
            "cnpjs": (json.loads(js_cnpjs) if isinstance(js_cnpjs, (str, bytes)) else js_cnpjs) or {},
            "fundos": OrderedDict(),
        }
    for linha in consultarTodos(
        "SELECT nr_item, nm_fundo, nm_cotista, nr_doc_cotista FROM tb_extratos_rodada_cotista WHERE id_rodada = %s ORDER BY nr_item, nr_ordem",
        (id_rodada,),
    ):
        cots = itens[linha["nr_item"]]["fundos"].setdefault(linha["nm_fundo"], [])
        if linha["nm_cotista"] is not None:
            cots.append((linha["nm_cotista"], linha["nr_doc_cotista"] or ""))
    reenvios = {
        int(linha["nr_item"]): linha["dt_reenvio"]
        for linha in consultarTodos("SELECT nr_item, dt_reenvio FROM tb_extratos_rodada_reenvio WHERE id_rodada = %s", (id_rodada,))
    }
    rodada = {
        "inicio": linha_rodada["dt_inicio"],
        "data": linha_rodada["dt_referencia"],
        "itens": list(itens.values()),
        "id_rodada": id_rodada,
        "reenvios": reenvios,
    }
    return rodada, len(lista_abertas) - 1


# ---------------------------------------------------------------- Anexos já salvos (manifesto do mês)
def _caminhoRelativo(ds_caminho, pasta_extratos):
    if str(ds_caminho).startswith("drive:"):  # arquivo no Google Drive: guarda como está
        return ds_caminho
    try:
        ds_relativo = os.path.relpath(ds_caminho, pasta_extratos)
    except ValueError:  # outra unidade de disco
        return ds_caminho
    if ds_relativo.startswith(".."):
        return ds_caminho
    return ds_relativo.replace(os.sep, "/")


def _caminhoAbsoluto(ds_caminho, pasta_extratos):
    if str(ds_caminho).startswith("drive:") or os.path.isabs(ds_caminho):
        return ds_caminho
    return os.path.join(pasta_extratos, *ds_caminho.split("/"))


def carregarAnexosSalvos(nm_mes, pasta_extratos):
    """{chave: caminho absoluto} dos anexos já salvos no mês (AAAA-MM)."""
    lista_linhas = consultarTodos("SELECT ds_chave, ds_caminho FROM tb_extratos_anexo_salvo WHERE nm_mes = %s", (nm_mes,))
    return {linha["ds_chave"]: _caminhoAbsoluto(linha["ds_caminho"], pasta_extratos) for linha in lista_linhas}


def salvarAnexosSalvos(nm_mes, manifesto, pasta_extratos):
    """Grava (insere ou atualiza) cada chave do manifesto do mês, com o caminho relativo a pasta_extratos."""
    if not manifesto:
        return
    executarVarios(
        """INSERT INTO tb_extratos_anexo_salvo (ds_chave, nm_mes, ds_caminho) VALUES (%s,%s,%s)
           ON DUPLICATE KEY UPDATE ds_caminho = VALUES(ds_caminho)""",
        [(ds_chave, nm_mes, _caminhoRelativo(ds_caminho, pasta_extratos)) for ds_chave, ds_caminho in manifesto.items()],
    )
