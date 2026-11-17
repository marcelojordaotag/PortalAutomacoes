"""Importa para o MySQL os dados que hoje estão em arquivos (JSON, JSONL e planilhas em portal/dados).

Uso, dentro de portal/:   APP_ENV=local python -m app.database.migrar_arquivos [--forcar]

- Só LÊ os arquivos: nada é apagado nem alterado em disco.
- Por segurança, uma tabela que já tem linhas é pulada. Com --forcar ela é esvaziada e importada de novo
  (cuidado: depois que os apps passarem a gravar no banco, isso apaga o que foi feito no banco).
"""
import json
import ntpath
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from app.ambiente.config_ambiente import diretorio_dados
from app.database.db import abrirTransacao

FORMATOS_DATA = ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d")
resumo = []


# ---------------------------------------------------------------- utilitárias
def lerData(tx_data):
    """Converte os textos de data usados nos arquivos (DD/MM/AAAA, AAAA-MM-DD, ISO) em datetime; vazio vira None."""
    if tx_data is None or str(tx_data).strip() in ("", "-", "nan", "NaT"):
        return None
    tx_data = str(tx_data).strip()
    for formato in FORMATOS_DATA:
        try:
            return datetime.strptime(tx_data, formato)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(tx_data)
    except ValueError:
        return None


def soData(tx_data):
    dt_valor = lerData(tx_data)
    return dt_valor.date() if dt_valor else None


def textoOuNulo(valor):
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    tx_valor = str(valor).strip()
    return tx_valor if tx_valor and tx_valor.lower() != "nan" else None


def lerJson(caminho):
    return json.loads(Path(caminho).read_text(encoding="utf-8"))


def tabelaVazia(cursor, nm_tabela, forcar):
    cursor.execute(f"SELECT COUNT(*) AS qt FROM {nm_tabela}")
    if cursor.fetchone()["qt"] == 0:
        return True
    if forcar:
        cursor.execute("SET FOREIGN_KEY_CHECKS=0")
        cursor.execute(f"DELETE FROM {nm_tabela}")
        cursor.execute("SET FOREIGN_KEY_CHECKS=1")
        return True
    return False


def registrar(nm_tabela, qt_linhas, nota=""):
    resumo.append((nm_tabela, qt_linhas, nota))


