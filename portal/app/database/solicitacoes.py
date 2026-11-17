"""Acesso ao banco das Solicitações (portal_tb_solicitacao, portal_tb_solicitacao_historico, portal_tb_solicitacao_complemento, portal_tb_cliente).

Devolve e recebe os mesmos dicionários que as páginas já usavam no solicitacoes.json (chaves em português,
datas como texto 'AAAA-MM-DD' e histórico com 'quando' em 'AAAA-MM-DD HH:MM'). As evidências continuam em disco:
o banco guarda só o nome do arquivo e a página recebe o caminho completo.
"""
import ntpath
from datetime import date, datetime

from app.ambiente.config_ambiente import obterDiretorioDados
from app.database.db import abrirTransacao, consultarTodos

PASTA_EVIDENCIAS = obterDiretorioDados("solicitacoes") / "evidencias"
FORMATO_QUANDO = "%Y-%m-%d %H:%M"

# chave da página -> coluna de portal_tb_solicitacao
COLUNAS = {
    "cliente": "ds_cliente", "solicitante": "nm_solicitante", "data": "dt_solicitacao", "tipo": "nm_tipo",
    "descricao": "ds_descricao", "status": "nm_status", "data_conclusao": "dt_conclusao", "evidencia": "nm_evidencia",
    "prioridade": "nm_prioridade", "registrado_por": "nm_registrado_por", "competencia": "ds_competencia", "sla_data": "dt_sla",
}
CHAVES_DATA = ("data", "data_conclusao", "sla_data")
CHAVES_OPCIONAIS = ("prioridade", "registrado_por", "competencia", "sla_data")  # ausentes nos registros antigos
# chave da página -> coluna de portal_tb_solicitacao_complemento
COLUNAS_COMPLEMENTO = {"resolucao": "ds_resolucao", "email_solicitante": "ds_email_solicitante"}


# ---------------------------------------------------------------- conversões
def dataParaTexto(dt_valor):
    return dt_valor.isoformat() if dt_valor else None


def textoParaData(tx_data):
    if not tx_data:
        return None
    return date.fromisoformat(str(tx_data)[:10])


def normalizarValor(chave, valor):
    """Valor no formato que o banco guarda (texto) para comparar o que mudou na página."""
    if chave == "evidencia":
        return ntpath.basename(valor) if valor else None
    if chave in CHAVES_DATA:
        return str(valor)[:10] if valor else None
    if chave in CHAVES_OPCIONAIS or chave in COLUNAS_COMPLEMENTO:
        return valor if valor not in ("", None) else None
    return valor


def valorParaBanco(chave, valor):
    valor = normalizarValor(chave, valor)
    return textoParaData(valor) if chave in CHAVES_DATA else valor


def montarRegistro(linha, lista_historico, linha_complemento):
    registro = {
        "id": linha["id_solicitacao"], "cliente": linha["ds_cliente"], "solicitante": linha["nm_solicitante"] or "",
        "data": dataParaTexto(linha["dt_solicitacao"]), "tipo": linha["nm_tipo"], "descricao": linha["ds_descricao"] or "",
        "status": linha["nm_status"], "data_conclusao": dataParaTexto(linha["dt_conclusao"]),
        "evidencia": str(PASTA_EVIDENCIAS / linha["nm_evidencia"]) if linha["nm_evidencia"] else "",
    }
    for chave in CHAVES_OPCIONAIS:
        valor = linha[COLUNAS[chave]]
        if valor is not None:
            registro[chave] = dataParaTexto(valor) if chave in CHAVES_DATA else valor
    for chave, nm_coluna in COLUNAS_COMPLEMENTO.items():
        if linha_complemento and linha_complemento[nm_coluna] is not None:
            registro[chave] = linha_complemento[nm_coluna]
    registro["historico"] = []
    for historico in lista_historico:
        evento = {
            "id_historico": historico["id_historico"],
            "quando": historico["dt_evento"].strftime(FORMATO_QUANDO) if historico["dt_evento"] else "",
            "evento": historico["nm_evento"] or "", "detalhe": historico["ds_detalhe"] or "",
        }
        if historico["nm_usuario"]:
            evento["usuario"] = historico["nm_usuario"]
        registro["historico"].append(evento)
    registro["_orig"] = {chave: normalizarValor(chave, registro.get(chave)) for chave in (*COLUNAS, *COLUNAS_COMPLEMENTO)}
    return registro


