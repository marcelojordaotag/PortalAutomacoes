"""Conciliação de Caixa (Streamlit)

Sobe a planilha, lê a aba "Caixa" (id_carteira, nm_carteira, vl_saldo_caixa_tag, vl_saldo_caixa_adm,
vl_saldo_caixa_dif) e deixa preencher, por carteira:
  - OBS: escolhida em uma lista de categorias prontas (botão para adicionar/remover categorias);
  - Comentário: texto livre para o que não vira categoria;
  - Aplicar em lote: mesma OBS/status em todas as linhas exibidas (respeita os filtros);
  - Status: verde = conciliado, amarelo = em andamento, vermelho = não tem como resolver.
A coluna "Fora de ±1" marca as diferenças menores que -1 ou maiores que 1.
O preenchimento é salvo sozinho (por nome de arquivo) e a planilha pode ser baixada com OBS e Status.
"""
import html
import io
import os
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st
from openpyxl import load_workbook
from openpyxl.styles import PatternFill

from app.utilitarias import email_gmail
from app.utilitarias.componentes import seletorIds
from app.utilitarias.tema import topo

from app.database.caixa import gravarCategorias, gravarEstado, gravarMonitor, lerEstado, listarCategorias, listarMonitor, removerMonitor
from app.database.carteiras import listarIdsCarteiras
from app.paginas.conciliacao_caixa import pdf_extratos

ABA = "Caixa"
COLUNAS = ["id_carteira", "nm_carteira", "vl_saldo_caixa_tag", "vl_saldo_caixa_adm", "vl_saldo_caixa_dif"]
LIMITE = 1.0
STATUS = {"🟢 Conciliado": "C6EFCE", "🟡 Em andamento": "FFEB9C", "🔴 Sem solução": "FFC7CE"}
CATEGORIAS_INICIAIS = ["IR JUROS", "APLICAÇÃO + RESGATE AQUA"]


def carregarCategorias():
    lista_categorias = listarCategorias() or CATEGORIAS_INICIAIS
    return list(dict.fromkeys(str(categoria).strip() for categoria in lista_categorias if str(categoria).strip()))


def salvarCategorias(lista_categorias):
    gravarCategorias(lista_categorias)


def carregarEstado(nome):
    return lerEstado(nome)


def salvarEstado(nome, estado):
    gravarEstado(nome, estado)


def lerCaixa(dados):
    try:
        df = pd.read_excel(io.BytesIO(dados), sheet_name=ABA)
    except ValueError:
        raise ValueError(f'A planilha não tem a aba "{ABA}".')
    df.columns = [str(coluna).strip() for coluna in df.columns]
    faltam = [coluna for coluna in COLUNAS if coluna not in df.columns]
    if faltam:
        raise ValueError("Colunas não encontradas na aba Caixa: " + ", ".join(faltam))
    cols = COLUNAS + (["obs"] if "obs" in df.columns else [])
    df = df[cols].dropna(subset=["id_carteira"]).copy()
    df["id_carteira"] = df["id_carteira"].astype(int).astype(str)
    for coluna in COLUNAS[2:]:
        df[coluna] = pd.to_numeric(df[coluna], errors="coerce")
    return df.reset_index(drop=True)


def gravar(nome, tabela):
    salvarEstado(nome, {linha["id_carteira"]: {"obs": linha["OBS"], "status": linha["Status"], "comentario": linha["Comentário"]}
                         for _, linha in tabela.iterrows() if linha["OBS"] or linha["Status"] or linha["Comentário"]})


def baixarPlanilha(dados, tabela):
    """Devolve a planilha original com OBS, Status e Fora de ±1 gravados na aba Caixa."""
    pasta_trabalho = load_workbook(io.BytesIO(dados))
    planilha_aba = pasta_trabalho[ABA]
    cab = {str(planilha_aba.cell(1, coluna).value).strip(): coluna for coluna in range(1, planilha_aba.max_column + 1) if planilha_aba.cell(1, coluna).value}
    col_obs = cab.get("obs", planilha_aba.max_column + 1)
    col_status = max(col_obs, planilha_aba.max_column) + 1
    col_fora = col_status + 1
    col_coment = col_fora + 1
    planilha_aba.cell(1, col_obs, "obs")
    planilha_aba.cell(1, col_status, "status")
    planilha_aba.cell(1, col_fora, "fora_de_1")
    planilha_aba.cell(1, col_coment, "comentario")
    linhas = {str(planilha_aba.cell(linha_planilha, cab["id_carteira"]).value).split(".")[0]: linha_planilha for linha_planilha in range(2, planilha_aba.max_row + 1)}
    for _, linha_tabela in tabela.iterrows():
        linha_planilha = linhas.get(linha_tabela["id_carteira"])
        if linha_planilha is None:
            continue
        planilha_aba.cell(linha_planilha, col_obs, linha_tabela["OBS"] or None)
        planilha_aba.cell(linha_planilha, col_status, linha_tabela["Status"] or None)
        planilha_aba.cell(linha_planilha, col_coment, linha_tabela["Comentário"] or None)
        planilha_aba.cell(linha_planilha, col_fora, "Sim" if linha_tabela["Fora de ±1"] else None)
        if linha_tabela["Status"] in STATUS:
            for coluna in range(1, col_coment + 1):
                planilha_aba.cell(linha_planilha, coluna).fill = PatternFill("solid", fgColor=STATUS[linha_tabela["Status"]])
    saida = io.BytesIO()
    pasta_trabalho.save(saida)
    return saida.getvalue()


