"""Controle de Erros da Mesa de Boletas no banco (antes: controle_erros.json e snapshot_ata.json).

Os cards saem e entram no mesmo formato de dict que a página já usa (datas como texto
"DD/MM/AAAA HH:MM" e "DD/MM/AAAA"); a conversão de/para DATE/DATETIME é feita aqui.
"""
from datetime import datetime

from app.database.db import abrirTransacao, consultarTodos

FORMATO_DATA_HORA = "%d/%m/%Y %H:%M"
FORMATO_DATA = "%d/%m/%Y"

CAMPOS_CARD = {
    "titulo": "ds_titulo", "descricao": "ds_descricao", "coluna": "nm_coluna", "prioridade": "nm_prioridade",
    "ocorrencias": "qt_ocorrencias", "solucao": "ds_solucao", "categoria": "nm_categoria", "causa_raiz": "ds_causa_raiz",
}


def agoraMinuto():
    return datetime.now().replace(second=0, microsecond=0)


def textoDataHora(dt_valor):
    return dt_valor.strftime(FORMATO_DATA_HORA) if dt_valor else None


def montarCards(cursor):
    cursor.execute("SELECT * FROM tb_boletador_card ORDER BY id_card")
    lista_linhas = cursor.fetchall()
    dic_conexoes, dic_historico = {}, {}
    cursor.execute("SELECT id_card, id_card_conectado FROM tb_boletador_card_conexao ORDER BY id_card, id_card_conectado")
    for linha in cursor.fetchall():
        dic_conexoes.setdefault(linha["id_card"], []).append(linha["id_card_conectado"])
    cursor.execute("SELECT * FROM tb_boletador_card_historico ORDER BY id_card, id_historico")
    for linha in cursor.fetchall():
        dic_historico.setdefault(linha["id_card"], []).append({
            "data": textoDataHora(linha["dt_registro"]) or "",
            "qtd": int(linha["qt_ocorrencias"]),
            "nota": linha["ds_nota"] or "",
        })
    lista_cards = []
    for linha in lista_linhas:
        card = {
            "id": linha["id_card"],
            "titulo": linha["ds_titulo"],
            "descricao": linha["ds_descricao"] or "",
            "coluna": linha["nm_coluna"],
            "prioridade": linha["nm_prioridade"],
            "ocorrencias": int(linha["qt_ocorrencias"]),
            "solucao": linha["ds_solucao"] or "",
            "categoria": linha["nm_categoria"],
            "causa_raiz": linha["ds_causa_raiz"] or "",
            "conexoes": dic_conexoes.get(linha["id_card"], []),
        }
        if linha["id_card"] in dic_historico:  # cards antigos sem histórico ficam sem a chave
            card["historico"] = dic_historico[linha["id_card"]]
        if linha["dt_criado"]:
            card["criado_em"] = textoDataHora(linha["dt_criado"])
        if linha["dt_atualizado"]:
            card["atualizado_em"] = textoDataHora(linha["dt_atualizado"])
        if linha["dt_ultima_ocorrencia"]:
            card["ultima_ocorrencia"] = linha["dt_ultima_ocorrencia"].strftime(FORMATO_DATA)
        if linha["dt_resolvido"]:
            card["resolvido_em"] = textoDataHora(linha["dt_resolvido"])
        lista_cards.append(card)
    return lista_cards


def listarCards():
    with abrirTransacao() as cursor:
        return montarCards(cursor)


