"""CRAVA COTAS no banco: cadastro fixo (portal_tb_crava_cadastro) e estado da leitura do pré-processamento (portal_tb_crava_leitura*).

Devolve as mesmas estruturas que a ferramenta usava com cadastro.xlsx e tabela.json."""
from datetime import datetime

import pandas as pd

from app.database.db import abrirTransacao, consultarTodos, consultarUm

COLUNAS_CADASTRO = ["Grupo Proc. Paralelo", "Id Cliente", "Apelido", "Id Pessoa", "Zera Caixa", "Tipo Cliente", "Ativo",
                    "Tipo Controle", "Implantação", "Status", "Data Dia", "Data Atualização", "Ativo Cetip"]
CAMPOS_CADASTRO = ["ds_grupo_proc_paralelo", "id_cliente", "nm_apelido", "id_pessoa", "ds_zera_caixa", "ds_tipo_cliente",
                   "ds_ativo", "ds_tipo_controle", "ds_implantacao", "ds_status", "ds_data_dia", "ds_data_atualizacao",
                   "ds_ativo_cetip"]


def lerCadastro():
    """Cadastro fixo como DataFrame de texto com os nomes originais das colunas (como o pd.read_excel devolvia)."""
    lista_linhas = consultarTodos(f"SELECT {', '.join(CAMPOS_CADASTRO)} FROM portal_tb_crava_cadastro ORDER BY id_cadastro")
    return pd.DataFrame([[linha[campo] for campo in CAMPOS_CADASTRO] for linha in lista_linhas],
                        columns=COLUNAS_CADASTRO, dtype=str)


def listarCadastroCrava():
    """Linhas do cadastro fixo como dicts (campos do banco, mais id_cadastro), na ordem de cadastro."""
    return consultarTodos(f"SELECT id_cadastro, {', '.join(CAMPOS_CADASTRO)} FROM portal_tb_crava_cadastro ORDER BY id_cadastro")


def incluirCadastroCrava(lista_linhas):
    """Insere linhas (13 valores, na ordem de CAMPOS_CADASTRO). A chave única do banco (id_cliente) ignora o que já existe,
    mesmo que outra pessoa tenha cadastrado a mesma carteira no meio do caminho. Devolve quantas linhas entraram."""
    if not lista_linhas:
        return 0
    with abrirTransacao() as cursor:
        cursor.execute("SELECT COUNT(*) AS qt FROM portal_tb_crava_cadastro")
        qt_antes = cursor.fetchone()["qt"]
        cursor.executemany(
            f"INSERT IGNORE INTO portal_tb_crava_cadastro ({', '.join(CAMPOS_CADASTRO)}) VALUES ({', '.join(['%s'] * len(CAMPOS_CADASTRO))})",
            lista_linhas)
        cursor.execute("SELECT COUNT(*) AS qt FROM portal_tb_crava_cadastro")
        return cursor.fetchone()["qt"] - qt_antes


def atualizarCadastroCrava(lista_linhas):
    """Atualiza todos os campos, menos o id_cliente, de linhas já cadastradas: (12 valores na ordem de CAMPOS_CADASTRO sem
    id_cliente, id_cadastro)."""
    lista_campos = [campo for campo in CAMPOS_CADASTRO if campo != "id_cliente"]
    if not lista_linhas:
        return
    with abrirTransacao() as cursor:
        cursor.executemany(f"UPDATE portal_tb_crava_cadastro SET {', '.join(f'{campo} = %s' for campo in lista_campos)} WHERE id_cadastro = %s",
                           lista_linhas)


def lerLeitura():
    """Estado da leitura: {"lido_em", "concluido", "dias": {nm_dia: {situacao, progresso, linhas, diagnostico, data}}}."""
    dic_meta = consultarUm("SELECT dt_lido, ic_concluido FROM portal_tb_crava_leitura_meta WHERE id_meta = 1")
    dic_dias = {}
    for dia in consultarTodos("SELECT nm_dia, ds_situacao, vl_progresso, ds_diagnostico, ds_data FROM portal_tb_crava_leitura ORDER BY nm_dia"):
        vl_progresso = dia["vl_progresso"]
        dic_dias[dia["nm_dia"]] = {"situacao": dia["ds_situacao"], "progresso": None if vl_progresso is None else float(vl_progresso),
                                   "linhas": [], "diagnostico": dia["ds_diagnostico"] or "", "data": dia["ds_data"] or ""}
    for linha in consultarTodos("""SELECT nm_dia, ds_id_exec, nm_fundo, nr_cnpj, ds_valor_cota, ds_status
                                   FROM portal_tb_crava_leitura_linha ORDER BY nm_dia, nr_linha"""):
        dic_dias[linha["nm_dia"]]["linhas"].append([linha["ds_id_exec"], linha["nm_fundo"], linha["nr_cnpj"],
                                                    linha["ds_valor_cota"], linha["ds_status"]])
    return {"lido_em": dic_meta["dt_lido"].isoformat(sep=" ", timespec="seconds") if dic_meta and dic_meta["dt_lido"] else None,
            "concluido": bool(dic_meta and dic_meta["ic_concluido"]), "dias": dic_dias}


def gravarLeitura(dic_dias, ic_concluido):
    """Substitui o estado inteiro da leitura (dias informados), numa única transação."""
    with abrirTransacao() as cursor:
        cursor.execute("DELETE FROM portal_tb_crava_leitura")  # as linhas saem junto (ON DELETE CASCADE)
        cursor.execute("DELETE FROM portal_tb_crava_leitura_meta")
        cursor.execute("INSERT INTO portal_tb_crava_leitura_meta (id_meta, dt_lido, ic_concluido) VALUES (1, %s, %s)",
                       (datetime.now().replace(microsecond=0), int(bool(ic_concluido))))
        for nm_dia, dia in dic_dias.items():
            cursor.execute(
                "INSERT INTO portal_tb_crava_leitura (nm_dia, ds_situacao, vl_progresso, ds_diagnostico, ds_data) VALUES (%s,%s,%s,%s,%s)",
                (nm_dia, dia.get("situacao"), dia.get("progresso"), dia.get("diagnostico"), dia.get("data")))
            lista_linhas = [(nm_dia, nr_linha, *(list(linha) + [None] * 5)[:5]) for nr_linha, linha in enumerate(dia.get("linhas") or [])]
            if lista_linhas:
                cursor.executemany(
                    """INSERT INTO portal_tb_crava_leitura_linha (nm_dia, nr_linha, ds_id_exec, nm_fundo, nr_cnpj, ds_valor_cota, ds_status)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""", lista_linhas)