topo("Conciliação de Caixa", "Diferenças de caixa entre a TAG e a administradora, com observação e status por carteira",
     app="caixa")

aba_aut1, aba_aut3, aba_caixa = st.tabs(["Aut1", "Aut3", "Conciliação de Caixa"])

def textoErroGmail(erro):
    if isinstance(erro, email_gmail.GmailNaoConectadoErro):
        return "A conexão com a conta Google expirou ou não existe. Conecte-se de novo (\"Conectar ao Google\" na lateral)."
    return str(erro)


def criarRascunhoImagem(nome_img, bytes_img, token):
    """Cria no Gmail um e-mail novo com a imagem no corpo (e a assinatura do Gmail), sem destinatários. Não envia.
    Devolve o link do rascunho. O código escondido no corpo permite achar este e-mail em Enviados e a conversa dele."""
    cid = "imagem_email@tag"
    servico = email_gmail.servicoDaSessao()
    ds_tipo = {"png": "png", "gif": "gif"}.get(Path(nome_img).suffix.lower().lstrip("."), "jpeg")
    ds_html = (f'<p><img src="cid:{cid}" style="max-width:700px"></p>'
               f'<span style="display:none;mso-hide:all;font-size:1px;color:#ffffff">{token}</span><br>{email_gmail.assinaturaHtml(servico)}')
    mensagem_email = email_gmail.montarMime("", "", ds_html, lista_imagens_bytes=[(cid, bytes_img, ds_tipo)], ds_texto_puro=f"ref: {token}")
    return email_gmail.criarRascunho(servico, mensagem_email)


def lerEnv():
    """Lê do ambiente (env/.env.segredo local ou Parameter Store) o webhook do Slack, que é um segredo."""
    return {chave: os.environ[chave] for chave in ("SLACK_WEBHOOK_AUT2", "SLACK_CAMPO", "PORTAL_URL") if chave in os.environ}


def carregarMonitor():
    return listarMonitor()


def salvarMonitor(lista):
    gravarMonitor(lista)


def enviarSlack(texto):
    """Manda o texto ao webhook do Slack. Devolve 'enviado' ou 'erro: ...'."""
    from app.utilitarias.limite_slack import liberarConteudo, postarComLimite, segundosParaRepetir

    dict_ambiente = lerEnv()
    url = dict_ambiente.get("SLACK_WEBHOOK_AUT2", "")
    if not url:
        return "erro: SLACK_WEBHOOK_AUT2 não configurado no ambiente"
    espera = segundosParaRepetir(texto)
    if espera:
        return f"erro: mesma mensagem acabou de ser enviada; aguarde {espera}s"
    try:
        resposta_slack = postarComLimite(url, json={dict_ambiente.get("SLACK_CAMPO", "teste_enviar_msg"): texto}, timeout=10)
        corpo = resposta_slack.json() if resposta_slack.headers.get("content-type", "").startswith("application/json") else {}
        if resposta_slack.ok and corpo.get("ok", True):
            return "enviado"
        liberarConteudo(texto)
        return f"erro: Slack respondeu {resposta_slack.status_code} {corpo.get('error', resposta_slack.text[:80])}"
    except Exception as excecao:
        liberarConteudo(texto)
        return f"erro: {excecao}"


def avisarSlack(reg):
    """Aviso de resposta: o texto que a pessoa escreveu e, se houver, a nota de anexos/imagens."""
    texto = reg.get("corpo") or ""
    nota = reg.get("nota_anexos") or ""
    texto = (texto + ("\n\n" if texto and nota else "") + nota).strip()
    if reg.get("entry_id"):  # id da resposta no Gmail: o link abre a conversa na conta de quem clica
        texto += f"\n\nAbrir o e-mail no Gmail: https://mail.google.com/mail/u/0/#all/{reg['entry_id']}"
    return enviarSlack(texto or f"(resposta de {reg.get('respondido_por', '?')} sem texto)")


def notaDeAnexos(mensagem):
    """Avisa que a resposta traz anexos ou imagens, que o Slack não recebe (o webhook só aceita texto).
    Imagem no corpo só conta se vier antes da mensagem citada e tiver 20 KB ou mais (logos de assinatura são menores)."""
    html_corpo = str(mensagem.corpo_html or "")
    marcas = [html_corpo.find(marca_busca) for marca_busca in ('class="gmail_quote"', 'id="divRplyFwdMsg"', "<b>De:", "<b>From:", "Enviada em:", "Mensagem original")]
    limite = min([ordem_item for ordem_item in marcas if ordem_item >= 0], default=len(html_corpo))
    anexos, imagens = 0, 0
    for anexo in mensagem.anexos:
        if anexo.embutido:
            if f"cid:{anexo.cid}" in html_corpo and html_corpo.find(f"cid:{anexo.cid}") < limite and anexo.tamanho >= 20 * 1024:
                imagens += 1
        else:
            anexos += 1
    partes = []
    if anexos:
        partes.append(f"{anexos} anexo(s)")
    if imagens:
        partes.append(f"{imagens} imagem(ns)")
    return f"(a resposta tem {' e '.join(partes)}; veja no e-mail)" if partes else ""