# ---------------------------------------------------------------- segurança
def migrarSeguranca(forcar):
    dir_portal = diretorio_dados / "portal"
    with abrirTransacao() as cursor:
        arq_usuarios = dir_portal / "usuarios.json"
        if arq_usuarios.exists() and tabelaVazia(cursor, "tb_usuario", forcar):
            lista_usuarios = lerJson(arq_usuarios)
            for usuario in lista_usuarios:
                cursor.execute(
                    """INSERT INTO tb_usuario (nm_usuario, nm_nome, nm_perfil, ic_ativo, js_apps, ds_salt, ds_hash,
                       qt_iteracoes, ic_pimenta, ic_trocar_senha, qt_falhas, qt_bloqueios, dt_bloqueado_ate, js_bloqueio_dispositivo,
                       dt_criado, dt_ultimo_acesso) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (usuario["usuario"], usuario.get("nome") or usuario["usuario"], usuario.get("perfil", "usuario"),
                     int(bool(usuario.get("ativo", True))),
                     json.dumps(usuario["apps"], ensure_ascii=False) if usuario.get("apps") is not None else None,
                     usuario["salt"], usuario["hash"], int(usuario.get("iteracoes", 0)),
                     int(bool(usuario.get("pimenta"))), int(bool(usuario.get("trocar_senha"))),
                     int(usuario.get("falhas", 0)), int(usuario.get("bloqueios", 0)), lerData(usuario.get("bloqueado_ate")),
                     json.dumps(usuario["bloqueio_dispositivo"], ensure_ascii=False) if usuario.get("bloqueio_dispositivo") else None,
                     lerData(usuario.get("criado_em")), lerData(usuario.get("ultimo_acesso"))),
                )
            registrar("tb_usuario", len(lista_usuarios))
        else:
            registrar("tb_usuario", 0, "pulada (já tem dados ou sem arquivo)")

        arq_sessoes = dir_portal / "sessoes.json"
        if arq_sessoes.exists() and tabelaVazia(cursor, "tb_sessao", forcar):
            lista_sessoes = lerJson(arq_sessoes)
            for sessao in lista_sessoes:
                cursor.execute("INSERT INTO tb_sessao (ds_hash, nm_usuario, dt_criado, dt_expira) VALUES (%s,%s,%s,%s)",
                               (sessao["hash"], sessao["usuario"], lerData(sessao["criado_em"]), lerData(sessao["expira_em"])))
            registrar("tb_sessao", len(lista_sessoes))

        arq_dispositivos = dir_portal / "dispositivos.json"
        if arq_dispositivos.exists() and tabelaVazia(cursor, "tb_dispositivo", forcar):
            lista_dispositivos = lerJson(arq_dispositivos)
            for dispositivo in lista_dispositivos:
                cursor.execute(
                    "INSERT INTO tb_dispositivo (nm_usuario, ds_dispositivo, ds_ip, nm_host, dt_visto) VALUES (%s,%s,%s,%s,%s)",
                    (dispositivo["usuario"], dispositivo["id"], dispositivo.get("ip"), dispositivo.get("host"),
                     lerData(dispositivo.get("visto_em"))))
            registrar("tb_dispositivo", len(lista_dispositivos))

        arq_acessos = dir_portal / "acessos.jsonl"
        if arq_acessos.exists() and tabelaVazia(cursor, "tb_acesso_log", forcar):
            lista_linhas = []
            for tx_linha in arq_acessos.read_text(encoding="utf-8").splitlines():
                if not tx_linha.strip():
                    continue
                try:
                    evento = json.loads(tx_linha)
                except json.JSONDecodeError:
                    continue
                lista_linhas.append((lerData(evento.get("quando")), evento.get("evento", ""), evento.get("usuario"),
                                     evento.get("detalhe"), evento.get("ip"), evento.get("computador")))
            cursor.executemany(
                "INSERT INTO tb_acesso_log (dt_evento, nm_evento, nm_usuario, ds_detalhe, ds_ip, nm_computador) VALUES (%s,%s,%s,%s,%s,%s)",
                lista_linhas)
            registrar("tb_acesso_log", len(lista_linhas))


# ---------------------------------------------------------------- Mesa de Boletas
def migrarBoletador(forcar):
    dir_boletador = diretorio_dados / "boletador"
    with abrirTransacao() as cursor:
        arq_erros = dir_boletador / "controle_erros.json"
        if arq_erros.exists() and tabelaVazia(cursor, "tb_boletador_card", forcar):
            lista_cards = lerJson(arq_erros)
            cursor.execute("DELETE FROM tb_boletador_card_conexao")
            cursor.execute("DELETE FROM tb_boletador_card_historico")
            arq_snapshot = dir_boletador / "snapshot_ata.json"
            dic_snapshot = lerJson(arq_snapshot) if arq_snapshot.exists() else {}
            qt_conexoes = qt_historico = 0
            for card in lista_cards:
                cursor.execute(
                    """INSERT INTO tb_boletador_card (id_card, ds_titulo, ds_descricao, nm_coluna, nm_prioridade,
                       qt_ocorrencias, ds_solucao, nm_categoria, ds_causa_raiz, dt_criado, dt_atualizado,
                       dt_ultima_ocorrencia, dt_resolvido, qt_ocorrencias_ata) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (card["id"], card["titulo"], card.get("descricao", ""), card["coluna"], card["prioridade"],
                     int(card.get("ocorrencias", 0)), card.get("solucao", ""), card.get("categoria"), card.get("causa_raiz", ""),
                     lerData(card.get("criado_em")), lerData(card.get("atualizado_em")), soData(card.get("ultima_ocorrencia")),
                     lerData(card.get("resolvido_em")), dic_snapshot.get(str(card["id"]))))
            for card in lista_cards:  # conexões depois, para todas as chaves já existirem
                for id_conectado in card.get("conexoes", []):
                    cursor.execute("INSERT IGNORE INTO tb_boletador_card_conexao (id_card, id_card_conectado) VALUES (%s,%s)",
                                   (card["id"], id_conectado))
                    qt_conexoes += 1
                for historico in card.get("historico", []):
                    cursor.execute(
                        "INSERT INTO tb_boletador_card_historico (id_card, dt_registro, qt_ocorrencias, ds_nota) VALUES (%s,%s,%s,%s)",
                        (card["id"], lerData(historico.get("data")), int(historico.get("qtd", 0)), historico.get("nota", "")))
                    qt_historico += 1
            cursor.execute("SELECT COALESCE(MAX(id_card),0)+1 AS prox FROM tb_boletador_card")
            cursor.execute(f"ALTER TABLE tb_boletador_card AUTO_INCREMENT = {cursor.fetchone()['prox']}")
            registrar("tb_boletador_card", len(lista_cards), f"snapshot da ata incluído na coluna qt_ocorrencias_ata")
            registrar("tb_boletador_card_conexao", qt_conexoes)
            registrar("tb_boletador_card_historico", qt_historico)
        else:
            registrar("tb_boletador_card", 0, "pulada (já tem dados ou sem arquivo)")