def criarCard(titulo, descricao, prioridade, ocorrencias, categoria, causa_raiz, nm_coluna):
    dt_agora = agoraMinuto()
    with abrirTransacao() as cursor:
        cursor.execute(
            """INSERT INTO tb_boletador_card (ds_titulo, ds_descricao, nm_coluna, nm_prioridade, qt_ocorrencias, ds_solucao,
               nm_categoria, ds_causa_raiz, dt_criado, dt_atualizado, dt_ultima_ocorrencia)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (titulo.strip(), descricao.strip(), nm_coluna, prioridade, int(ocorrencias), "", categoria,
             causa_raiz.strip(), dt_agora, dt_agora, dt_agora.date()))
        id_card = cursor.lastrowid
        cursor.execute(
            "INSERT INTO tb_boletador_card_historico (id_card, dt_registro, qt_ocorrencias, ds_nota) VALUES (%s,%s,%s,%s)",
            (id_card, dt_agora, int(ocorrencias), "Registro inicial"))
        return id_card


def atualizarCard(id_card, campos, nm_coluna_solucionada):
    """Atualiza os campos informados (mesmos nomes do dict do card; aceita conexoes, historico e ultima_ocorrencia)."""
    dt_agora = agoraMinuto()
    lista_sets, lista_valores = ["dt_atualizado=%s"], [dt_agora]
    for nm_campo, nm_coluna in CAMPOS_CARD.items():
        if nm_campo in campos:
            lista_sets.append(f"{nm_coluna}=%s")
            lista_valores.append(campos[nm_campo])
    if campos.get("ultima_ocorrencia"):
        lista_sets.append("dt_ultima_ocorrencia=%s")
        lista_valores.append(datetime.strptime(campos["ultima_ocorrencia"], FORMATO_DATA).date())
    with abrirTransacao() as cursor:
        cursor.execute("SELECT nm_coluna FROM tb_boletador_card WHERE id_card=%s FOR UPDATE", (id_card,))
        if cursor.fetchone() is None:
            return
        cursor.execute(f"UPDATE tb_boletador_card SET {', '.join(lista_sets)} WHERE id_card=%s", (*lista_valores, id_card))
        if "coluna" in campos:  # resolvido_em: preenchido ao entrar em Solucionados, limpo ao sair
            if campos["coluna"] == nm_coluna_solucionada:
                cursor.execute("UPDATE tb_boletador_card SET dt_resolvido=COALESCE(dt_resolvido, %s) WHERE id_card=%s", (dt_agora, id_card))
            else:
                cursor.execute("UPDATE tb_boletador_card SET dt_resolvido=NULL WHERE id_card=%s", (id_card,))
        if "conexoes" in campos:
            cursor.execute("DELETE FROM tb_boletador_card_conexao WHERE id_card=%s", (id_card,))
            for id_conectado in set(campos["conexoes"]):
                cursor.execute("INSERT INTO tb_boletador_card_conexao (id_card, id_card_conectado) VALUES (%s,%s)", (id_card, id_conectado))
        if "historico" in campos:
            cursor.execute("DELETE FROM tb_boletador_card_historico WHERE id_card=%s", (id_card,))
            for registro in campos["historico"]:
                cursor.execute(
                    "INSERT INTO tb_boletador_card_historico (id_card, dt_registro, qt_ocorrencias, ds_nota) VALUES (%s,%s,%s,%s)",
                    (id_card, datetime.strptime(registro["data"], FORMATO_DATA_HORA) if registro.get("data") else None,
                     int(registro["qtd"]), registro.get("nota", "")))


def registrarOcorrencia(id_card, qtd, nota):
    """Soma ocorrências ao card e registra data e nota na linha do tempo (card antigo ganha antes a entrada inicial)."""
    dt_agora = agoraMinuto()
    with abrirTransacao() as cursor:
        cursor.execute("SELECT qt_ocorrencias, dt_criado FROM tb_boletador_card WHERE id_card=%s FOR UPDATE", (id_card,))
        card = cursor.fetchone()
        if card is None:
            return
        cursor.execute("SELECT COUNT(*) AS qt FROM tb_boletador_card_historico WHERE id_card=%s", (id_card,))
        if cursor.fetchone()["qt"] == 0:
            cursor.execute(
                "INSERT INTO tb_boletador_card_historico (id_card, dt_registro, qt_ocorrencias, ds_nota) VALUES (%s,%s,%s,%s)",
                (id_card, card["dt_criado"] or dt_agora, int(card["qt_ocorrencias"]), "Registro inicial (anterior ao histórico)"))
        cursor.execute(
            "INSERT INTO tb_boletador_card_historico (id_card, dt_registro, qt_ocorrencias, ds_nota) VALUES (%s,%s,%s,%s)",
            (id_card, dt_agora, int(qtd), nota.strip()))
        cursor.execute(
            "UPDATE tb_boletador_card SET qt_ocorrencias=qt_ocorrencias+%s, dt_ultima_ocorrencia=%s, dt_atualizado=%s WHERE id_card=%s",
            (int(qtd), dt_agora.date(), dt_agora, id_card))


def excluirCard(id_card):
    """Remove o card, seu histórico e as conexões que apontavam para ele."""
    with abrirTransacao() as cursor:
        cursor.execute("DELETE FROM tb_boletador_card_conexao WHERE id_card_conectado=%s", (id_card,))
        cursor.execute("DELETE FROM tb_boletador_card WHERE id_card=%s", (id_card,))  # histórico e conexões próprias: ON DELETE CASCADE


def obterSnapshotAta():
    """{"<id do card>": ocorrências na última ata} só dos cards que têm referência guardada."""
    lista_linhas = consultarTodos("SELECT id_card, qt_ocorrencias_ata FROM tb_boletador_card WHERE qt_ocorrencias_ata IS NOT NULL")
    return {str(linha["id_card"]): int(linha["qt_ocorrencias_ata"]) for linha in lista_linhas}


def gravarSnapshotAta(dic_snapshot):
    with abrirTransacao() as cursor:
        cursor.execute("UPDATE tb_boletador_card SET qt_ocorrencias_ata=NULL")
        for id_card, qt_ocorrencias in dic_snapshot.items():
            cursor.execute("UPDATE tb_boletador_card SET qt_ocorrencias_ata=%s WHERE id_card=%s", (int(qt_ocorrencias), int(id_card)))