def textoDaResposta(corpo, limite=3000):
    """Só o que a pessoa escreveu: corta a mensagem citada (De:, From:, -----Original...) e a assinatura
    (despedidas como Atenciosamente/Att/Abs, '--' e 'Enviado do meu ...'). Tira também as marcas de imagem."""
    corte = re.search(r"^\s*(De:|From:|-{3,}\s*(Mensagem original|Original Message)|_{5,}|Em .{5,160} escreveu:|On .{5,160} wrote:)",
                      corpo, flags=re.IGNORECASE | re.MULTILINE)
    texto = corpo[: corte.start()] if corte else corpo
    texto = re.sub(r"\[(cid:[^\]]*|image\d+\.\w+|Imagem[^\]]*)\]", "", texto, flags=re.IGNORECASE)
    despedida = re.search(
        r"^\s*(Atenciosamente|Att\.?|Abs\.?|Abraços?|Cordialmente|Cumprimentos|Grato|Grata|Best regards|Kind regards|"
        r"Regards|Sincerely|Enviado do meu .*|Sent from my .*|-{2,}\s*)[,.!:]?\s*$",
        texto, flags=re.IGNORECASE | re.MULTILINE)
    if despedida:
        texto = texto[: despedida.start()]
    return texto.strip()[:limite]


def conferirMonitor(lista):
    """Procura no Gmail o e-mail enviado (pelo código escondido no corpo) e depois a resposta dele, na mesma conversa.
    Quando a resposta chega, avisa no Slack uma única vez. Devolve True se algo mudou."""
    abertos = [registro for registro in lista if registro["status"] in ("aguardando envio", "aguardando resposta")
               or (registro["status"] == "respondido" and registro.get("slack") != "enviado")]
    if not abertos:
        return False
    servico = email_gmail.servicoDaSessao()
    mudou = False
    lista_enviados = None  # busca em Enviados uma vez só por conferência (do registro mais antigo em diante)
    for registro in abertos:
        if registro["status"] == "aguardando envio":
            if lista_enviados is None:
                dt_inicio = min(datetime.fromisoformat(item["criado_em"]) for item in abertos if item["status"] == "aguardando envio") - timedelta(minutes=1)
                lista_enviados = email_gmail.buscarMensagens(servico, f"in:sent after:{email_gmail.segundosEpoch(dt_inicio)}")
            original = None
            for mensagem in lista_enviados:  # da mais nova para a mais antiga
                if registro["token"] in (mensagem.corpo_html or "") + (mensagem.corpo or ""):
                    original = mensagem  # segue até a mais antiga: respostas citam o código, mas saem depois
            if original is not None:
                registro.update(status="aguardando resposta", topico=original.id_conversa, assunto=original.assunto,
                                para=", ".join(sorted(original.para)), enviado_em=original.quando.isoformat(timespec="seconds"))
                mudou = True
        if registro["status"] == "aguardando resposta":
            desde = datetime.fromisoformat(registro["enviado_em"])
            # Resposta = mensagem da mesma conversa, que não está em Enviados (não é do próprio remetente) e chegou depois do envio
            respostas = [mensagem for mensagem in email_gmail.mensagensDaConversa(servico, registro.get("topico", ""))
                         if "SENT" not in mensagem.rotulos and mensagem.quando > desde] if registro.get("topico") else []
            if respostas:
                resposta = respostas[-1]  # a mais nova
                registro.update(status="respondido", respondido_por=resposta.nome_remetente or resposta.remetente, slack="pendente",
                                entry_id=resposta.id, corpo=textoDaResposta(resposta.corpo or ""), nota_anexos=notaDeAnexos(resposta),
                                respondido_em=resposta.quando.strftime("%d/%m/%Y %H:%M"))
                mudou = True
        if registro["status"] == "aguardando resposta" and registro.get("prazo_horas") and registro.get("alerta_prazo") != "enviado":
            horas = (datetime.now() - datetime.fromisoformat(registro["enviado_em"])).total_seconds() / 3600
            if horas >= registro["prazo_horas"]:
                registro["alerta_prazo"] = enviarSlack(f"Sem resposta há {registro['prazo_horas']}h: \"{registro.get('assunto', '')}\" "
                                                 f"(enviado para {registro.get('para', '')}).")
                mudou = True
        if registro["status"] == "respondido" and registro.get("slack") != "enviado":
            salvarMonitor(lista)  # grava antes de avisar: se cair no meio, não perde a resposta
            registro["slack"] = avisarSlack(registro)
            mudou = True
    if mudou:
        salvarMonitor(lista)
    return mudou


def numeroBr(valor):
    """'1.234,56' -> 1234.56 e '-12,5' -> -12.5. O que não for número fica como veio."""
    if isinstance(valor, str):
        texto_limpo = valor.strip()
        if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?|-?\d+,\d+", texto_limpo):
            return float(texto_limpo.replace(".", "").replace(",", "."))
    return valor