# ---------------------------------------------------------------- leitura
def listarSolicitacoes():
    """Todas as solicitações (ordem do id) com o histórico aninhado. Erro de banco sobe como exceção."""
    lista_linhas = consultarTodos("SELECT * FROM portal_tb_solicitacao ORDER BY id_solicitacao")
    dic_historico, dic_complemento = {}, {}
    for historico in consultarTodos("SELECT * FROM portal_tb_solicitacao_historico ORDER BY id_solicitacao, id_historico"):
        dic_historico.setdefault(historico["id_solicitacao"], []).append(historico)
    for complemento in consultarTodos("SELECT * FROM portal_tb_solicitacao_complemento"):
        dic_complemento[complemento["id_solicitacao"]] = complemento
    return [montarRegistro(linha, dic_historico.get(linha["id_solicitacao"], []), dic_complemento.get(linha["id_solicitacao"]))
            for linha in lista_linhas]


def listarClientes():
    return [linha["ds_cliente"] for linha in consultarTodos("SELECT ds_cliente FROM portal_tb_cliente ORDER BY id_cliente")]


# ---------------------------------------------------------------- gravação por registro
def inserirEventos(cursor, registro):
    """Grava no banco os eventos do histórico que ainda não têm id_historico e devolve o id nos próprios eventos."""
    for evento in registro.get("historico", []):
        if evento.get("id_historico"):
            continue
        dt_evento = datetime.strptime(evento["quando"], FORMATO_QUANDO) if evento.get("quando") else None
        cursor.execute(
            "INSERT INTO portal_tb_solicitacao_historico (id_solicitacao, dt_evento, nm_evento, ds_detalhe, nm_usuario) VALUES (%s,%s,%s,%s,%s)",
            (registro["id"], dt_evento, evento.get("evento"), evento.get("detalhe"), evento.get("usuario") or None))
        evento["id_historico"] = cursor.lastrowid


def gravarComplemento(cursor, registro, lista_chaves):
    if not lista_chaves:
        return
    dic_valores = {COLUNAS_COMPLEMENTO[chave]: valorParaBanco(chave, registro.get(chave)) for chave in lista_chaves}
    nm_colunas = list(dic_valores)
    cursor.execute(
        f"INSERT INTO portal_tb_solicitacao_complemento (id_solicitacao, {', '.join(nm_colunas)}) VALUES (%s, {', '.join(['%s'] * len(nm_colunas))}) "
        f"ON DUPLICATE KEY UPDATE {', '.join(f'{nm_coluna}=VALUES({nm_coluna})' for nm_coluna in nm_colunas)}",
        (registro["id"], *dic_valores.values()))


def criarSolicitacao(registro):
    """Insere a solicitação (com os eventos de histórico já presentes) e devolve o id gerado, que também vai em registro['id']."""
    lista_chaves = [chave for chave in COLUNAS if chave in registro]
    with abrirTransacao() as cursor:
        cursor.execute(
            f"INSERT INTO portal_tb_solicitacao ({', '.join(COLUNAS[chave] for chave in lista_chaves)}) VALUES ({', '.join(['%s'] * len(lista_chaves))})",
            [valorParaBanco(chave, registro[chave]) for chave in lista_chaves])
        registro["id"] = cursor.lastrowid
        inserirEventos(cursor, registro)
        gravarComplemento(cursor, registro, [chave for chave in COLUNAS_COMPLEMENTO if normalizarValor(chave, registro.get(chave)) is not None])
    registro["_orig"] = {chave: normalizarValor(chave, registro.get(chave)) for chave in (*COLUNAS, *COLUNAS_COMPLEMENTO)}
    return registro["id"]


def salvarSolicitacoes(lista_registros):
    """Grava, numa transação, só o que mudou em cada registro (campos diferentes do lido) e os eventos novos do histórico.

    Outras solicitações e campos não tocados ficam como estão no banco, mesmo que outra pessoa os tenha alterado.
    """
    with abrirTransacao() as cursor:
        for registro in lista_registros:
            dic_orig = registro.get("_orig", {})
            mudados = [chave for chave in COLUNAS if normalizarValor(chave, registro.get(chave)) != dic_orig.get(chave)]
            if mudados:
                cursor.execute(
                    f"UPDATE portal_tb_solicitacao SET {', '.join(COLUNAS[chave] + '=%s' for chave in mudados)} WHERE id_solicitacao=%s",
                    [valorParaBanco(chave, registro.get(chave)) for chave in mudados] + [registro["id"]])
            gravarComplemento(cursor, registro, [chave for chave in COLUNAS_COMPLEMENTO
                                                 if normalizarValor(chave, registro.get(chave)) != dic_orig.get(chave)])
            inserirEventos(cursor, registro)
    for registro in lista_registros:
        registro["_orig"] = {chave: normalizarValor(chave, registro.get(chave)) for chave in (*COLUNAS, *COLUNAS_COMPLEMENTO)}


def salvarSolicitacao(registro):
    salvarSolicitacoes([registro])


def excluirSolicitacao(id_solicitacao):
    """Remove a solicitação (histórico e complemento vão junto por ON DELETE CASCADE)."""
    with abrirTransacao() as cursor:
        cursor.execute("DELETE FROM portal_tb_solicitacao WHERE id_solicitacao=%s", (id_solicitacao,))