# ---------------------------------------------------------------- Solicitações
def migrarSolicitacoes(forcar):
    dir_solicitacoes = diretorio_dados / "solicitacoes"
    with abrirTransacao() as cursor:
        arq_clientes = dir_solicitacoes / "clientes.json"
        if arq_clientes.exists() and tabelaVazia(cursor, "tb_cliente", forcar):
            lista_clientes = lerJson(arq_clientes)
            cursor.executemany("INSERT IGNORE INTO tb_cliente (ds_cliente) VALUES (%s)", [(cliente,) for cliente in lista_clientes])
            registrar("tb_cliente", len(lista_clientes))
        arq_solicitacoes = dir_solicitacoes / "solicitacoes.json"
        if arq_solicitacoes.exists() and tabelaVazia(cursor, "tb_solicitacao", forcar):
            cursor.execute("DELETE FROM tb_solicitacao_historico")
            lista_registros = lerJson(arq_solicitacoes)
            qt_historico = 0
            for registro in lista_registros:
                nm_evidencia = ntpath.basename(registro["evidencia"]) if registro.get("evidencia") else None
                cursor.execute(
                    """INSERT INTO tb_solicitacao (id_solicitacao, ds_cliente, nm_solicitante, dt_solicitacao, nm_tipo,
                       ds_descricao, nm_status, dt_conclusao, nm_evidencia, nm_prioridade, nm_registrado_por, ds_competencia, dt_sla)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (registro["id"], registro["cliente"], registro.get("solicitante"), soData(registro.get("data")),
                     registro.get("tipo"), registro.get("descricao", ""), registro["status"], soData(registro.get("data_conclusao")),
                     nm_evidencia, registro.get("prioridade"), registro.get("registrado_por"), registro.get("competencia"),
                     soData(registro.get("sla_data"))))
                for historico in registro.get("historico", []):
                    cursor.execute(
                        "INSERT INTO tb_solicitacao_historico (id_solicitacao, dt_evento, nm_evento, ds_detalhe, nm_usuario) VALUES (%s,%s,%s,%s,%s)",
                        (registro["id"], lerData(historico.get("quando")), historico.get("evento"), historico.get("detalhe"),
                         historico.get("usuario")))
                    qt_historico += 1
            cursor.execute("SELECT COALESCE(MAX(id_solicitacao),0)+1 AS prox FROM tb_solicitacao")
            cursor.execute(f"ALTER TABLE tb_solicitacao AUTO_INCREMENT = {cursor.fetchone()['prox']}")
            registrar("tb_solicitacao", len(lista_registros), "evidência guardada só pelo nome do arquivo")
            registrar("tb_solicitacao_historico", qt_historico)
        else:
            registrar("tb_solicitacao", 0, "pulada (já tem dados ou sem arquivo)")


# ---------------------------------------------------------------- Conciliação de Caixa
def migrarCaixa(forcar):
    dir_caixa = diretorio_dados / "conciliacao_caixa" / "estado"
    arq_categorias = Path(__file__).resolve().parents[1] / "assets" / "categorias.json"
    with abrirTransacao() as cursor:
        if arq_categorias.exists() and tabelaVazia(cursor, "tb_caixa_categoria", forcar):
            lista_categorias = []
            for nm_categoria in lerJson(arq_categorias):
                nm_categoria = str(nm_categoria).strip()
                if nm_categoria and nm_categoria not in lista_categorias:
                    lista_categorias.append(nm_categoria)
            cursor.executemany("INSERT INTO tb_caixa_categoria (nm_categoria, nr_ordem) VALUES (%s,%s)",
                               [(nm_categoria, nr_ordem) for nr_ordem, nm_categoria in enumerate(lista_categorias)])
            registrar("tb_caixa_categoria", len(lista_categorias))
        if dir_caixa.exists() and tabelaVazia(cursor, "tb_caixa_estado", forcar):
            qt_estados = 0
            for arquivo in sorted(dir_caixa.glob("*.json")):
                if arquivo.name == "aut2_monitor.json":
                    continue
                nm_planilha = arquivo.name[:-len(".json")]
                for id_carteira, estado in lerJson(arquivo).items():
                    cursor.execute(
                        "INSERT INTO tb_caixa_estado (nm_planilha, id_carteira, ds_obs, nm_status, ds_comentario) VALUES (%s,%s,%s,%s,%s)",
                        (nm_planilha, str(id_carteira), estado.get("obs", ""), estado.get("status", ""), estado.get("comentario", "")))
                    qt_estados += 1
            registrar("tb_caixa_estado", qt_estados)
        arq_monitor = dir_caixa / "aut2_monitor.json"
        if arq_monitor.exists() and tabelaVazia(cursor, "tb_caixa_monitor_email", forcar):
            lista_monitor = lerJson(arq_monitor)
            for email in lista_monitor:
                cursor.execute(
                    """INSERT INTO tb_caixa_monitor_email (ds_token, nm_imagem, nm_status, qt_prazo_horas, dt_criado, dt_enviado,
                       ds_topico, ds_assunto, ds_para, nm_respondido_por, dt_respondido, ds_entry_id, ds_corpo, ds_nota_anexos,
                       nm_slack, ds_alerta_prazo) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (email["token"], email.get("imagem"), email["status"], email.get("prazo_horas"), lerData(email.get("criado_em")),
                     lerData(email.get("enviado_em")), email.get("topico"), email.get("assunto"), email.get("para"),
                     email.get("respondido_por"), lerData(email.get("respondido_em")), email.get("entry_id"), email.get("corpo"),
                     email.get("nota_anexos"), email.get("slack"), None if email.get("alerta_prazo") is None else str(email["alerta_prazo"])))
            registrar("tb_caixa_monitor_email", len(lista_monitor))