def analisarPdf(dados, metodo, numeros, primeira_linha_cabecalho):
    """Lê o PDF e devolve {'paginas': n, 'texto_por_pagina': [...], 'tabelas': [{'pagina','numero','df'}], 'erro': str|None}."""
    import pdfplumber

    saida = {"paginas": 0, "texto_por_pagina": [], "tabelas": [], "erro": None}
    linhas_cfg = {}
    texto_cfg = {"vertical_strategy": "text", "horizontal_strategy": "text"}
    try:
        with pdfplumber.open(io.BytesIO(dados)) as pdf:
            saida["paginas"] = len(pdf.pages)
            for ordem_item, pg in enumerate(pdf.pages, start=1):
                saida["texto_por_pagina"].append(len(pg.extract_text() or ""))
                tabelas = [] if metodo == "Alinhamento do texto" else pg.extract_tables(linhas_cfg)
                if not tabelas and metodo != "Linhas da tabela":
                    tabelas = pg.extract_tables(texto_cfg)
                for ordem_tabela, aba_atual in enumerate(tabelas, start=1):
                    aba_atual = [[(celula or "").replace("\n", " ").strip() for celula in linha] for linha in aba_atual if any(linha)]
                    if len(aba_atual) < 2:
                        continue
                    df = pd.DataFrame(aba_atual)
                    if primeira_linha_cabecalho:
                        cab = [coluna or f"col{ordem_aux + 1}" for ordem_aux, coluna in enumerate(df.iloc[0])]
                        df = df.iloc[1:].reset_index(drop=True)
                        df.columns = [coluna if cab[:ordem_aux].count(coluna) == 0 else f"{coluna} ({cab[:ordem_aux].count(coluna) + 1})"
                                      for ordem_aux, coluna in enumerate(cab)]  # nomes repetidos ganham sufixo
                    if numeros:
                        df = df.apply(lambda col: col.map(numeroBr))
                    saida["tabelas"].append({"pagina": ordem_item, "numero": ordem_tabela, "df": df})
    except Exception as excecao:  # PDF protegido por senha, corrompido...
        saida["erro"] = str(excecao)
    return saida


def excelDasTabelas(tabelas, uma_aba):
    saida = io.BytesIO()
    with pd.ExcelWriter(saida, engine="openpyxl") as escritor_planilha:
        if uma_aba:
            pd.concat([tabela_pdf["df"].assign(pagina=tabela_pdf["pagina"]) for tabela_pdf in tabelas], ignore_index=True).to_excel(
                escritor_planilha, sheet_name="Tabelas", index=False)
        else:
            for tabela_pdf in tabelas:
                tabela_pdf["df"].to_excel(escritor_planilha, sheet_name=f"p{tabela_pdf['pagina']}_t{tabela_pdf['numero']}"[:31], index=False)
    return saida.getvalue()


def idsBritech():
    """IDs de carteira do app de Rentabilidade (a mesma lista de lá)."""
    return listarIdsCarteiras()


