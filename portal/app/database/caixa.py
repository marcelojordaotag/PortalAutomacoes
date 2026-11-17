"""Conciliação de Caixa no MySQL: categorias de OBS, estado por planilha e e-mails do monitor.
Devolve as mesmas estruturas que a página usava com os arquivos JSON (datas em texto no formato antigo)."""
import re
from datetime import datetime

from app.database.db import abrirTransacao, consultarTodos

CAMPOS_MONITOR = (("token", "ds_token"), ("imagem", "nm_imagem"), ("status", "nm_status"), ("prazo_horas", "qt_prazo_horas"),
                  ("topico", "ds_topico"), ("assunto", "ds_assunto"), ("para", "ds_para"), ("respondido_por", "nm_respondido_por"),
                  ("entry_id", "ds_entry_id"), ("corpo", "ds_corpo"), ("nota_anexos", "ds_nota_anexos"), ("slack", "nm_slack"),
                  ("alerta_prazo", "ds_alerta_prazo"))
FORMATOS_DATA = ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%d")


def listarCategorias():
    """Categorias de OBS na ordem salva (lista vazia se a tabela estiver vazia)."""
    lista_linhas = consultarTodos("SELECT nm_categoria FROM tb_caixa_categoria ORDER BY nr_ordem")
    return [linha["nm_categoria"] for linha in lista_linhas]


def gravarCategorias(lista_categorias):
    """Substitui a lista inteira, preservando a ordem."""
    lista_unica = list(dict.fromkeys(str(nm_categoria).strip() for nm_categoria in lista_categorias if str(nm_categoria).strip()))
    with abrirTransacao() as cursor:
        cursor.execute("DELETE FROM tb_caixa_categoria")
        if lista_unica:
            cursor.executemany("INSERT INTO tb_caixa_categoria (nm_categoria, nr_ordem) VALUES (%s,%s)",
                               [(nm_categoria, nr_ordem) for nr_ordem, nm_categoria in enumerate(lista_unica)])


def nomePlanilha(nm_arquivo):
    """Mesmo nome que o arquivo de estado tinha, sem o .json."""
    return re.sub(r"[^\w.-]+", "_", nm_arquivo)


def lerEstado(nm_arquivo):
    """{id_carteira: {obs, status, comentario}} da planilha."""
    lista_linhas = consultarTodos(
        "SELECT id_carteira, ds_obs, nm_status, ds_comentario FROM tb_caixa_estado WHERE nm_planilha = %s", (nomePlanilha(nm_arquivo),))
    return {linha["id_carteira"]: {"obs": linha["ds_obs"] or "", "status": linha["nm_status"] or "", "comentario": linha["ds_comentario"] or ""}
            for linha in lista_linhas}


def gravarEstado(nm_arquivo, dict_estado):
    """Faz o banco ficar igual ao dict: upsert por carteira e remove as carteiras que saíram."""
    nm_planilha = nomePlanilha(nm_arquivo)
    with abrirTransacao() as cursor:
        if dict_estado:
            lista_ids = [str(id_carteira) for id_carteira in dict_estado]
            cursor.execute(f"DELETE FROM tb_caixa_estado WHERE nm_planilha = %s AND id_carteira NOT IN ({','.join(['%s'] * len(lista_ids))})",
                           [nm_planilha] + lista_ids)
            cursor.executemany(
                """INSERT INTO tb_caixa_estado (nm_planilha, id_carteira, ds_obs, nm_status, ds_comentario) VALUES (%s,%s,%s,%s,%s)
                   ON DUPLICATE KEY UPDATE ds_obs = VALUES(ds_obs), nm_status = VALUES(nm_status), ds_comentario = VALUES(ds_comentario)""",
                [(nm_planilha, str(id_carteira), estado.get("obs", ""), estado.get("status", ""), estado.get("comentario", ""))
                 for id_carteira, estado in dict_estado.items()])
        else:
            cursor.execute("DELETE FROM tb_caixa_estado WHERE nm_planilha = %s", (nm_planilha,))


def lerData(tx_data):
    if not tx_data:
        return None
    for formato in FORMATOS_DATA:
        try:
            return datetime.strptime(str(tx_data).strip(), formato)
        except ValueError:
            continue
    return None


def listarMonitor():
    """Lista de e-mails do monitor (dicts como no JSON antigo), do mais novo para o mais antigo."""
    lista_linhas = consultarTodos("SELECT * FROM tb_caixa_monitor_email ORDER BY dt_criado DESC, id_monitor DESC")
    lista_monitor = []
    for linha in lista_linhas:
        registro = {nm_chave: linha[nm_coluna] for nm_chave, nm_coluna in CAMPOS_MONITOR if linha[nm_coluna] is not None}
        if linha["dt_criado"]:
            registro["criado_em"] = linha["dt_criado"].isoformat(timespec="seconds")
        if linha["dt_enviado"]:
            registro["enviado_em"] = linha["dt_enviado"].isoformat(timespec="seconds")
        if linha["dt_respondido"]:
            registro["respondido_em"] = linha["dt_respondido"].strftime("%d/%m/%Y %H:%M")
        lista_monitor.append(registro)
    return lista_monitor


def gravarMonitor(lista_monitor):
    """Upsert (por token) de cada e-mail da lista. Não apaga ninguém: para remover use removerMonitor."""
    lista_params = []
    for registro in lista_monitor:
        lista_params.append((
            registro["token"], registro.get("imagem"), registro["status"], registro.get("prazo_horas"),
            lerData(registro.get("criado_em")), lerData(registro.get("enviado_em")),
            registro.get("topico"), registro.get("assunto"), registro.get("para"), registro.get("respondido_por"),
            lerData(registro.get("respondido_em")), registro.get("entry_id"), registro.get("corpo"), registro.get("nota_anexos"),
            registro.get("slack"), None if registro.get("alerta_prazo") is None else str(registro["alerta_prazo"])))
    if not lista_params:
        return
    with abrirTransacao() as cursor:
        cursor.executemany(
            """INSERT INTO tb_caixa_monitor_email (ds_token, nm_imagem, nm_status, qt_prazo_horas, dt_criado, dt_enviado,
               ds_topico, ds_assunto, ds_para, nm_respondido_por, dt_respondido, ds_entry_id, ds_corpo, ds_nota_anexos,
               nm_slack, ds_alerta_prazo) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON DUPLICATE KEY UPDATE nm_imagem = VALUES(nm_imagem), nm_status = VALUES(nm_status), qt_prazo_horas = VALUES(qt_prazo_horas),
               dt_criado = VALUES(dt_criado), dt_enviado = VALUES(dt_enviado), ds_topico = VALUES(ds_topico),
               ds_assunto = VALUES(ds_assunto), ds_para = VALUES(ds_para), nm_respondido_por = VALUES(nm_respondido_por),
               dt_respondido = VALUES(dt_respondido), ds_entry_id = VALUES(ds_entry_id), ds_corpo = VALUES(ds_corpo),
               ds_nota_anexos = VALUES(ds_nota_anexos), nm_slack = VALUES(nm_slack), ds_alerta_prazo = VALUES(ds_alerta_prazo)""",
            lista_params)


def removerMonitor(lista_tokens):
    if not lista_tokens:
        return
    with abrirTransacao() as cursor:
        cursor.executemany("DELETE FROM tb_caixa_monitor_email WHERE ds_token = %s", [(ds_token,) for ds_token in lista_tokens])