# ---------------------------------------------------------------- Crava Cotas
def migrarCrava(forcar):
    dir_crava = diretorio_dados / "crava_cotas"
    with abrirTransacao() as cursor:
        arq_cadastro = dir_crava / "cadastro.xlsx"
        if arq_cadastro.exists() and tabelaVazia(cursor, "tb_crava_cadastro", forcar):
            df_cadastro = pd.read_excel(arq_cadastro, dtype=str)
            lista_linhas = [tuple(textoOuNulo(valor) for valor in linha[:13]) for linha in df_cadastro.itertuples(index=False, name=None)]
            cursor.executemany(
                """INSERT INTO tb_crava_cadastro (ds_grupo_proc_paralelo, id_cliente, nm_apelido, id_pessoa, ds_zera_caixa,
                   ds_tipo_cliente, ds_ativo, ds_tipo_controle, ds_implantacao, ds_status, ds_data_dia, ds_data_atualizacao,
                   ds_ativo_cetip) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", lista_linhas)
            registrar("tb_crava_cadastro", len(lista_linhas), "colunas lidas por posição (os acentos do cabeçalho vêm corrompidos)")
        arq_tabela = dir_crava / "tabela.json"
        if arq_tabela.exists() and tabelaVazia(cursor, "tb_crava_leitura", forcar):
            cursor.execute("DELETE FROM tb_crava_leitura_meta")
            dic_tabela = lerJson(arq_tabela)
            cursor.execute("INSERT INTO tb_crava_leitura_meta (id_meta, dt_lido, ic_concluido) VALUES (1,%s,%s)",
                           (lerData(dic_tabela.get("lido_em")), int(bool(dic_tabela.get("concluido")))))
            qt_linhas = 0
            for nm_dia, dia in dic_tabela.get("dias", {}).items():
                cursor.execute(
                    "INSERT INTO tb_crava_leitura (nm_dia, ds_situacao, vl_progresso, ds_diagnostico, ds_data) VALUES (%s,%s,%s,%s,%s)",
                    (nm_dia, dia.get("situacao"), dia.get("progresso"), dia.get("diagnostico"), dia.get("data")))
                for nr_linha, linha in enumerate(dia.get("linhas", [])):
                    linha = (list(linha) + [None] * 5)[:5]
                    cursor.execute(
                        """INSERT INTO tb_crava_leitura_linha (nm_dia, nr_linha, ds_id_exec, nm_fundo, nr_cnpj, ds_valor_cota, ds_status)
                           VALUES (%s,%s,%s,%s,%s,%s,%s)""", (nm_dia, nr_linha, *linha))
                    qt_linhas += 1
            registrar("tb_crava_leitura", len(dic_tabela.get("dias", {})))
            registrar("tb_crava_leitura_linha", qt_linhas)


# ---------------------------------------------------------------- Britech
def migrarBritech(forcar):
    arq_ids = diretorio_dados / "britech" / "ids_cliente.xlsx"
    with abrirTransacao() as cursor:
        if arq_ids.exists() and tabelaVazia(cursor, "tb_britech_carteira", forcar):
            lista_ids = []
            for id_cliente in pd.read_excel(arq_ids, dtype=str)["id_cliente"].dropna():
                id_cliente = str(id_cliente).strip()
                if id_cliente and id_cliente not in lista_ids:
                    lista_ids.append(id_cliente)
            cursor.executemany("INSERT INTO tb_britech_carteira (id_cliente, nr_ordem) VALUES (%s,%s)",
                               [(id_cliente, nr_ordem) for nr_ordem, id_cliente in enumerate(lista_ids)])
            registrar("tb_britech_carteira", len(lista_ids))


# ---------------------------------------------------------------- Extratos
def caminhoRelativoExtratos(tx_caminho):
    """Guarda só a parte depois da pasta 'Extratos' (o caminho absoluto antigo muda de máquina para máquina)."""
    lista_partes = [parte for parte in ntpath.normpath(tx_caminho).replace("/", "\\").split("\\") if parte]
    if "Extratos" in lista_partes:
        nr_posicao = len(lista_partes) - 1 - lista_partes[::-1].index("Extratos")
        return "/".join(lista_partes[nr_posicao + 1:])
    return ntpath.basename(tx_caminho)


def migrarExtratos(forcar):
    dir_extratos = diretorio_dados / "extratos"
    with abrirTransacao() as cursor:
        arq_planilha = dir_extratos / "Template_Fundos_Ativos.xlsx"
        if arq_planilha.exists() and tabelaVazia(cursor, "tb_extratos_fundo_cotista", forcar):
            df_dados = pd.read_excel(arq_planilha, sheet_name="Dados", dtype=str).dropna(how="all")
            lista_linhas = [tuple(textoOuNulo(valor) for valor in linha[:5]) for linha in df_dados.itertuples(index=False, name=None)]
            cursor.executemany(
                "INSERT INTO tb_extratos_fundo_cotista (nm_fundo, nr_cnpj, nm_cotista, nr_doc_cotista, ds_emails) VALUES (%s,%s,%s,%s,%s)",
                lista_linhas)
            registrar("tb_extratos_fundo_cotista", len(lista_linhas))
            if tabelaVazia(cursor, "tb_extratos_cotista_legado", forcar):
                df_legado = pd.read_excel(arq_planilha, sheet_name="Planilha1", header=None, dtype=str).dropna(how="all")
                lista_legado = [(textoOuNulo(linha[0]), textoOuNulo(linha[1])) for linha in df_legado.itertuples(index=False, name=None)]
                cursor.executemany("INSERT INTO tb_extratos_cotista_legado (nm_cotista, nr_doc) VALUES (%s,%s)", lista_legado)
                registrar("tb_extratos_cotista_legado", len(lista_legado), "aba Planilha1 (o app não usava)")
        dir_rodadas = dir_extratos / "Extratos" / "_rodadas"
        if dir_rodadas.exists() and tabelaVazia(cursor, "tb_extratos_rodada", forcar):
            qt_rodadas = qt_itens = 0
            for arquivo in sorted(dir_rodadas.glob("*.json")):
                try:
                    rodada = lerJson(arquivo)
                    dt_inicio = datetime.fromisoformat(rodada["inicio"])
                except (ValueError, KeyError, OSError):
                    continue
                cursor.execute("INSERT INTO tb_extratos_rodada (dt_inicio, dt_referencia, ic_encerrada) VALUES (%s,%s,%s)",
                               (dt_inicio, datetime.fromisoformat(rodada["data"]).date(), int(bool(rodada.get("encerrada")))))
                id_rodada = cursor.lastrowid
                for nr_item, item in enumerate(rodada.get("itens", [])):
                    cursor.execute(
                        "INSERT INTO tb_extratos_rodada_item (id_rodada, nr_item, ds_emails, qt_linhas, js_cnpjs) VALUES (%s,%s,%s,%s,%s)",
                        (id_rodada, nr_item, item.get("emails"), item.get("linhas"), json.dumps(item.get("cnpjs", {}), ensure_ascii=False)))
                    nr_ordem = 0
                    for nm_fundo, lista_cotistas in item.get("fundos", []):
                        if not lista_cotistas:  # fundo sem cotista: linha marcadora (nm_cotista NULL), como o app faz
                            cursor.execute(
                                """INSERT INTO tb_extratos_rodada_cotista (id_rodada, nr_item, nr_ordem, nm_fundo, nm_cotista, nr_doc_cotista)
                                   VALUES (%s,%s,%s,%s,NULL,NULL)""", (id_rodada, nr_item, nr_ordem, nm_fundo))
                            nr_ordem += 1
                        for cotista in lista_cotistas:
                            cursor.execute(
                                """INSERT INTO tb_extratos_rodada_cotista (id_rodada, nr_item, nr_ordem, nm_fundo, nm_cotista, nr_doc_cotista)
                                   VALUES (%s,%s,%s,%s,%s,%s)""", (id_rodada, nr_item, nr_ordem, nm_fundo, cotista[0], cotista[1]))
                            nr_ordem += 1
                    qt_itens += 1
                for nr_item, tx_reenvio in rodada.get("reenvios", {}).items():
                    cursor.execute("INSERT INTO tb_extratos_rodada_reenvio (id_rodada, nr_item, dt_reenvio) VALUES (%s,%s,%s)",
                                   (id_rodada, int(nr_item), datetime.fromisoformat(tx_reenvio)))
                qt_rodadas += 1
            registrar("tb_extratos_rodada", qt_rodadas)
            registrar("tb_extratos_rodada_item", qt_itens)
        dir_meses = dir_extratos / "Extratos"
        if dir_meses.exists() and tabelaVazia(cursor, "tb_extratos_anexo_salvo", forcar):
            qt_anexos = 0
            for arquivo in sorted(dir_meses.glob("*/_salvos.json")):
                nm_mes = arquivo.parent.name
                for ds_chave, ds_caminho in lerJson(arquivo).items():
                    cursor.execute("INSERT INTO tb_extratos_anexo_salvo (ds_chave, nm_mes, ds_caminho) VALUES (%s,%s,%s)",
                                   (ds_chave, nm_mes, caminhoRelativoExtratos(ds_caminho)))
                    qt_anexos += 1
            registrar("tb_extratos_anexo_salvo", qt_anexos)


def migrarTudo(forcar=False):
    for funcao_migrar in (migrarSeguranca, migrarBoletador, migrarSolicitacoes, migrarCaixa, migrarCrava, migrarBritech, migrarExtratos):
        funcao_migrar(forcar)
    print(f"{'tabela':<44}{'linhas':>8}  observação")
    for nm_tabela, qt_linhas, tx_nota in resumo:
        print(f"{nm_tabela:<44}{qt_linhas:>8}  {tx_nota}")


if __name__ == "__main__":
    migrarTudo(forcar="--forcar" in sys.argv)