with aba_aut3:
    st.markdown('<p class="secao">Consulta na Britech</p>'
                '<p class="secao-sub">Selecione os IDs das carteiras que serão consultados</p>', unsafe_allow_html=True)
    ids_sel = seletorIds("IDs das carteiras", idsBritech(), "aut2_ids",
                         "Os IDs das carteiras cadastradas aparecem na lista. Também dá para digitar um ID novo.")
    st.button("Consultar na Britech", key="aut2_consultar", disabled=True,
              help="Ainda sem conexão: a rota da Britech será definida depois.")
    st.caption("Consulta ainda não conectada. Os IDs escolhidos já ficam prontos para quando a rota for definida.")

    st.markdown('<p class="secao">Imagem do e-mail</p>'
                '<p class="secao-sub">Suba a imagem que será usada para montar o e-mail</p>', unsafe_allow_html=True)
    imagem = st.file_uploader("Imagem", type=["png", "jpg", "jpeg", "gif"], key="aut2_imagem",
                              label_visibility="collapsed")
    if imagem is not None:
        st.image(imagem, caption=f"{imagem.name} ({imagem.size / 1024:.0f} KB)", width=600)

    prazo = st.selectbox("Avisar no Slack se ninguém responder em", [0, 1, 2, 4, 8, 24], key="aut2_prazo",
                         format_func=lambda horas: "Não avisar" if horas == 0 else f"{horas} hora(s)")
    if st.button("Enviar e-mail com a imagem", key="aut2_email", disabled=imagem is None,
                 help="Cria o rascunho no Gmail com a imagem no corpo; você abre, escolhe os destinatários e envia."):
        token = f"AUT2-{uuid.uuid4().hex[:12]}"
        try:
            ds_link = criarRascunhoImagem(imagem.name, imagem.getvalue(), token)
        except Exception as excecao:  # sem conexão Google ou falha na API
            st.error(f"Não foi possível criar o rascunho no Gmail. {textoErroGmail(excecao)}")
        else:
            lista = carregarMonitor()
            lista.insert(0, {"token": token, "imagem": imagem.name, "status": "aguardando envio", "prazo_horas": prazo,
                             "criado_em": datetime.now().isoformat(timespec="seconds")})
            salvarMonitor(lista)
            st.success(f"Rascunho criado no Gmail: [abrir, escolher os destinatários e enviar]({ds_link}). O app passa a monitorar a resposta.")
    if imagem is None:
        st.caption("Suba a imagem para liberar o botão.")

    st.markdown('<p class="secao">Respostas</p>'
                '<p class="secao-sub">O app acompanha os e-mails enviados e avisa no Slack quando alguém responde</p>',
                unsafe_allow_html=True)

    def _painel():
        lista = carregarMonitor()
        agora = datetime.now()
        ultima = st.session_state.get("aut2_ultima_conf")
        forcar = st.button("Conferir agora", key="aut2_conferir")
        if lista and (forcar or ultima is None or agora - ultima >= timedelta(seconds=55)):
            try:
                conferirMonitor(lista)
                st.session_state["aut2_ultima_conf"] = agora
                st.session_state.pop("aut2_erro_outlook", None)
            except Exception as excecao:  # sem conexão Google ou falha na API
                st.session_state["aut2_erro_outlook"] = textoErroGmail(excecao)
        if st.session_state.get("aut2_erro_outlook"):
            st.warning(f"Não foi possível consultar o Gmail agora: {st.session_state['aut2_erro_outlook']}")
        if not lista:
            st.caption("Nenhum e-mail em monitoramento.")
            return
        ultima = st.session_state.get("aut2_ultima_conf")
        if ultima:
            st.caption(f"Última conferência às {ultima:%H:%M:%S}. O app confere sozinho a cada 1 min enquanto estiver aberto "
                       "e a conexão Google também.")
        def selo(classe, texto):
            return f'<span class="badge {classe}">{html.escape(texto)}</span>' if texto else ""

        linhas = []
        for registro in lista:
            situacao = {"aguardando envio": selo("warn", "Aguardando envio"),
                        "aguardando resposta": selo("ok", "Enviado"),
                        "respondido": selo("ok", "Respondido")}.get(registro["status"], html.escape(registro["status"]))
            sl = str(registro.get("slack", ""))
            if registro["status"] == "aguardando resposta":
                if registro.get("alerta_prazo"):
                    situacao = selo("div", f"Sem resposta há {registro['prazo_horas']}h")
                    sl = "enviado" if registro["alerta_prazo"] == "enviado" else registro["alerta_prazo"]
            aviso = selo("ok", "Avisado") if sl == "enviado" else selo("warn", "Pendente") if sl == "pendente" \
                else selo("div", "Falhou") if sl.startswith("erro") else ""
            linhas.append(
                "<tr>" + "".join(f"<td>{celula}</td>" for celula in (
                    html.escape(registro.get("assunto") or registro["imagem"]), html.escape(registro.get("para", "")), situacao,
                    html.escape(registro.get("enviado_em", "").replace("T", " ")), html.escape(registro.get("respondido_por", "")),
                    html.escape(registro.get("respondido_em", "")), aviso)) + "</tr>")
        cab = "".join(f"<th>{titulo_coluna}</th>" for titulo_coluna in ("E-mail", "Para", "Situação", "Enviado em", "Respondido por",
                                                 "Respondido em", "Slack"))
        st.markdown(
            "<style>.tab-resp{width:100%;border-collapse:collapse;font-size:.9rem;}"
            ".tab-resp th{text-align:left;color:#6B5560;font-size:.74rem;letter-spacing:.06em;text-transform:uppercase;"
            "padding:.4rem .6rem;border-bottom:1px solid #E6D9DE;}"
            ".tab-resp td{padding:.55rem .6rem;border-bottom:1px solid #F0E8EB;}</style>"
            f'<table class="tab-resp"><tr>{cab}</tr>{"".join(linhas)}</table>', unsafe_allow_html=True)
        if any(str(registro.get("slack", "")).startswith("erro") for registro in lista):
            st.error("Falha ao avisar no Slack: " + "; ".join(registro["slack"] for registro in lista if str(registro.get("slack", "")).startswith("erro")))
            if st.button("Tentar avisar de novo", key="aut2_slack_retry"):
                for registro in lista:
                    if str(registro.get("slack", "")).startswith("erro"):
                        registro["slack"] = "pendente"
                salvarMonitor(lista)
                st.rerun(scope="fragment")
        if st.button("Limpar respondidos", key="aut2_limpar", disabled=not any(registro["status"] == "respondido" for registro in lista)):
            removerMonitor([registro["token"] for registro in lista if registro["status"] == "respondido"])
            st.rerun(scope="fragment")

    st.fragment(run_every=timedelta(minutes=1))(_painel)()


def mostrarPdfGenerico(pdf):
    """PDF que não é extrato conhecido: procura tabelas desenhadas ou alinhadas no texto."""
    o1, o2, o3 = st.columns([2, 1, 1])
    metodo = o1.selectbox("Como achar as tabelas", ["Automático", "Linhas da tabela", "Alinhamento do texto"], key="aut3_metodo",
                          help="Automático tenta as linhas desenhadas e, se não houver, o alinhamento do texto. "
                               "Use 'Alinhamento do texto' para tabelas sem bordas.")
    cab1 = o2.checkbox("1ª linha é cabeçalho", value=True, key="aut3_cab")
    nums = o3.checkbox("Números no formato BR", value=True, key="aut3_nums", help="Converte 1.234,56 em número.")
    if pdf is not None:
        with st.spinner("Lendo o PDF..."):
            resultado_calculo = analisarPdf(pdf.getvalue(), metodo, nums, cab1)
        if resultado_calculo["erro"]:
            st.error(f"Não foi possível ler o PDF (pode estar protegido por senha ou corrompido): {resultado_calculo['erro']}")
        else:
            sem_texto = sum(1 for qt_caracteres in resultado_calculo["texto_por_pagina"] if qt_caracteres < 20)
            tabs_ = resultado_calculo["tabelas"]
            linhas_total = sum(len(tabela_pdf["df"]) for tabela_pdf in tabs_)
            if resultado_calculo["paginas"] and sem_texto == resultado_calculo["paginas"]:
                veredito = ("div", "Não dá", "O PDF é imagem (digitalizado): não tem texto para extrair. Precisaria de OCR.")
            elif not tabs_:
                veredito = ("warn", "Difícil", "Tem texto, mas nenhuma tabela foi reconhecida. Teste 'Alinhamento do texto'.")
            elif sem_texto:
                veredito = ("warn", "Parcial", f"{sem_texto} página(s) sem texto (imagem) ficaram de fora.")
            else:
                veredito = ("ok", "Dá", "Tabelas reconhecidas em texto real do PDF.")
            kp = [("", "Páginas", resultado_calculo["paginas"], f"{sem_texto} sem texto"),
                  ("", "Tabelas achadas", len(tabs_), f"{linhas_total} linhas"),
                  (veredito[0], "Conversão", veredito[1], veredito[2])]
            st.markdown('<div class="kpis">' + "".join(
                f'<div class="kpi {cls}"><div class="kpi-label">{rot}</div><div class="kpi-valor">{valor}</div>'
                f'<div class="kpi-sub">{sub_}</div></div>' for cls, rot, valor, sub_ in kp) + "</div>", unsafe_allow_html=True)
            if tabs_:
                rotulos = [f"Página {tabela_pdf['pagina']} · tabela {tabela_pdf['numero']} ({len(tabela_pdf['df'])} linhas x {tabela_pdf['df'].shape[1]} colunas)"
                           for tabela_pdf in tabs_]
                escolha = st.selectbox("Pré-visualizar", range(len(tabs_)), format_func=lambda ordem_item: rotulos[ordem_item], key="aut3_prev")
                st.dataframe(tabs_[escolha]["df"], hide_index=True, use_container_width=True, height=420)
                uma = st.checkbox("Juntar tudo em uma aba só", value=False, key="aut3_uma",
                                  help="Uma aba por tabela é o padrão. Juntar só faz sentido quando as tabelas têm as mesmas colunas.")
                try:
                    xlsx = excelDasTabelas(tabs_, uma)
                except Exception as excecao:
                    st.error(f"Não foi possível montar o Excel: {excecao}")
                else:
                    st.download_button("Baixar Excel", data=xlsx, file_name=f"{Path(pdf.name).stem}.xlsx",
                                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                       key="aut3_baixar")


def mostrarExtrato(pdf, textos, formato):
    resultado_calculo = pdf_extratos.LEITORES[formato](textos)
    mov = resultado_calculo["movimentos"]
    confs = resultado_calculo["conferencias"]
    todas_ok = bool(confs) and all(ok for _, ok in confs)
    kp = [("", "Formato", pdf_extratos.NOMES[formato], "reconhecido automaticamente"),
          ("", "Lançamentos", len(mov), "linhas na movimentação"),
          ("ok" if todas_ok else "div", "Conferência",
           "Fecha" if todas_ok else "Revisar", f"{sum(ok for _, ok in confs)} de {len(confs)} checagens de saldo")]
    st.markdown('<div class="kpis">' + "".join(
        f'<div class="kpi {cls}"><div class="kpi-label">{rot}</div><div class="kpi-valor">{valor}</div>'
        f'<div class="kpi-sub">{sub_}</div></div>' for cls, rot, valor, sub_ in kp) + "</div>", unsafe_allow_html=True)
    if mov.empty:
        st.warning("Formato reconhecido, mas nenhuma linha de movimentação foi lida.")
        return
    with st.expander("Conferências e resumo do extrato", expanded=not todas_ok):
        for nome, ok in confs:
            st.markdown(f'<span class="badge {"ok" if ok else "div"}">{"OK" if ok else "NÃO CONFERE"}</span> {html.escape(nome)}',
                        unsafe_allow_html=True)
        st.dataframe(pd.DataFrame([{"Campo": chave_item, "Valor": f"{valor_resumo:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                                    if isinstance(valor_resumo, float) else str(valor_resumo)} for chave_item, valor_resumo in resultado_calculo["resumo"].items()]), hide_index=True,
                     use_container_width=True)
    def moeda(valor):  # 1.234,56 e -30.000,00; vazio fica vazio
        return "" if pd.isna(valor) else f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    colunas_num = [coluna for coluna in ("Valor", "Débito", "Crédito", "Saldo") if coluna in mov.columns]
    colunas_data = [coluna for coluna in ("Movimentação", "Liquidação", "Data") if coluna in mov.columns]
    exibicao = (mov.style.format(moeda, subset=colunas_num)
                .format(lambda data: data.strftime("%d/%m/%Y"), subset=colunas_data)
                .set_properties(subset=colunas_num, **{"text-align": "right"}))
    st.dataframe(exibicao, hide_index=True, use_container_width=True, height=min(80 + 38 * len(mov), 640))
    st.download_button("Baixar Excel", data=pdf_extratos.excelExtrato(resultado_calculo), file_name=f"{Path(pdf.name).stem}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="aut3_baixar_extrato")


with aba_aut1:
    st.markdown('<p class="secao">PDF para Excel</p>'
                '<p class="secao-sub">Suba o PDF: extratos da XP e do BTG Pactual são reconhecidos sozinhos; '
                'outros PDFs passam pela busca de tabelas</p>', unsafe_allow_html=True)
    pdf = st.file_uploader("PDF", type=["pdf"], key="aut3_pdf", label_visibility="collapsed")
    if pdf is not None:
        try:
            textos_pdf = pdf_extratos.textosPaginas(pdf.getvalue())
        except Exception as excecao:  # PDF protegido por senha ou corrompido
            st.error(f"Não foi possível ler o PDF (pode estar protegido por senha ou corrompido): {excecao}")
        else:
            formato_pdf = pdf_extratos.detectar(textos_pdf)
            if formato_pdf:
                mostrarExtrato(pdf, textos_pdf, formato_pdf)
            else:
                st.caption("Formato de extrato não reconhecido: buscando tabelas no PDF.")
                mostrarPdfGenerico(pdf)

with aba_caixa:
    if "categorias" not in st.session_state:
        st.session_state["categorias"] = carregarCategorias()
    categorias = st.session_state["categorias"]

    with st.expander("Categorias de OBS", expanded=False):
        col_add, col_rem = st.columns(2)
        with col_add:
            with st.form("form_categoria", clear_on_submit=True):
                nova = st.text_input("Nova categoria")
                if st.form_submit_button("Adicionar categoria", use_container_width=True):
                    nova = nova.strip().upper()
                    if not nova:
                        st.warning("Digite o nome da categoria.")
                    elif nova in categorias:
                        st.info("Essa categoria já existe.")
                    else:
                        categorias.append(nova)
                        salvarCategorias(categorias)
                        st.rerun()
        with col_rem:
            remover = st.multiselect("Remover categorias", categorias)
            if remover and st.button("Remover selecionadas", use_container_width=True):
                st.session_state["categorias"] = [categoria for categoria in categorias if categoria not in remover]
                salvarCategorias(st.session_state["categorias"])
                st.rerun()

    arquivo = st.file_uploader("Planilha com a aba Caixa", type=["xlsx", "xlsm"])
    if arquivo is None:
        st.info("Suba a planilha para começar.")
        st.stop()

    dados = arquivo.getvalue()
    try:
        base = lerCaixa(dados)
    except ValueError as excecao:
        st.error(str(excecao))
        st.stop()

    # Chave do estado: muda quando a planilha é trocada, para recarregar o que já foi preenchido.
    chave = f"{arquivo.name}:{len(dados)}"
    if st.session_state.get("chave") != chave:
        salvo = carregarEstado(arquivo.name)
        obs_planilha = base["obs"] if "obs" in base.columns else pd.Series([None] * len(base))
        tabela = base[COLUNAS].copy()
        tabela["OBS"] = [salvo.get(ordem_item, {}).get("obs", obs_original if isinstance(obs_original, str) else "") or ""
                         for ordem_item, obs_original in zip(base["id_carteira"], obs_planilha)]
        tabela["Status"] = [salvo.get(ordem_item, {}).get("status", "") or "" for ordem_item in base["id_carteira"]]
        tabela["Comentário"] = [salvo.get(ordem_item, {}).get("comentario", "") or "" for ordem_item in base["id_carteira"]]
        st.session_state["tabela"] = tabela
        st.session_state["chave"] = chave
        # OBS que já vieram escritas na planilha viram categorias, para poder reutilizar.
        novas = [obs for obs in dict.fromkeys(tabela["OBS"]) if obs and obs not in categorias]
        if novas:
            categorias.extend(novas)
            salvarCategorias(categorias)

    tabela = st.session_state["tabela"]
    tabela["Fora de ±1"] = tabela["vl_saldo_caixa_dif"].abs() > LIMITE

    c1, c3, c2 = st.columns([1, 1, 2])
    filtro_dif = c1.selectbox("Diferença (dif)", ["Todas", "Menor que -1", "Maior que 1", "Fora de ±1"])
    ordem = c3.selectbox("Ordenar por", ["Planilha", "Maior diferença", "Menor diferença"])
    filtro_status = c2.multiselect("Status", ["(sem status)"] + list(STATUS), placeholder="Todos os status")

    visivel = tabela
    dif = visivel["vl_saldo_caixa_dif"]
    if filtro_dif == "Menor que -1":
        visivel = visivel[dif < -LIMITE]
    elif filtro_dif == "Maior que 1":
        visivel = visivel[dif > LIMITE]
    elif filtro_dif == "Fora de ±1":
        visivel = visivel[visivel["Fora de ±1"]]
    if filtro_status:
        visivel = visivel[visivel["Status"].replace("", "(sem status)").isin(filtro_status)]

    if ordem == "Maior diferença":
        visivel = visivel.sort_values("vl_saldo_caixa_dif", key=lambda serie: serie.abs(), ascending=False)
    elif ordem == "Menor diferença":
        visivel = visivel.sort_values("vl_saldo_caixa_dif", key=lambda serie: serie.abs())

    total = len(tabela)
    n_fora = int(tabela["Fora de ±1"].sum())
    n_menor = int((tabela["vl_saldo_caixa_dif"] < -LIMITE).sum())
    n_maior = n_fora - n_menor
    # O card da diferença acompanha o filtro escolhido.
    if filtro_dif == "Menor que -1":
        card_dif = ("Menor que -1", n_menor, "diferença abaixo de -1")
    elif filtro_dif == "Maior que 1":
        card_dif = ("Maior que 1", n_maior, "diferença acima de 1")
    else:
        card_dif = ("Fora de ±1", n_fora, f"{n_menor} abaixo de -1 · {n_maior} acima de 1")
    n_ok = int((tabela["Status"] == "🟢 Conciliado").sum())
    n_andamento = int((tabela["Status"] == "🟡 Em andamento").sum())
    n_sem = int((tabela["Status"] == "🔴 Sem solução").sum())
    n_pendentes = int((tabela["Fora de ±1"] & (tabela["Status"] == "")).sum())
    kpis = [
        ("", "Carteiras", total, "na aba Caixa"),
        ("div", *card_dif),
        ("ok", "Conciliadas", n_ok, f"{n_ok / total:.0%} do total" if total else ""),
        ("vazio", "Em andamento", n_andamento, "amarelo"),
        ("div", "Sem solução", n_sem, "vermelho"),
    ]
    st.markdown(
        '<div class="kpis">' + "".join(
            f'<div class="kpi {cls}"><div class="kpi-label">{rot}</div>'
            f'<div class="kpi-valor">{valor}</div><div class="kpi-sub">{sub_}</div></div>'
            for cls, rot, valor, sub_ in kpis
        ) + "</div>",
        unsafe_allow_html=True,
    )

    if n_pendentes:
        st.warning(f"{n_pendentes} carteira(s) fora de ±1 ainda sem status.")

    opcoes_obs = [""] + sorted(set(categorias) | {obs for obs in tabela["OBS"] if obs})

    with st.expander(f"Aplicar em lote nas {len(visivel)} linhas exibidas", expanded=False):
        b1, b2, b3 = st.columns([2, 2, 1])
        lote_obs = b1.selectbox("OBS", ["(não alterar)"] + opcoes_obs[1:], key="lote_obs")
        lote_status = b2.selectbox("Status", ["(não alterar)", "(limpar)"] + list(STATUS), key="lote_status")
        b3.markdown("<div style='height:1.9rem'></div>", unsafe_allow_html=True)
        if b3.button("Aplicar", use_container_width=True, disabled=visivel.empty):
            if lote_obs != "(não alterar)":
                tabela.loc[visivel.index, "OBS"] = lote_obs
            if lote_status == "(limpar)":
                tabela.loc[visivel.index, "Status"] = ""
            elif lote_status != "(não alterar)":
                tabela.loc[visivel.index, "Status"] = lote_status
            gravar(arquivo.name, tabela)
            st.rerun()


    def corLinha(linha):
        cor = STATUS.get(linha["Status"])
        return [f"background-color: #{cor}; color: #1f1f1f" if cor else ""] * len(linha)


    editado = st.data_editor(
        visivel.style.apply(corLinha, axis=1),
        key="editor",
        hide_index=True,
        use_container_width=True,
        height=min(60 + 48 * len(visivel), 900),
        row_height=44,
        disabled=COLUNAS + ["Fora de ±1"],
        column_order=COLUNAS + ["Fora de ±1", "OBS", "Status", "Comentário"],
        column_config={
            "id_carteira": st.column_config.TextColumn("id_carteira", width=110),
            "nm_carteira": st.column_config.TextColumn("nm_carteira", width=460),
            "vl_saldo_caixa_tag": st.column_config.NumberColumn("vl_saldo_caixa_tag", format="%.2f", width=170),
            "vl_saldo_caixa_adm": st.column_config.NumberColumn("vl_saldo_caixa_adm", format="%.2f", width=170),
            "vl_saldo_caixa_dif": st.column_config.NumberColumn("vl_saldo_caixa_dif", format="%.2f", width=170),
            "Fora de ±1": st.column_config.CheckboxColumn("Fora de ±1", width=110, help="Diferença menor que -1 ou maior que 1"),
            "OBS": st.column_config.SelectboxColumn("OBS", options=opcoes_obs, width=340),
            "Status": st.column_config.SelectboxColumn("Status", options=[""] + list(STATUS), width=190),
            "Comentário": st.column_config.TextColumn("Comentário", width=380),
        },
    )

    # Grava as alterações (só as linhas visíveis mudam) e salva no disco.
    mudou = False
    for idx, linha in editado.iterrows():
        for col in ("OBS", "Status", "Comentário"):
            novo = linha[col] if isinstance(linha[col], str) else ""
            if tabela.at[idx, col] != novo:
                tabela.at[idx, col] = novo
                mudou = True
    if mudou:
        gravar(arquivo.name, tabela)
        st.rerun()

    st.download_button(
        "Baixar planilha com OBS e Status",
        data=baixarPlanilha(dados, tabela),
        file_name=f"{Path(arquivo.name).stem} - conciliada.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
