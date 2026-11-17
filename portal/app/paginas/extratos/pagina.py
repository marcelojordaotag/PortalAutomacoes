import html
import os
import re
import tempfile
import unicodedata
from collections import Counter, OrderedDict
from datetime import date, datetime, timedelta
from functools import lru_cache

import pandas as pd
import streamlit as st

try:
    from pypdf import PdfReader  # opcional: pip install pypdf
except ImportError:
    PdfReader = None

from app.ambiente.config_ambiente import obterDiretorioDados, obterVariavel  # noqa: E402
from app.paginas.extratos import extratos_drive, modo_teste  # noqa: E402
from app.utilitarias import email_gmail  # noqa: E402
from app.paginas.extratos.exclusao import abaApagar  # noqa: E402
from app.paginas.extratos.importacao import abaImportar  # noqa: E402
from app.database.extratos import (  # noqa: E402
    carregarAnexosSalvos,
    carregarRodadaAberta,
    listarFundosCotistas,
    obterVersaoCadastro,
    salvarAnexosSalvos,
    salvarRodadaBanco,
)

# Pasta de dados do app: não depende de onde o comando foi executado
BASE = str(obterDiretorioDados("extratos"))
EMAIL_RE = re.compile(r"^[^@\s;,]+@[^@\s;,]+\.[^@\s;,]+$")
MODO_TESTE = "teste" in st.query_params  # /extratos?teste: tela de teste com dados fictícios (nada real é consultado, enviado ou gravado)

# ==========================================
# ESTILO
# ==========================================
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
:root{--vinho:#6A0F2B;--vinho-escuro:#4A0A1E;--vinho-medio:#8A1B3D;--vinho-claro:#F4E8EC;
--fundo:#F7F4F5;--card:#FFFFFF;--texto:#26151B;--suave:#7A6770;--borda:#E6DCE0;--dourado:#B8924A;
--ok:#2E8B57;--ok-bg:#DDF1E5;--ok-tx:#1D6B40;--div:#C0392B;--div-bg:#F4D3D8;--div-tx:#8E1B2E;
--alerta:#C98A1B;--alerta-bg:#FBEBC8;--alerta-tx:#8A5A00;--sombra:0 2px 8px rgba(74,10,30,.07);}
html,body,.stApp{font-family:"Inter",system-ui,sans-serif;color-scheme:light;}
.stApp{background:var(--fundo);color:var(--texto);}
#MainMenu,footer,[data-testid="stToolbar"],[data-testid="stDecoration"]{display:none !important;}


.kpi{background:var(--card);border:1px solid var(--borda);border-top:4px solid var(--vinho);border-radius:12px;
box-shadow:var(--sombra);padding:.9rem 1.1rem;}
.kpi-val{font-size:2.1rem;font-weight:700;line-height:1.1;color:var(--texto);}
.kpi-lbl{color:var(--suave);font-size:.78rem;font-weight:600;letter-spacing:.06em;text-transform:uppercase;margin-top:.3rem;}
.kpi.ok{border-top-color:var(--ok);}
.kpi.warn{border-top-color:var(--alerta);}
.kpi.warn .kpi-val{color:var(--div-tx);}

.st-key-card_envio,.st-key-card_lista,.st-key-card_conf{background:var(--card) !important;border:1px solid var(--borda) !important;
border-radius:12px;box-shadow:var(--sombra);}
[data-testid="stVerticalBlockBorderWrapper"]:has(> .st-key-card_envio),[data-testid="stVerticalBlockBorderWrapper"]:has(> div > .st-key-card_envio),[data-testid="stVerticalBlockBorderWrapper"]:has(> .st-key-card_lista),[data-testid="stVerticalBlockBorderWrapper"]:has(> div > .st-key-card_lista),[data-testid="stVerticalBlockBorderWrapper"]:has(> .st-key-card_conf),[data-testid="stVerticalBlockBorderWrapper"]:has(> div > .st-key-card_conf){background:var(--card) !important;border:1px solid var(--borda) !important;border-radius:12px;box-shadow:var(--sombra);}
[data-testid="stVerticalBlockBorderWrapper"]>.st-key-card_envio,[data-testid="stVerticalBlockBorderWrapper"]>div>.st-key-card_envio,[data-testid="stVerticalBlockBorderWrapper"]>.st-key-card_lista,[data-testid="stVerticalBlockBorderWrapper"]>div>.st-key-card_lista,[data-testid="stVerticalBlockBorderWrapper"]>.st-key-card_conf,[data-testid="stVerticalBlockBorderWrapper"]>div>.st-key-card_conf{border:0 !important;box-shadow:none !important;background:transparent !important;}

[data-testid="stWidgetLabel"] *,[data-testid="stCheckbox"] p{color:var(--texto) !important;}
[data-testid="stTooltipIcon"] svg{color:var(--suave) !important;}
[data-testid="stAlert"]{border-radius:10px;}
[data-baseweb="input"],[data-baseweb="base-input"],[data-baseweb="input"]>div{background:#fff !important;border-radius:10px;}
[data-baseweb="input"]{border:1px solid var(--borda) !important;}
[data-baseweb="input"]:focus-within{border-color:var(--vinho) !important;box-shadow:0 0 0 2px rgba(106,15,43,.18);}
[data-baseweb="input"] input{background:#fff !important;color:var(--texto) !important;-webkit-text-fill-color:var(--texto);}
[data-baseweb="input"] input::placeholder{color:var(--suave) !important;-webkit-text-fill-color:var(--suave);opacity:1;}
label[data-baseweb="checkbox"]:not(:has(input:checked))>span:first-child{background:#fff !important;border:2px solid #C9A3B1 !important;}
label[data-baseweb="checkbox"]:has(input:checked)>span:first-child{background:var(--vinho) !important;border-color:var(--vinho) !important;}
.card-title{font-weight:700;font-size:1.08rem;color:var(--vinho);}
.card-hint{color:var(--suave);font-size:.88rem;margin:.1rem 0 .6rem;}

[data-testid="stHorizontalBlock"]{align-items:center;}
.colhead{color:var(--suave);font-size:.78rem;font-weight:600;letter-spacing:.05em;text-transform:uppercase;}
.sep{border-top:1px solid #F0E8EB;margin:.3rem 0;}
.fundo{font-weight:600;}
.ativo{color:var(--suave);font-size:.92rem;}
.badge{display:inline-block;padding:.2rem .7rem;border-radius:999px;font-size:.8rem;font-weight:600;}
.badge.ok{background:var(--ok-bg);color:var(--ok-tx);}
.badge.sem{background:var(--div-bg);color:var(--div-tx);}
.badge.pend{background:var(--alerta-bg);color:var(--alerta-tx);}

.stButton>button{border-radius:10px;font-weight:600;border:1px solid var(--borda);color:var(--vinho);background:#fff;}
.stButton>button:hover{border-color:var(--vinho);color:var(--vinho);background:var(--vinho-claro);}
.stButton>button[kind="primary"],.stButton>button[data-testid="stBaseButton-primary"]{
background:var(--vinho);border-color:var(--vinho);color:#fff;}
.stButton>button[kind="primary"]:hover,.stButton>button[data-testid="stBaseButton-primary"]:hover{
background:var(--vinho-medio);border-color:var(--vinho-medio);color:#fff;box-shadow:0 4px 12px rgba(74,10,30,.25);}
.stButton>button:focus-visible{outline:3px solid rgba(184,146,74,.7);outline-offset:2px;}
.stButton>button:disabled{background:#E3D8DC !important;color:var(--suave) !important;border-color:#E3D8DC !important;opacity:1 !important;cursor:not-allowed;}

.tbl-wrap{max-height:540px;overflow:auto;margin-top:.6rem;border:1px solid var(--borda);border-radius:12px;}
.tbl{width:100%;border-collapse:collapse;font-size:.93rem;}
.tbl th{position:sticky;top:0;background:var(--vinho);color:#fff;text-align:left;font-size:.78rem;font-weight:600;
letter-spacing:.05em;text-transform:uppercase;padding:.6rem .7rem;border-bottom:2px solid var(--dourado);}
.tbl td{padding:.65rem .7rem;border-bottom:1px solid #F0E8EB;vertical-align:middle;}
.tbl tbody tr:nth-child(even){background:#FBF8F9;}
.tbl tbody tr:hover{background:var(--vinho-claro);}
.tbl tr:last-child td{border-bottom:none;}
.tbl tr.novo td{border-top:2px solid #E6DCE0;}
.tbl tr.cont td{border-bottom-color:#F7F1F3;}

[data-testid="stHorizontalBlock"]:has(.st-key-card_envio){align-items:flex-start;}
.st-key-card_envio .stButton>button[kind="primary"],.st-key-card_envio .stButton>button[data-testid="stBaseButton-primary"]{
padding:.7rem 1rem;font-size:1.02rem;}
.vazio{background:var(--card);border:1px dashed #D8C3CB;border-radius:12px;padding:1.4rem;text-align:center;color:var(--suave);}
.vazio b{color:var(--vinho);display:block;margin-bottom:.2rem;font-size:1.02rem;}

[data-testid="stHorizontalBlock"]:has(.row-warn){background:#FDF3F4;box-shadow:inset 4px 0 0 var(--div);border-radius:8px;padding:.15rem .4rem .15rem .7rem;}

[data-testid="stAlert"]{background:#FFF8EA !important;border:1px solid #F0DDB0;border-left:4px solid var(--dourado);color:var(--texto);}
[data-testid="stAlert"] *{color:var(--texto) !important;}

[data-testid="stRadio"] [role="radiogroup"]{gap:.4rem;flex-wrap:wrap;}
[data-testid="stRadio"] label{background:#fff;border:1px solid var(--borda);border-radius:999px;padding:.15rem .9rem;margin:0;cursor:pointer;}
[data-testid="stRadio"] label:hover{border-color:var(--vinho);background:var(--vinho-claro);}
[data-testid="stRadio"] label:has(input:checked){background:var(--vinho);border-color:var(--vinho);}
[data-testid="stRadio"] label:has(input:checked) *{color:#fff !important;}
[data-testid="stRadioOption"]>div>div:first-child:not([data-testid="stMarkdownContainer"]){display:none !important;}
.badge{white-space:nowrap;}
.tbl td.fundo{font-weight:600;}
@media (max-width:640px){.topo .marca{font-size:1.4rem;}.block-container{padding:1rem .8rem 2rem;}}
</style>
"""


# ==========================================
# COLUNAS DA PLANILHA (nomes tolerantes a maiúsculas, acentos e espaços)
# ==========================================
ALIASES = {
    "fundo": {"nome do fundo", "fundo"},
    "cotista": {"cotistas", "cotista", "nome do cotista"},
    "doc": {"cpf/cnpj cotistas", "cpf/cnpj cotista", "cpf/cnpj", "cpf cnpj cotistas"},
    "email": {"emails", "email", "e-mail", "e-mails"},
    "cnpj_fundo": {"cnpj do fundo", "cnpj fundo"},
}
OBRIGATORIAS = {"fundo": "Nome do Fundo", "cotista": "COTISTAS", "email": "emails"}

# ==========================================
# CONFIGURAÇÕES DE ENVIO OCULTAS
# ==========================================
# Coloque os e-mails em cópia aqui. Deixe vazio ("") se não quiser ninguém em cópia.
EMAILS_EM_COPIA = "processamento@taginvest.com.br; bo@taginvest.com.br"

# ==========================================
# FUNÇÕES AUXILIARES
# ==========================================
def norm(texto_bruto):
    texto_bruto = unicodedata.normalize("NFKD", str(texto_bruto))
    texto_bruto = "".join(caractere for caractere in texto_bruto if not unicodedata.combining(caractere))
    return re.sub(r"\s+", " ", texto_bruto).strip().casefold()


def saudacao():
    hora = datetime.now().hour
    return "bom dia" if hora < 12 else "boa tarde" if hora < 18 else "boa noite"


def _pascoa(ano):
    """Domingo de Páscoa (algoritmo gregoriano anônimo)."""
    resto_19, seculo, resto_100 = ano % 19, ano // 100, ano % 100
    quarto_seculo, resto_seculo = seculo // 4, seculo % 4
    correcao_lua = (seculo + 8) // 25
    correcao_ajuste = (seculo - correcao_lua + 1) // 3
    epacta = (19 * resto_19 + seculo - quarto_seculo - correcao_ajuste + 15) % 30
    ordem_item, chave_item = resto_100 // 4, resto_100 % 4
    ajuste_lua = (32 + 2 * resto_seculo + 2 * ordem_item - epacta - chave_item) % 7
    correcao_final = (resto_19 + 11 * epacta + 22 * ajuste_lua) // 451
    mes, dia = divmod(epacta + ajuste_lua - 7 * correcao_final + 114, 31)
    return date(ano, mes, dia + 1)


def feriadosNacionais(ano):
    """Feriados nacionais (fixos e móveis) do ano: {data: nome}. Estaduais e municipais não entram."""
    domingo_pascoa = _pascoa(ano)
    lista = {
        date(ano, 1, 1): "Confraternização Universal",
        domingo_pascoa - timedelta(days=48): "Carnaval",
        domingo_pascoa - timedelta(days=47): "Carnaval",
        domingo_pascoa - timedelta(days=2): "Sexta-feira Santa",
        date(ano, 4, 21): "Tiradentes",
        date(ano, 5, 1): "Dia do Trabalho",
        domingo_pascoa + timedelta(days=60): "Corpus Christi",
        date(ano, 9, 7): "Independência do Brasil",
        date(ano, 10, 12): "Nossa Senhora Aparecida",
        date(ano, 11, 2): "Finados",
        date(ano, 11, 15): "Proclamação da República",
        date(ano, 12, 25): "Natal",
    }
    if ano >= 2024:
        lista[date(ano, 11, 20)] = "Consciência Negra"
    return lista


def motivoNaoUtil(dt_ref):
    """Por que a data não é dia útil ('sábado', 'domingo' ou nome do feriado); None se for dia útil."""
    if dt_ref.weekday() == 5:
        return "um sábado"
    if dt_ref.weekday() == 6:
        return "um domingo"
    feriado = feriadosNacionais(dt_ref.year).get(dt_ref)
    return f"feriado ({feriado})" if feriado else None


def diaUtilAnterior(dt_ref):
    dt_ref -= timedelta(days=1)
    while motivoNaoUtil(dt_ref):
        dt_ref -= timedelta(days=1)
    return dt_ref


def texto(valor):
    return "" if pd.isna(valor) else str(valor).strip()


def listaEmails(valor):
    """Separa por vírgula, ';' ou quebra de linha e remove repetidos (sem diferenciar maiúsculas)."""
    if pd.isna(valor):
        return []
    vistos, saida = set(), []
    for endereco in re.split(r"[;,\r\n]+", str(valor)):
        endereco = endereco.strip()
        if endereco and endereco.lower() not in vistos:
            vistos.add(endereco.lower())
            saida.append(endereco)
    return saida


def _mapearColunas(df):
    """Renomeia as colunas do cadastro para os nomes usados pelo app. Devolve (tabela, nomes originais das colunas)."""
    originais = [str(coluna_original) for coluna_original in df.columns]
    mapa = {}
    for col in df.columns:
        nm_coluna_norm = norm(col)
        for campo, nomes in ALIASES.items():
            if nm_coluna_norm in nomes and campo not in mapa.values():
                mapa[col] = campo
    return df.rename(columns=mapa), originais


@st.cache_data(ttl=60)
def carregarPlanilha(versao):
    # versao (linhas, maior id) invalida o cache quando o cadastro muda; ttl pega edições feitas direto no banco
    df, originais = _mapearColunas(listarFundosCotistas())
    return df, originais, datetime.now()


def montarItens(df):
    """Um item por destinatário: linhas com o mesmo e-mail (ou o mesmo conjunto de e-mails)
    viram um único e-mail com todos os fundos e cotistas."""
    itens = OrderedDict()
    for nr_linha, (_, linha) in enumerate(df.iterrows()):
        fundo, cotista = texto(linha["fundo"]), texto(linha["cotista"])
        doc = texto(linha["doc"]) if "doc" in df.columns else ""
        cnpj = texto(linha["cnpj_fundo"]) if "cnpj_fundo" in df.columns else ""
        if not (fundo or cotista):
            continue
        emails = listaEmails(linha["email"])
        chave = tuple(sorted(email.lower() for email in emails)) if emails else ("__sem_email__", nr_linha)
        item = itens.setdefault(
            chave,
            {"emails": "; ".join(emails), "fundos": OrderedDict(), "cnpjs": {}, "linhas": 0,
             "invalidos": [email for email in emails if not EMAIL_RE.match(email)]},
        )
        item["linhas"] += 1
        if cnpj:
            item["cnpjs"].setdefault(fundo, cnpj)
        cots = item["fundos"].setdefault(fundo, [])
        if cotista and (cotista, doc) not in cots:
            cots.append((cotista, doc))
    return list(itens.values())


def nomeItem(item):
    fundos = [nm_fundo_item for nm_fundo_item in item["fundos"] if nm_fundo_item]
    if not fundos:
        return ""
    return fundos[0] if len(fundos) == 1 else f"{fundos[0]} e mais {len(fundos) - 1}"


def montarAssunto(item, data_fmt):
    nome = nomeItem(item)
    return f"Extrato Mensal Ref. {data_fmt}" + (f" - {nome}" if nome else "")


def montarCorpoHtml(item, data_fmt):
    """Um bloco por fundo: frase de pedido + tabela (Nome Cliente / CPF/CNPJ)."""
    fonte = "font-family:Arial,Helvetica,sans-serif;font-size:10pt;"
    borda = "border:1px solid #000000;padding:2px 5px;"
    blocos = []
    for fundo, cots in item["fundos"].items():
        cnpj = item["cnpjs"].get(fundo, "")
        ativo = f"<b>{html.escape(fundo)}</b>" if fundo else ""
        if cnpj:
            ativo += f" <b>({html.escape(cnpj)})</b>"
        pedido = "os extratos dos cotistas abaixo" if len(cots) > 1 else "o extrato do cotista abaixo"
        frase = f"Por favor, poderiam nos enviar {pedido}, ref. <b>{data_fmt}</b>"
        if ativo:
            frase += f", no ativo {ativo}"
        frase += "?"

        linhas = "".join(
            f'<tr><td style="{borda}">{html.escape(cotista) or "-"}</td>'
            f'<td style="{borda}">{html.escape(documento) or "-"}</td></tr>'
            for cotista, documento in (cots or [("", "")])
        )
        tabela = (
            '<table border="1" cellspacing="0" cellpadding="2" width="720" '
            f'style="border-collapse:collapse;border:1px solid #000000;{fonte}">'
            f'<tr><th align="left" width="75%" style="{borda}">Nome Cliente</th>'
            f'<th align="left" width="25%" style="{borda}">CPF/CNPJ</th></tr>'
            f"{linhas}</table>"
        )
        blocos.append(f"<p>{frase}</p>{tabela}<br>Fico no aguardo!<br>")

    return (
        f'<div style="{fonte}">'
        f"<p>Prezados, {saudacao()}! Tudo bem?</p>"
        + "<br>".join(blocos)
        + "<br></div>"
    )


def inserirNoCorpo(html_existente, corpo):
    """Coloca o texto logo após <body>, preservando a assinatura."""
    correspondencia = re.search(r"<body[^>]*>", html_existente, flags=re.IGNORECASE)
    if correspondencia:
        return html_existente[: correspondencia.end()] + corpo + html_existente[correspondencia.end():]
    return corpo + html_existente


def _registrarFalhaEnvio(ds_texto, ic_dialogo):
    """Dentro do modal a tela é refeita ao fechar; por isso a falha vai para a sessão e aparece depois (mostrarResultadoEnvio)."""
    if ic_dialogo:
        st.session_state.setdefault("falhas_envio", []).append(ds_texto)
    else:
        st.error(ds_texto)


def emailDeTeste():
    """Endereço que recebe todos os e-mails no modo de teste. Na tela de teste (/extratos?teste) é sempre o fixo do modo_teste;
    fora dela, só se a variável de ambiente EXTRATOS_EMAIL_TESTE estiver definida (aí todo e-mail sai só para esse endereço)."""
    return modo_teste.EMAIL_DE_TESTE if MODO_TESTE else obterVariavel("EXTRATOS_EMAIL_TESTE").strip()


def _destinoDoEnvio(elemento, data_fmt):
    """(destinatários, assunto em minúsculas) com que o e-mail do item sai: o real ou, no modo de teste, o endereço de teste
    com [TESTE] no assunto. Serve para achar o e-mail enviado em Enviados e a conversa dele."""
    ds_teste = emailDeTeste()
    ds_assunto = montarAssunto(elemento, data_fmt).lower()
    if ds_teste:
        return {ds_teste.lower()}, f"[teste] {ds_assunto}"
    return {email.lower() for email in listaEmails(elemento["emails"])}, ds_assunto


def enviarEmailsGmail(itens, data_ref, ic_dialogo=False):
    """Envia um e-mail por item, pela conta Gmail conectada, com assinatura e cópia (CC). Devolve quantos foram enviados.
    No modo de teste (emailDeTeste) o destinatário é o e-mail de teste, sem CC, e o assunto leva [TESTE]."""
    data_fmt = data_ref.strftime("%d/%m")
    ds_teste = emailDeTeste()
    qt_enviados = 0
    try:
        servico = email_gmail.servicoDaSessao()
    except email_gmail.GmailNaoConectadoErro:
        _registrarFalhaEnvio("A conexão com a conta Google expirou ou não existe. Conecte-se de novo "
                             "(use \"Conectar ao Google\" na lateral).", ic_dialogo)
        return 0
    ds_assinatura = email_gmail.assinaturaHtml(servico)
    for item in itens:
        try:
            ds_html = f"<div>{montarCorpoHtml(item, data_fmt)}</div><br>{ds_assinatura}"
            mensagem_email = email_gmail.montarMime(
                ds_teste or item["emails"], ("[TESTE] " if ds_teste else "") + montarAssunto(item, data_fmt), ds_html,
                "" if ds_teste else (EMAILS_EM_COPIA or ""))
            email_gmail.enviarEmail(servico, mensagem_email)
            qt_enviados += 1
        except Exception as erro:
            _registrarFalhaEnvio(f"Não foi possível enviar o e-mail para {item['emails']}: {erro}", ic_dialogo)
    return qt_enviados


def mostrarResultadoEnvio():
    """Resultado do último envio feito pelo modal: aviso de sucesso e falhas, se houve."""
    ds_aviso = st.session_state.pop("aviso_envio", None)
    if ds_aviso:
        st.success(ds_aviso)
    for ds_falha in st.session_state.pop("falhas_envio", []):
        st.error(ds_falha)


HORAS_TRAVA_ENVIO = 24  # e-mail enviado há menos que isso pede uma confirmação a mais para ser enviado de novo


def enviosRecentes(itens, data_ref, ic_nova_rodada):
    """Trava contra envio em duplicidade. Devolve ({índice do item: quando foi enviado}, ic_erro) com os e-mails que já saíram
    nas últimas HORAS_TRAVA_ENVIO horas: pelo Gmail desta conta (mesmo destinatário e mesmo assunto) ou, ao abrir uma rodada nova,
    por uma rodada aberta há menos tempo que isso para a mesma data de referência (inclusive a de outra pessoa)."""
    data_fmt = data_ref.strftime("%d/%m")
    dt_limite = datetime.now() - timedelta(hours=HORAS_TRAVA_ENVIO)
    dict_recentes, ic_erro = {}, False
    try:
        servico = email_gmail.servicoDaSessao()
        lista_enviados = email_gmail.buscarMensagens(servico, f"in:sent subject:extrato after:{email_gmail.segundosEpoch(dt_limite)}")
        for ordem_item, item in enumerate(itens):
            esperados = {email.lower() for email in listaEmails(item["emails"])}
            ds_assunto = montarAssunto(item, data_fmt).lower()
            lista_quando = [mensagem.quando for mensagem in lista_enviados if esperados <= mensagem.para and mensagem.assunto.lower() == ds_assunto]
            if lista_quando:
                dict_recentes[ordem_item] = max(lista_quando)
    except Exception:  # noqa: BLE001  (sem a conferência, a trava avisa que não conseguiu verificar)
        ic_erro = True
    if ic_nova_rodada:
        lista_rodadas = [st.session_state.get("rodada")]
        try:
            lista_rodadas.append(carregarRodadaAberta()[0])
        except Exception:  # noqa: BLE001
            ic_erro = True
        for rodada_aberta in lista_rodadas:
            if rodada_aberta and rodada_aberta["data"] == data_ref and rodada_aberta["inicio"] >= dt_limite:
                lista_emails_rodada = {item_rodada["emails"] for item_rodada in rodada_aberta["itens"]}
                for ordem_item, item in enumerate(itens):
                    if item["emails"] in lista_emails_rodada:
                        dict_recentes.setdefault(ordem_item, rodada_aberta["inicio"])
    return dict_recentes, ic_erro


@st.dialog("Revisar e enviar os e-mails", width="large")
def dialogoRevisarEnvio(itens, data_ref, rodada_atual=None, qt_sem_email=0):
    """Mostra todos os e-mails que vão sair, com a prévia de cada um. Só depois da conferência a pessoa confirma e todos
    são enviados de uma vez. Sem `rodada_atual`, o envio abre uma rodada nova de conferência."""
    data_fmt = data_ref.strftime("%d/%m")
    ds_conta = email_gmail.emailDaSessao()
    if not ds_conta:
        st.error("A conexão com a conta Google expirou ou não existe. Feche esta janela e use \"Conectar ao Google\" na lateral.")
        return
    ds_teste = emailDeTeste()
    if ds_teste:
        if MODO_TESTE:
            st.warning(f"TELA DE TESTE: os e-mails saem de verdade, mas só para **{ds_teste}**, sem cópia (CC) e com [TESTE] no assunto. "
                       "Nenhum cotista recebe nada.")
        else:
            itens = itens[:3]  # no teste por variável de ambiente saem só os 3 primeiros
            st.warning(f"MODO TESTE: os e-mails saem só para **{ds_teste}**, sem CC, com [TESTE] no assunto. "
                       "Nenhum cotista recebe nada e a rodada de conferência não é aberta.")
        st.markdown(f"**{len(itens)} e-mail(s)** serão enviados agora pela conta **{ds_conta}**.")
    else:
        st.markdown(
            f"**{len(itens)} e-mail(s)** serão enviados agora pela conta **{ds_conta}**, com cópia (CC) para {EMAILS_EM_COPIA}. "
            "Confira a lista e a prévia antes de confirmar."
        )
    if qt_sem_email:
        st.caption(f"{qt_sem_email} cotista(s) sem e-mail cadastrado ficam de fora.")
    lista_opcoes = [f"{ordem + 1}. {item['emails']}" for ordem, item in enumerate(itens)]
    ds_chave_lista = f"{len(itens)}|{hash(tuple(item['emails'] for item in itens))}"
    if st.session_state.get("dlg_lista") != ds_chave_lista:  # outra lista de e-mails (ex.: só os pendentes): volta ao primeiro
        st.session_state["dlg_lista"] = ds_chave_lista
        st.session_state["dlg_previa"] = lista_opcoes[0]
    if st.session_state.get("dlg_previa") not in lista_opcoes:
        st.session_state["dlg_previa"] = lista_opcoes[0]
    nr_atual = lista_opcoes.index(st.session_state["dlg_previa"])

    # trava contra envio em duplicidade: confere uma vez por lista (e a cada 2 min), não a cada clique nos botões
    dict_guardado = st.session_state.get("dlg_recentes")
    if ds_teste or MODO_TESTE:
        dict_recentes, ic_erro_verificacao = {}, False  # modo de teste não tem trava: nada vai para os cotistas
    elif dict_guardado and dict_guardado["chave"] == ds_chave_lista and (datetime.now() - dict_guardado["quando"]).total_seconds() < 120:
        dict_recentes, ic_erro_verificacao = dict_guardado["recentes"], dict_guardado["erro"]
    else:
        dict_recentes, ic_erro_verificacao = enviosRecentes(itens, data_ref, rodada_atual is None)
        st.session_state["dlg_recentes"] = {"chave": ds_chave_lista, "quando": datetime.now(), "recentes": dict_recentes, "erro": ic_erro_verificacao}

    def irPara(nr_destino):
        st.session_state["dlg_previa"] = lista_opcoes[nr_destino]

    coluna_anterior, coluna_escolha, coluna_proximo = st.columns([1, 4, 1])
    coluna_anterior.button("← Anterior", key="dlg_anterior", disabled=nr_atual == 0, on_click=irPara, args=(nr_atual - 1,), use_container_width=True)
    coluna_proximo.button("Próximo →", key="dlg_proximo", disabled=nr_atual == len(itens) - 1, on_click=irPara, args=(nr_atual + 1,), use_container_width=True)
    coluna_escolha.selectbox("E-mail", lista_opcoes, key="dlg_previa", label_visibility="collapsed")
    st.caption(f"E-mail {nr_atual + 1} de {len(itens)}")
    item_previa = itens[nr_atual]
    with st.container(border=True):
        if nr_atual in dict_recentes:
            st.markdown(f":red[**Já enviado em {dict_recentes[nr_atual]:%d/%m às %H:%M}.**]")
        st.markdown(
            f"**Para:** {html.escape(ds_teste or item_previa['emails'])}  \n**CC:** {'-' if ds_teste else html.escape(EMAILS_EM_COPIA or '-')}  \n"
            f"**Assunto:** {html.escape(montarAssunto(item_previa, data_fmt))}"
        )
        st.divider()
        st.markdown(montarCorpoHtml(item_previa, data_fmt), unsafe_allow_html=True)
    st.caption("A assinatura do seu Gmail é incluída no envio.")

    ic_confirmou_repetir = True
    if ic_erro_verificacao and not dict_recentes:
        st.caption("Não consegui conferir se estes e-mails já foram enviados antes.")
    if dict_recentes:
        dt_ultimo = max(dict_recentes.values())
        st.error(f"**Atenção:** {len(dict_recentes)} de {len(itens)} e-mail(s) já foram enviados nas últimas {HORAS_TRAVA_ENVIO} horas "
                 f"(o último em {dt_ultimo:%d/%m às %H:%M}). Quer enviar mesmo assim?")
        with st.expander("Ver quais já foram enviados"):
            for ordem_item, dt_envio in sorted(dict_recentes.items()):
                st.write(f"{ordem_item + 1}. {itens[ordem_item]['emails']}: enviado em {dt_envio:%d/%m às %H:%M}")
        ic_confirmou_repetir = st.checkbox("Sim, já foram enviados e quero enviar mesmo assim", key=f"dlg_repetir_{ds_chave_lista}")

    ic_conferido = st.checkbox("Conferi os e-mails e quero enviá-los", key=f"dlg_ok_{len(itens)}_{abs(hash(tuple(i['emails'] for i in itens)))}")
    coluna_enviar, coluna_cancelar = st.columns(2)
    ds_botao = f"Enviar mesmo assim ({len(itens)})" if dict_recentes else f"Enviar {len(itens)} e-mail(s)"
    if coluna_enviar.button(ds_botao, type="primary", disabled=not (ic_conferido and ic_confirmou_repetir), use_container_width=True, key="dlg_enviar"):
        dt_inicio = datetime.now()
        with st.spinner("Enviando..."):
            qt_enviados = enviarEmailsGmail(itens, data_ref, ic_dialogo=True)
        if qt_enviados:
            if rodada_atual is None and (not ds_teste or MODO_TESTE):  # a rodada da tela de teste fica só na sessão
                st.session_state["rodada"] = {"inicio": dt_inicio, "data": data_ref, "itens": itens}
                salvarRodada(st.session_state["rodada"])
                st.session_state.pop("conferencia", None)
            st.session_state["aviso_envio"] = f"{qt_enviados} de {len(itens)} e-mail(s) enviado(s)."
        st.session_state.pop("dlg_recentes", None)  # a próxima abertura do modal confere de novo (já vai achar estes envios)
        st.rerun()
    if coluna_cancelar.button("Cancelar", use_container_width=True, key="dlg_cancelar"):
        st.rerun()


NDR_MARCAS = (
    "undeliverable", "delivery status notification", "mail delivery", "returned mail",
    "não foi possível entregar", "nao foi possivel entregar", "falha na entrega", "não entregue",
)


def conferirEnvios(itens, desde, data_ref):
    """Confere no Gmail o que aconteceu com cada e-mail criado. Retorna {indice: status}."""
    data_fmt = data_ref.strftime("%d/%m")
    desde = desde - timedelta(minutes=1)
    status = {ordem_item: "Aguardando envio" for ordem_item in range(len(itens))}
    try:
        servico = email_gmail.servicoDaSessao()
    except email_gmail.GmailNaoConectadoErro:
        st.error("A conexão com a conta Google expirou ou não existe. Conecte-se de novo (use \"Conectar ao Google\" na lateral).")
        return None
    try:
        vl_apos = email_gmail.segundosEpoch(desde)
        enviados = [(mensagem.para, mensagem.assunto.lower(), mensagem.quando)
                    for mensagem in email_gmail.buscarMensagens(servico, f"in:sent subject:extrato after:{vl_apos}")]
        saida = [(mensagem.para, mensagem.assunto.lower()) for mensagem in email_gmail.listarRascunhos(servico)]
        devolvidos = [
            (mensagem.quando, mensagem.corpo.lower())
            for mensagem in email_gmail.buscarMensagens(servico, f"(from:mailer-daemon OR from:postmaster) after:{vl_apos}")
            if any(chave_item in mensagem.assunto.lower() for chave_item in NDR_MARCAS)
        ]

        for ordem_item, elemento in enumerate(itens):
            esperados, ds_assunto_item = _destinoDoEnvio(elemento, data_fmt)
            # fora do teste basta "extrato" no assunto; no teste (todos vão ao mesmo endereço) vale o assunto completo
            casados = [dt_envio for dest, assunto, dt_envio in enviados
                       if esperados <= dest and (assunto == ds_assunto_item if emailDeTeste() else "extrato" in assunto)]
            if casados:
                status[ordem_item] = "Enviado"
                # só vale devolução recebida depois do envio mais antigo deste e-mail
                primeiro = min(casados)
                if any(rec >= primeiro and email_esperado in corpo for rec, corpo in devolvidos for email_esperado in esperados):
                    status[ordem_item] = "Erro de entrega"
            elif any(esperados <= dest and "extrato" in assunto for dest, assunto in saida):
                status[ordem_item] = "Em rascunho"
        return status
    except Exception as erro:
        st.error(f"Não foi possível conferir no Gmail: {erro}")
        return None


PASTA_EXTRATOS = os.path.join(BASE, "Extratos")
PREFIXO_REVISAR = "_Revisar"  # anexos sem fundo identificado; também reclassificados a cada conferência


def _nomeSeguro(txt):
    limpo = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(txt))
    return re.sub(r"\s+", " ", limpo).strip(" .") or "sem_nome"


def _assuntoBase(assunto):
    """Tira prefixos de resposta/encaminhamento (RE:, RES:, ENC:, FW:...)."""
    return re.sub(r"^\s*((re|res|enc|fw|fwd|rv)\s*:\s*)+", "", str(assunto), flags=re.I).strip().lower()


def _anexoValido(anexo):
    """Só arquivos de verdade: ignora imagens embutidas e logos de assinatura."""
    if anexo.embutido:
        return False
    if anexo.nome.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp")) and anexo.tamanho < 50000:
        return False
    return True


# ==========================================
# CLASSIFICAÇÃO DO ANEXO POR FUNDO
# ==========================================
def _soDigitos(texto_bruto):
    return re.sub(r"\D", "", str(texto_bruto))


def _limpo(texto_bruto):
    """norm() tratando _ - . como espaço, para casar nomes de arquivo."""
    return norm(re.sub(r"[_\-.]+", " ", str(texto_bruto)))


def _contem(texto_limpo, termo):
    """O termo aparece como palavra(s) inteira(s) no texto (já passado por _limpo)?"""
    termo = _limpo(termo)
    if not termo:
        return False
    return re.search(rf"(?<!\w){re.escape(termo)}(?!\w)", texto_limpo) is not None


# palavras genéricas de nomes de fundos/cotistas: não servem para identificar ninguém
PALAVRAS_COMUNS = {
    "fic", "fim", "fif", "fidc", "fia", "fip", "fii", "fi", "cic", "resp", "ltda", "limitada", "sub", "sr",
    "cp", "lp", "rl", "de", "da", "do", "das", "dos", "e", "ou", "mult", "multimercado", "cred", "credito",
    "priv", "privado", "acoes", "ie", "ii", "iii", "iv", "fundo", "investimento", "investimentos", "cotas",
    "cotista", "cotistas", "extrato", "posicao", "perfil", "previdencia", "prev", "institucional",
}


def _tokens(nome):
    """Palavras que distinguem o nome (sem termos genéricos como FIC, FIM, RESP LTDA)."""
    return [palavra for palavra in _limpo(nome).split() if palavra not in PALAVRAS_COMUNS and (len(palavra) >= 3 or palavra.isdigit())]


def _forcaNome(texto_limpo, nome):
    """Quanto do nome aparece no texto: 1.0 = nome completo; fração das palavras-chave quando abreviado
    (ex.: 'Previ Novartis' para 'PREVI NOVARTIS FIF CIC MULT RESP LTDA'); 0 = não aparece."""
    if not nome:
        return 0.0
    if _contem(texto_limpo, nome):
        return 1.0
    toks = _tokens(nome)
    if not toks:
        return 0.0
    achou = sum(1 for palavra in toks if _contem(texto_limpo, palavra))
    if len(toks) == 1:
        return 0.5 if achou else 0.0
    return achou / len(toks) if achou >= 2 and achou / len(toks) >= 0.5 else 0.0


def _pontuar(item, fonte):
    """Pontos por fundo: nome/CNPJ do fundo valem 10 (nome abreviado vale proporcional);
    nome/documento do cotista valem 3 (abreviado, proporcional)."""
    if not fonte:
        return {}
    texto_limpo, ds_digitos = _limpo(fonte), _soDigitos(fonte)
    pontos = {}
    for fundo, cots in item["fundos"].items():
        if not fundo:
            continue
        vl_pontos = 0
        if _contem(texto_limpo, fundo):
            vl_pontos += 10
        else:
            # nome do fundo abreviado no arquivo (ex.: 'Root' para 'Root Capital'): conta cada palavra-chave
            vl_pontos += 4 * sum(1 for palavra in _tokens(fundo) if _contem(texto_limpo, palavra))
        cnpj = _soDigitos(item["cnpjs"].get(fundo, ""))
        if len(cnpj) >= 11 and cnpj in ds_digitos:
            vl_pontos += 10
        for cot, doc in cots:
            vl_pontos += 3 * _forcaNome(texto_limpo, cot)
            dd = _soDigitos(doc)
            if len(dd) >= 11 and dd in ds_digitos:
                vl_pontos += 3
        if vl_pontos:
            pontos[fundo] = vl_pontos
    return pontos


def _vencedor(pontos):
    """Fundo com mais pontos, só se não houver empate."""
    ordem = sorted(pontos.items(), key=lambda par_fundo: -par_fundo[1])
    if not ordem:
        return None
    if len(ordem) == 1 or ordem[0][1] > ordem[1][1]:
        return ordem[0][0]
    return None


@lru_cache(maxsize=512)
def _textoPdfCache(caminho, mtime, tamanho, max_paginas=3):
    try:
        return " ".join((pagina.extract_text() or "") for pagina in PdfReader(caminho).pages[:max_paginas])
    except Exception:
        return ""


def _textoPdf(caminho, max_paginas=3):
    """Texto das primeiras páginas do PDF (com cache por arquivo, para não reler a cada conferência).
    `caminho` é um arquivo local (o temporário, antes de ir para o Drive) ou um ArquivoSalvo (já no Drive)."""
    if isinstance(caminho, extratos_drive.ArquivoSalvo):
        return extratos_drive.textoDoPdf(caminho)
    if PdfReader is None or not caminho.lower().endswith(".pdf"):
        return ""
    try:
        st_ = os.stat(caminho)
    except OSError:
        return ""
    return _textoPdfCache(caminho, st_.st_mtime_ns, st_.st_size, max_paginas)


def _cotistasCobertos(item, nome_arquivo, caminho, so_fundo=None):
    """Cotistas (fundo, nome) do item identificados no anexo, pelo nome do arquivo ou conteúdo do PDF.
    Nome completo ou documento: todos contam. Só nome abreviado: conta apenas o que casa melhor
    (se houver empate, conta um só, para não inflar o total)."""
    fonte = f"{nome_arquivo} {_textoPdf(caminho)}"
    texto_limpo, digitos_fonte = _limpo(fonte), _soDigitos(fonte)
    exatos, parciais = set(), []
    for fundo, cots in item["fundos"].items():
        if so_fundo and fundo != so_fundo:
            continue
        for cot, doc in cots:
            dd = _soDigitos(doc)
            forca = _forcaNome(texto_limpo, cot) if cot else 0.0
            if forca >= 1.0 or (len(dd) >= 11 and dd in digitos_fonte):
                exatos.add((fundo, cot))
            elif forca > 0:
                parciais.append((forca, fundo, cot))
    if exatos or not parciais:
        return exatos
    melhor = max(parcial[0] for parcial in parciais)
    return {next((fundo_parcial, cotista_parcial) for forca, fundo_parcial, cotista_parcial in parciais if forca == melhor)}


def _escolherItem(itens, candidatos, nome_arquivo, caminho):
    """Entre vários itens do mesmo remetente, escolhe o que melhor casa com o conteúdo do anexo."""
    if len(candidatos) == 1:
        return candidatos[0]
    fonte = f"{nome_arquivo} {_textoPdf(caminho)}"
    notas = {chave_item: sum(_pontuar(itens[chave_item], fonte).values()) for chave_item in candidatos}
    melhor = max(notas.values())
    if melhor > 0:
        vencedores = [chave_item for chave_item in candidatos if notas[chave_item] == melhor]
        if len(vencedores) == 1:
            return vencedores[0]
    return candidatos[0]


def _fundoIdentificado(item, nome_arquivo, texto_mensagem, caminho):
    """Fundo do anexo somando evidências do nome do arquivo, do conteúdo do PDF, do assunto e do corpo
    (peso maior para as duas primeiras). None se não der para identificar com segurança."""
    fundos = [nm_fundo_item for nm_fundo_item in item["fundos"] if nm_fundo_item]
    if len(fundos) == 1:
        return fundos[0]

    total = {}
    for peso, fonte in ((3, nome_arquivo), (3, _textoPdf(caminho)), (1, texto_mensagem.assunto), (0.5, texto_mensagem.corpo)):
        for fundo, vl_pontos in _pontuar(item, fonte).items():
            total[fundo] = total.get(fundo, 0) + vl_pontos * peso
    return _vencedor(total)


def _pastaSemFundo(texto_mensagem):
    """Pasta de revisão para anexos que não foram associados a nenhum fundo."""
    remetente = re.sub(r"\s+", " ", texto_mensagem.nome_remetente or texto_mensagem.remetente).strip()
    return f"{PREFIXO_REVISAR} - {remetente}" if remetente else f"{PREFIXO_REVISAR} - remetente desconhecido"


def _fundoDoAnexo(item, nome_arquivo, texto_mensagem, caminho):
    """Nome da pasta do anexo: o fundo identificado ou, na falta dele, a pasta de revisão."""
    return _fundoIdentificado(item, nome_arquivo, texto_mensagem, caminho) or _pastaSemFundo(texto_mensagem)


def _pastaDoArquivo(caminho):
    """Nome da pasta em que o arquivo está (a do fundo ou a de revisão)."""
    if isinstance(caminho, extratos_drive.ArquivoSalvo):
        return caminho.pasta
    return os.path.basename(os.path.dirname(caminho))


def _emPastaSemFundo(caminho):
    return _pastaDoArquivo(caminho).startswith((PREFIXO_REVISAR, "Remetente"))  # "Remetente" = nome antigo da pasta


def _idPastaNoDrive(login, nm_mes, nome_pasta):
    """(id da pasta, nome real da pasta) em <raiz>/<ano>/<MM>- <Mês>/ do Drive: a do fundo (a que já existe com nome parecido ou
    uma nova) ou a de revisão. Cria o ano, o mês e a pasta se ainda não existirem."""
    id_mes = extratos_drive.idPastaDoMes(login, int(nm_mes[:4]), int(nm_mes[5:7]), ic_criar=True)
    if nome_pasta.startswith(PREFIXO_REVISAR):
        id_pasta = extratos_drive.idPastaPorNome(login, id_mes, nome_pasta)
    else:
        id_pasta = extratos_drive.idPastaDoFundo(login, id_mes, nome_pasta, ic_criar=True)
    return id_pasta, extratos_drive.nomeDaPasta(login, id_mes, id_pasta, _nomeSeguro(nome_pasta))


def _guardarNoDrive(origem, nm_mes, nome_pasta, nome, evitar_duplicata=False):
    """Envia o arquivo temporário para a pasta do fundo no Drive sem sobrescrever nada e apaga o temporário. Com
    evitar_duplicata, se a pasta já tem um arquivo de mesmo nome e tamanho, não envia e aponta para o existente."""
    login = extratos_drive.loginAtual()
    id_pasta, nm_pasta_real = _idPastaNoDrive(login, nm_mes, nome_pasta)
    ds_texto = _textoPdf(origem)  # lido do temporário: vale para o arquivo no Drive e evita baixá-lo de novo
    with open(origem, "rb") as arquivo_origem:
        conteudo = arquivo_origem.read()
    arquivo = extratos_drive.salvarArquivo(login, id_pasta, nm_pasta_real, nome, conteudo, evitar_duplicata)
    extratos_drive.guardarTexto(arquivo, ds_texto)
    os.remove(origem)
    return arquivo


def _moverNoDrive(arquivo, nm_mes, nome_pasta):
    """Move um arquivo que já está no Drive (ex.: da pasta de revisão) para a pasta do fundo. Se a pasta do fundo já tem um
    arquivo de mesmo nome e tamanho, aponta para ele e deixa a cópia onde está (a conta não apaga arquivos do Drive)."""
    login = extratos_drive.loginAtual()
    id_pasta, nm_pasta_real = _idPastaNoDrive(login, nm_mes, nome_pasta)
    nr_tamanho = extratos_drive.tamanhoDoArquivo(login, arquivo)
    for dict_existente in extratos_drive.listarArquivos(login, id_pasta):
        if dict_existente["nome"].lower() == arquivo.nome.lower() and dict_existente["tamanho"] == nr_tamanho:
            return extratos_drive.ArquivoSalvo(dict_existente["id"], dict_existente["nome"], nm_pasta_real, dict_existente["modificado"])
    return extratos_drive.moverArquivo(login, arquivo, id_pasta, nm_pasta_real)


def _respostasAosEnviados(servico, itens, desde, data_fmt):
    """Só as respostas aos e-mails que nós enviamos: acha em Enviados o e-mail de cada item (mesmos destinatários e mesmo assunto)
    e lê a conversa (thread) dele. Toda mensagem da conversa que não é um dos nossos envios e tem anexo é resposta (inclusive uma
    resposta sua para você mesmo, usada nos testes). Devolve [(mensagem, índice do item)]. Mensagem avulsa na caixa de entrada,
    fora dessas conversas, não conta."""
    lista_enviados = email_gmail.buscarMensagens(servico, f"in:sent subject:extrato after:{email_gmail.segundosEpoch(desde)}")
    lista_respostas, vistos = [], set()
    for ordem_item, elemento in enumerate(itens):
        esperados, ds_assunto = _destinoDoEnvio(elemento, data_fmt)
        lista_nossos = [enviada for enviada in lista_enviados
                        if enviada.id_conversa and esperados <= enviada.para and enviada.assunto.lower() == ds_assunto]
        ids_enviados = {enviada.id for enviada in lista_nossos}
        for id_conversa in {enviada.id_conversa for enviada in lista_nossos}:
            for mensagem in email_gmail.mensagensDaConversa(servico, id_conversa):
                if mensagem.id in ids_enviados or not mensagem.anexos or (mensagem.id, ordem_item) in vistos:
                    continue
                vistos.add((mensagem.id, ordem_item))
                lista_respostas.append((mensagem, ordem_item))
    return lista_respostas


def conferirRespostas(itens, desde, data_ref, pasta_mes):
    """Procura as respostas com anexo aos e-mails que nós enviamos (na conversa de cada um) e salva os arquivos na pasta do
    fundo, no Drive. Retorna ({indice: n_cotistas_recebidos}, n_salvos_agora, falhas) ou None."""
    desde = desde - timedelta(minutes=1)
    data_fmt = data_ref.strftime("%d/%m")
    nm_mes = os.path.basename(pasta_mes)  # AAAA-MM
    manifesto = st.session_state.setdefault("teste_manifesto", {}) if MODO_TESTE else carregarAnexosSalvos(nm_mes, PASTA_EXTRATOS)

    cobertos, sem_ident, falhas, novos = {}, {}, [], 0
    try:
        servico = email_gmail.servicoDaSessao()
    except email_gmail.GmailNaoConectadoErro:
        st.error("A conexão com a conta Google expirou ou não existe. Conecte-se de novo (use \"Conectar ao Google\" na lateral).")
        return None
    try:
        for mensagem, ordem_candidata in _respostasAosEnviados(servico, itens, desde, data_fmt):
            candidatos = [ordem_candidata]  # a resposta é de um e-mail nosso: o item já é conhecido

            for anexo in mensagem.anexos:
                if not _anexoValido(anexo):
                    continue
                nome = _nomeSeguro(anexo.nome)
                chave = f"{mensagem.id}|{nome}|{anexo.tamanho}"
                tmp_salvo = None
                try:
                    arquivo_salvo = extratos_drive.arquivoDeTexto(manifesto[chave]) if chave in manifesto else None
                    if arquivo_salvo is not None:
                        caminho, ja_salvo = arquivo_salvo, True
                    else:
                        # baixa para um temporário; só depois de identificar o fundo vai para o Drive
                        tmp_salvo = caminho = os.path.join(tempfile.gettempdir(), f"extratos_{os.getpid()}_{mensagem.id}_{nome}")
                        with open(caminho, "wb") as arquivo_anexo:
                            arquivo_anexo.write(email_gmail.baixarAnexo(servico, mensagem.id, anexo.id))
                        ja_salvo = False

                    ordem_item = _escolherItem(itens, candidatos, nome, caminho)

                    if not ja_salvo:
                        fundo = _fundoDoAnexo(itens[ordem_item], nome, mensagem, caminho)
                        destino = _guardarNoDrive(caminho, nm_mes, fundo, nome, evitar_duplicata=True)
                        tmp_salvo = None
                        manifesto[chave] = destino.paraTexto()
                        caminho = destino
                        novos += 1
                    elif _emPastaSemFundo(caminho):
                        # já salvo numa pasta de revisão: tenta de novo com as regras atuais
                        fundo = _fundoIdentificado(itens[ordem_item], nome, mensagem, caminho)
                        if fundo:
                            destino = _moverNoDrive(caminho, nm_mes, fundo)
                            manifesto[chave] = destino.paraTexto()
                            caminho = destino
                except Exception as erro:
                    falhas.append(f"{nome}: {erro}")
                    if tmp_salvo and os.path.exists(tmp_salvo):
                        try:
                            os.remove(tmp_salvo)
                        except OSError:
                            pass
                    continue

                # só conta o que foi realmente salvo; conta por cotista identificado no anexo
                pasta_fundo = _pastaDoArquivo(caminho)  # pasta em que o anexo foi guardado
                achados = _cotistasCobertos(itens[ordem_item], nome, caminho, pasta_fundo if pasta_fundo in itens[ordem_item]["fundos"] else None)
                if achados:
                    cobertos.setdefault(ordem_item, set()).update(achados)
                else:
                    sem_ident[ordem_item] = sem_ident.get(ordem_item, 0) + 1
        if not MODO_TESTE:  # a tela de teste não grava no banco
            salvarAnexosSalvos(nm_mes, manifesto, PASTA_EXTRATOS)

        recebidos = {}
        for ordem_item in set(cobertos) | set(sem_ident):
            n_cot = sum(len(cotistas_fundo) for cotistas_fundo in itens[ordem_item]["fundos"].values())
            recebidos[ordem_item] = max(1, min(n_cot, len(cobertos.get(ordem_item, ())) + sem_ident.get(ordem_item, 0)))
        return recebidos, novos, falhas
    except Exception as erro:
        st.error(f"Não foi possível procurar as respostas no Gmail: {erro}")
        return None


def fazerConferencia(rodada, pasta_mes):
    """Consulta o Gmail (envios e respostas) e guarda o resultado na sessão. True se deu certo."""
    status = conferirEnvios(rodada["itens"], rodada["inicio"], rodada["data"])
    resposta_http = conferirRespostas(rodada["itens"], rodada["inicio"], rodada["data"], pasta_mes) if status is not None else None
    if status is None:
        return False
    st.session_state["conferencia"] = {
        "status": status,
        "recebidos": resposta_http[0] if resposta_http else {},
        "falhas": resposta_http[2] if resposta_http else [],
        "hora": datetime.now(),
    }
    if resposta_http and resposta_http[1]:
        st.toast(f"{resposta_http[1]} arquivo(s) salvo(s) na pasta Extratos.")
    return True


UNIDADES_REENVIO = {"horas": 1, "dias": 24, "semanas": 168}


def reenviarSemResposta(rodada, pasta_mes, intervalo):
    """Confere o Gmail e reenvia (de fato envia) os e-mails já enviados que seguem sem extrato
    há mais que o intervalo. Retorna quantos foram reenviados, ou None se a conferência falhou."""
    if not fazerConferencia(rodada, pasta_mes):
        return None
    conf = st.session_state["conferencia"]
    recebidos = dict(conf["recebidos"])
    for chave_item, qt_recebidos_pasta in contarNaPasta(rodada["itens"], pasta_mes).items():
        recebidos[chave_item] = max(recebidos.get(chave_item, 0), qt_recebidos_pasta)
    agora = datetime.now()
    reenvios = rodada.setdefault("reenvios", {})
    devidos = []
    for ordem_item, elemento in enumerate(rodada["itens"]):
        n_cot = sum(len(cotistas_fundo) for cotistas_fundo in elemento["fundos"].values())
        if conf["status"].get(ordem_item) != "Enviado" or recebidos.get(ordem_item, 0) >= n_cot:
            continue
        if agora - reenvios.get(ordem_item, rodada["inicio"]) >= intervalo:
            devidos.append(ordem_item)
    if not devidos:
        return 0
    qt_reenviados = enviarEmailsGmail([rodada["itens"][ordem_item] for ordem_item in devidos], rodada["data"])
    for ordem_item in devidos:
        reenvios[ordem_item] = agora
    try:
        salvarRodada(rodada)
    except OSError:
        pass
    return qt_reenviados


def contarNaPasta(itens, pasta_mes):
    """{indice: cotistas recebidos} a partir dos arquivos nas pastas dos fundos no Drive, inclusive os colocados à mão.
    Só olha as pastas que já existem (não cria nada só para contar)."""
    recebidos = {}
    try:
        login = extratos_drive.loginAtual()
        id_mes = extratos_drive.idPastaDoMes(login, int(pasta_mes[:4]), int(pasta_mes[5:7]))
        if not id_mes:
            return recebidos
        lista_pastas_item, dict_arquivos = [], {}
        for elemento in itens:
            dict_pastas = {}  # pasta -> fundos do item que caem nela (uma pasta pode servir a mais de um fundo)
            for fundo in elemento["fundos"]:
                id_pasta = extratos_drive.idPastaDoFundo(login, id_mes, fundo) if fundo else None
                if id_pasta:
                    dict_pastas.setdefault(id_pasta, []).append(fundo)
                    if id_pasta not in dict_arquivos:
                        dict_arquivos[id_pasta] = extratos_drive.listarArquivos(login, id_pasta)
            lista_pastas_item.append(dict_pastas)
        extratos_drive.prepararTextos(login, [extratos_drive.ArquivoSalvo(dict_arquivo["id"], dict_arquivo["nome"], "", dict_arquivo["modificado"])
                                              for lista_arquivos in dict_arquivos.values() for dict_arquivo in lista_arquivos])
        for ordem_item, elemento in enumerate(itens):
            cobertos, sem_ident = set(), 0
            for id_pasta, lista_fundos in lista_pastas_item[ordem_item].items():
                so_fundo = lista_fundos[0] if len(lista_fundos) == 1 else None
                for dict_arquivo in sorted(dict_arquivos[id_pasta], key=lambda dict_item: dict_item["nome"]):
                    arquivo = extratos_drive.ArquivoSalvo(dict_arquivo["id"], dict_arquivo["nome"], "", dict_arquivo["modificado"])
                    achados = _cotistasCobertos(elemento, dict_arquivo["nome"], arquivo, so_fundo)
                    if achados:
                        cobertos |= achados
                    else:
                        sem_ident += 1
            total = len(cobertos) + sem_ident
            if total:
                n_cot = sum(len(cotistas_fundo) for cotistas_fundo in elemento["fundos"].values())
                recebidos[ordem_item] = max(1, min(n_cot, total))
    except extratos_drive.ERROS_DRIVE as erro:
        st.warning(f"Não consegui contar os arquivos no Drive: {extratos_drive.textoErro(erro)}")
    return recebidos


def assinaturaDoMes(pasta_mes):
    """Muda quando chega, sai ou é alterado um arquivo no Drive do mês (inclusive os colocados à mão)."""
    try:
        return extratos_drive.assinaturaDoMes(extratos_drive.loginAtual(), int(pasta_mes[:4]), int(pasta_mes[5:7]))
    except extratos_drive.ERROS_DRIVE:
        return "erro"


def salvarRodada(rodada, encerrada=False):
    """Guarda a rodada no banco para retomar a conferência em outro dia."""
    if MODO_TESTE:  # a rodada de teste não vai para o banco
        return
    salvarRodadaBanco(rodada, encerrada)


def carregarUltimaRodada():
    """Retorna a rodada aberta mais recente (ou None) e quantas outras rodadas abertas existem."""
    escolhida, outras = carregarRodadaAberta()
    if escolhida:
        for elemento in escolhida["itens"]:
            elemento["invalidos"] = [email for email in listaEmails(elemento["emails"]) if not EMAIL_RE.match(email)]
    return escolhida, outras


def kpi(rotulo, valor, alerta=False, tipo=""):
    cls = "kpi warn" if alerta and valor > 0 else f"kpi {tipo}".strip()
    return f'<div class="{cls}"><div class="kpi-val">{valor}</div><div class="kpi-lbl">{rotulo}</div></div>'


# ==========================================
# INTERFACE
# ==========================================
# set_page_config e tema ficam no portal (home.py)
st.markdown(CSS, unsafe_allow_html=True)

data = st.session_state.get("data_ref")

from app.utilitarias.tema import topo

topo("Solicitação de extratos", "Gere os e-mails de extratos direto no Gmail e envie", app="extratos")
modo_teste.alinharModo(MODO_TESTE)  # trocar entre a tela real e a de teste limpa o que era do outro modo
if MODO_TESTE:
    try:
        ds_link_teste = extratos_drive.linkDaPasta(extratos_drive.idRaiz())
    except extratos_drive.ERROS_DRIVE:
        ds_link_teste = ""
    modo_teste.mostrarFaixa(ds_link_teste)
mostrarResultadoEnvio()

# Áreas da página. A importação fica antes de ler o cadastro: funciona também com o cadastro vazio.
nm_area = st.radio("Área", ["Solicitar extratos", "Importar cadastro", "Apagar cadastros"], horizontal=True, key="area_extratos",
                   label_visibility="collapsed")
if MODO_TESTE and nm_area != "Solicitar extratos":
    st.info("Importar e apagar cadastros mexem no banco de verdade, por isso não funcionam na tela de teste.")
    st.stop()
if nm_area == "Importar cadastro":
    abaImportar()
    st.stop()
if nm_area == "Apagar cadastros":
    abaApagar()
    st.stop()

try:
    if MODO_TESTE:
        df, originais = _mapearColunas(modo_teste.cadastroFicticio())
        dt_consulta = datetime.now()
    else:
        df, originais, dt_consulta = carregarPlanilha(obterVersaoCadastro())
except Exception as erro:
    st.error(f"Não foi possível ler o cadastro de fundos no banco de dados: {erro}")
    st.stop()

if df.empty:
    st.error("O cadastro de fundos (tabela portal_tb_extratos_fundo_cotista) está vazio.")
    st.stop()

faltando = [rotulo for campo, rotulo in OBRIGATORIAS.items() if campo not in df.columns]
if faltando:
    st.error(f"Faltam colunas no cadastro de fundos: {', '.join(faltando)}.")
    st.caption(f"Colunas encontradas: {', '.join(originais)}")
    st.stop()

itens = montarItens(df)
validos = [ordem_item for ordem_item in itens if ordem_item["emails"]]
sem_email = len(itens) - len(validos)
linhas_total = sum(ordem_item["linhas"] for ordem_item in itens)

k1, k2, k3 = st.columns(3)
k1.markdown(kpi("Linhas na planilha", linhas_total), unsafe_allow_html=True)
k2.markdown(kpi("E-mails a enviar", len(validos)), unsafe_allow_html=True)
k3.markdown(kpi("Sem e-mail cadastrado", sem_email, alerta=True), unsafe_allow_html=True)
st.write("")

com_invalido = [ordem_item for ordem_item in validos if ordem_item.get("invalidos")]
if com_invalido:
    st.warning(
        f"{len(com_invalido)} destinatário(s) com e-mail de formato inválido: "
        + "; ".join(email_invalido for ordem_item in com_invalido for email_invalido in ordem_item["invalidos"][:3])
        + ". Corrija na planilha antes de enviar."
    )

esq, dir_ = st.columns([1, 2.3], gap="medium")

# ---------- Painel de envio ----------
with esq:
    with st.container(border=True, key="card_envio"):
        st.markdown(
            '<div class="card-title">Preparar envio</div>'
            '<div class="card-hint">A data aparece no assunto e no texto de cada e-mail. '
            "Destinatários repetidos são unificados: cada um recebe um único e-mail com todos os fundos e cotistas.</div>",
            unsafe_allow_html=True,
        )
        st.date_input("Data de referência", value=None, format="DD/MM/YYYY", key="data_ref")
        motivo = motivoNaoUtil(data) if data else None
        if motivo:
            anterior = diaUtilAnterior(data)
            st.warning(f"{data:%d/%m/%Y} cai em {motivo}. Confira se a data de referência está certa.")
            st.button(
                f"Usar o dia útil anterior ({anterior:%d/%m/%Y})",
                key="usar_util",
                use_container_width=True,
                on_click=lambda dt_dia=anterior: st.session_state.update(data_ref=dt_dia),
            )
        st.write("")

        if st.button(
            f"Revisar e enviar ({len(validos)})",
            type="primary",
            use_container_width=True,
            disabled=data is None or not validos,
        ):
            dialogoRevisarEnvio(validos, data, None, sem_email)

        if data is None:
            st.caption("Escolha a data para liberar os botões de envio.")
        elif validos:
            st.caption(f"{len(validos)} e-mails: você revisa todos numa tela e envia de uma vez, sem abrir rascunhos.")

# ---------- Lista ----------
with dir_:
    with st.container(border=True, key="card_lista"):
        st.markdown('<div class="card-title">Fundos e cotistas</div>', unsafe_allow_html=True)
        busca = st.text_input(
            "Buscar",
            placeholder="Busque por fundo ou cotista",
            label_visibility="collapsed",
        ).strip().lower()

        registros = []
        for elemento in itens:
            for fundo, cots in elemento["fundos"].items():
                for cotista, _doc in (cots or [("", "")]):
                    registros.append({"fundo": fundo, "cotista": cotista, "ok": bool(elemento["emails"])})

        visiveis = [registro for registro in registros if not busca or busca in f"{registro['fundo']} {registro['cotista']}".lower()]

        if not visiveis:
            st.info("Nenhum resultado. Apague o texto da busca para ver a lista completa.")
        else:
            linhas, anterior = [], None
            for registro_visivel in visiveis:
                status = (
                    '<span class="badge ok">E-mail cadastrado</span>'
                    if registro_visivel["ok"]
                    else '<span class="badge sem">Sem e-mail</span>'
                )
                # o nome do fundo aparece só na primeira linha de cada grupo
                novo = registro_visivel["fundo"] != anterior
                anterior = registro_visivel["fundo"]
                nome_fundo = (html.escape(registro_visivel["fundo"]) or "-") if novo else ""
                linhas.append(
                    f'<tr class="{"novo" if novo else "cont"}"><td class="fundo">{nome_fundo}</td>'
                    f'<td>{html.escape(registro_visivel["cotista"]) or "-"}</td><td>{status}</td></tr>'
                )
            st.markdown(
                '<div class="tbl-wrap"><table class="tbl"><thead><tr>'
                "<th>Fundo</th><th>Cotista</th><th>Status</th></tr></thead><tbody>"
                + "".join(linhas)
                + "</tbody></table></div>",
                unsafe_allow_html=True,
            )

        st.caption(f"Cadastro de fundos (banco de dados), consultado em {dt_consulta:%d/%m/%Y %H:%M}.")

# ---------- Conferência de envios e respostas ----------
if "rodada" not in st.session_state and not st.session_state.get("rodada_carregada") and not MODO_TESTE:
    st.session_state["rodada_carregada"] = True
    _retomada, _outras = carregarUltimaRodada()
    if _retomada:
        st.session_state["rodada"] = _retomada
        st.session_state["rodadas_outras"] = _outras

rodada = st.session_state.get("rodada")
if not rodada:
    st.write("")
    st.markdown(
        '<div class="vazio"><b>Conferência de envios e respostas</b>'
        "Ela aparece aqui depois que você criar os e-mails no Gmail.</div>",
        unsafe_allow_html=True,
    )
if rodada:
    st.write("")
    pasta_mes = rodada["data"].strftime("%Y-%m")  # o mês da data de referência decide a pasta do Drive (ex.: 2026-10 -> 2026/10- Outubro)
    conf = st.session_state.get("conferencia")
    pend = []
    if conf:
        # soma ao que veio do Gmail os arquivos que estão nas pastas (inclusive os colocados à mão)
        chave_disco = (pasta_mes, assinaturaDoMes(pasta_mes), conf["hora"])
        if st.session_state.get("disco_chave") != chave_disco:
            st.session_state["disco"] = contarNaPasta(rodada["itens"], pasta_mes)
            st.session_state["disco_chave"] = chave_disco
        efetivos = dict(conf["recebidos"])
        for chave_item, qt_recebida in st.session_state["disco"].items():
            efetivos[chave_item] = max(efetivos.get(chave_item, 0), qt_recebida)
        conf = {**conf, "recebidos": efetivos}
        pend = [
            ordem_item for ordem_item, stt in conf["status"].items()
            if stt in ("Aguardando envio", "Erro de entrega") and ordem_item not in conf["recebidos"]
        ]

    with st.container(border=True, key="card_conf"):
        st.markdown(
            '<div class="card-title">Conferência de envios e respostas</div>'
            f'<div class="card-hint">Rodada de referência {rodada["data"]:%d/%m/%Y}, aberta em '
            f'{rodada["inicio"]:%d/%m às %H:%M}. Depois de enviar, clique em conferir: o app verifica os envios '
            "e salva os extratos recebidos por resposta.</div>",
            unsafe_allow_html=True,
        )
        b1, b2, b3, b4 = st.columns(4)
        if b1.button("Conferir envios e respostas", key="conferir", type="primary", use_container_width=True):
            with st.spinner("Consultando o Gmail..."):
                ok = fazerConferencia(rodada, pasta_mes)
            if ok:
                st.rerun()

        if b2.button(f"Reenviar pendentes ({len(pend)})", key="reabrir", disabled=not pend, use_container_width=True):
            dialogoRevisarEnvio([rodada["itens"][ordem_item] for ordem_item in pend], rodada["data"], rodada)

        try:
            id_pasta_mes = extratos_drive.idPastaDoMes(extratos_drive.loginAtual(), int(pasta_mes[:4]), int(pasta_mes[5:7]))
        except extratos_drive.ERROS_DRIVE:
            id_pasta_mes = None
        if id_pasta_mes:
            b3.link_button("Abrir pasta no Drive", extratos_drive.linkDaPasta(id_pasta_mes), use_container_width=True)
        else:
            b3.button("Abrir pasta no Drive", key="pasta", disabled=True, use_container_width=True,
                      help="A pasta deste mês ainda não existe no Drive: ela é criada quando chegar o primeiro extrato.")

        if b4.button("Encerrar rodada", key="encerrar", use_container_width=True):
            try:
                salvarRodada(rodada, encerrada=True)
            except OSError:
                pass
            st.session_state.pop("rodada", None)
            st.session_state.pop("conferencia", None)
            st.rerun()

        a1, a2 = st.columns([2, 1])
        auto = a1.checkbox(
            "Conferir automaticamente",
            key="auto_conf",
            help="Com o app aberto, consulta o Gmail sozinho no intervalo escolhido e salva as respostas.",
        )
        minutos = a2.selectbox(
            "Intervalo", [5, 10, 15, 30], key="auto_min", disabled=not auto,
            format_func=lambda qt_minutos: f"a cada {qt_minutos} min", label_visibility="collapsed",
        )
        if auto:
            ultima = (st.session_state.get("conferencia") or {}).get("hora") or rodada["inicio"]
            st.caption(f"Próxima conferência automática por volta de {ultima + timedelta(minutes=minutos):%H:%M}.")

            def _auto():
                conferencia_atual = st.session_state.get("conferencia")
                desde = conferencia_atual["hora"] if conferencia_atual else rodada["inicio"]
                if datetime.now() - desde >= timedelta(minutes=minutos):
                    with st.spinner("Conferindo automaticamente no Gmail..."):
                        ok = fazerConferencia(rodada, pasta_mes)
                    if ok:
                        st.rerun()

            st.fragment(run_every=timedelta(minutes=1))(_auto)()

        r1, r2, r3 = st.columns([2, 1, 1])
        reenviar = r1.checkbox(
            "Reenviar automaticamente quem não respondeu",
            key="auto_reenvio",
            help="Com o app aberto, a cada intervalo confere o Gmail e reenvia o e-mail a quem já recebeu "
            "mas ainda não mandou o extrato. Os e-mails são enviados direto, sem abrir para revisão.",
        )
        qtd = r2.number_input(
            "Quantidade", min_value=1, max_value=999, value=1, step=1, key="reenvio_qtd",
            disabled=not reenviar, label_visibility="collapsed",
        )
        unidade = r3.selectbox(
            "Unidade", list(UNIDADES_REENVIO), index=1, key="reenvio_unidade",
            disabled=not reenviar, label_visibility="collapsed",
        )
        if reenviar:
            intervalo_reenvio = timedelta(hours=qtd * UNIDADES_REENVIO[unidade])
            st.caption(f"Reenvia a cada {qtd} {unidade} quem ainda não enviou o extrato.")

            def _reenvio():
                feitos = reenviarSemResposta(rodada, pasta_mes, intervalo_reenvio)
                if feitos:
                    st.toast(f"{feitos} e-mail(s) reenviado(s) automaticamente.")
                if feitos is not None:
                    st.rerun()

            def _checarReenvio():
                # cada e-mail tem o seu prazo; confere com frequência suficiente para respeitá-los
                ultima = st.session_state.get("reenvio_ultima_checagem", rodada["inicio"])
                if datetime.now() - ultima >= min(intervalo_reenvio, timedelta(minutes=30)):
                    st.session_state["reenvio_ultima_checagem"] = datetime.now()
                    with st.spinner("Reenviando e-mails sem resposta..."):
                        _reenvio()

            st.fragment(run_every=timedelta(minutes=1))(_checarReenvio)()

        # vigia da pasta: a cada minuto confere o Drive e atualiza a tela quando chega ou sai arquivo (também os colocados à mão)
        def _vigiar():
            chave_item = f"vigia_{pasta_mes}"
            assinatura = assinaturaDoMes(pasta_mes)
            visto = st.session_state.setdefault(chave_item, assinatura)
            if assinatura != visto:
                st.session_state[chave_item] = assinatura
                st.rerun()

        st.fragment(run_every="60s")(_vigiar)()

        if st.session_state.get("rodadas_outras"):
            st.caption(
                f"Há outras {st.session_state['rodadas_outras']} rodada(s) antiga(s) abertas. "
                "Esta é a mais recente; encerre as que não usa mais."
            )

        if conf and conf.get("falhas"):
            st.warning(
                f"{len(conf['falhas'])} anexo(s) não puderam ser salvos e não foram contados: "
                + "; ".join(conf["falhas"][:5])
            )

        if conf:
            classes = {"Enviado": "ok", "Erro de entrega": "sem", "Em rascunho": "pend", "Aguardando envio": "pend"}
            total = len(rodada["itens"])
            enviados = sum(1 for status_envio in conf["status"].values() if status_envio == "Enviado")
            def _falta(chave_item, elemento_aux):
                return sum(len(cotistas_fundo) for cotistas_fundo in elemento_aux["fundos"].values()) - (conf["recebidos"].get(chave_item) or 0)

            n_completos = sum(1 for chave_item, elemento_aux in enumerate(rodada["itens"]) if _falta(chave_item, elemento_aux) <= 0)
            n_erros = sum(1 for status_envio in conf["status"].values() if status_envio == "Erro de entrega")
            n_pend = total - n_completos
            c1, c2, c3, c4 = st.columns(4)
            c1.markdown(kpi("E-mails enviados", f"{enviados} de {total}", tipo="ok" if enviados == total else ""), unsafe_allow_html=True)
            c2.markdown(kpi("Com extrato recebido", len(conf["recebidos"])), unsafe_allow_html=True)
            c3.markdown(kpi("Completos", n_completos, tipo="ok"), unsafe_allow_html=True)
            c4.markdown(kpi("Com pendência", n_pend, alerta=True), unsafe_allow_html=True)
            st.caption(
                f"Última conferência às {conf['hora']:%H:%M}."
                + (f" {n_erros} com erro de entrega." if n_erros else "")
            )
            filtro = st.radio(
                "Mostrar", ["Todos", "Pendentes", "Completos"], horizontal=True,
                key="filtro_conf", label_visibility="collapsed",
            )
            larguras = [3, 1, 1.7, 1.5, 1.5, 1.5]
            cab = st.columns(larguras)
            for coluna_cab, nm_coluna in zip(cab, ["Fundo", "Cotistas", "Envio", "Extrato", "Alerta", "Ação"]):
                coluna_cab.markdown(f'<div class="colhead">{nm_coluna}</div>', unsafe_allow_html=True)
            st.markdown('<div class="sep"></div>', unsafe_allow_html=True)
            with st.container(height=540, border=False):
                for ordem_item, elemento in enumerate(rodada["itens"]):
                    completo = _falta(ordem_item, elemento) <= 0
                    if (filtro == "Pendentes" and completo) or (filtro == "Completos" and not completo):
                        continue
                    stt = conf["status"].get(ordem_item, "Aguardando envio")
                    rec = conf["recebidos"].get(ordem_item)
                    extrato = (
                        f'<span class="badge ok">Recebido ({rec})</span>' if rec else '<span class="badge pend">Aguardando</span>'
                    )
                    fundos = "; ".join(nm_fundo_item for nm_fundo_item in elemento["fundos"] if nm_fundo_item) or "-"
                    n_cot = sum(len(cotistas_fundo) for cotistas_fundo in elemento["fundos"].values())
                    falta = n_cot - (rec or 0)
                    if falta <= 0:
                        alerta = '<span class="badge ok">Completo</span>'
                    elif rec or stt == "Enviado":
                        alerta = f'<span class="badge sem">Faltam {falta}</span>'
                    else:
                        alerta = '<span class="ativo">-</span>'

                    cols = st.columns(larguras)
                    marca = '<span class="row-warn"></span>' if (stt == "Erro de entrega" or "Faltam" in alerta) else ""
                    cols[0].markdown(f'{marca}<div class="fundo">{html.escape(fundos)}</div>', unsafe_allow_html=True)
                    cols[1].markdown(str(n_cot))
                    cols[2].markdown(f'<span class="badge {classes[stt]}">{stt}</span>', unsafe_allow_html=True)
                    cols[3].markdown(extrato, unsafe_allow_html=True)
                    cols[4].markdown(alerta, unsafe_allow_html=True)
                    # botão individual: só para e-mails não enviados (ou com erro) e sem extrato recebido
                    if stt in ("Aguardando envio", "Erro de entrega") and not rec:
                        if cols[5].button("Reenviar", key=f"reenviar_{ordem_item}", use_container_width=True):
                            dialogoRevisarEnvio([elemento], rodada["data"], rodada)
                    else:
                        cols[5].markdown('<span class="ativo">-</span>', unsafe_allow_html=True)
                    st.markdown('<div class="sep"></div>', unsafe_allow_html=True)
            st.caption(
                f"Arquivos salvos no Drive (BO_Extratos Mensais, pasta do mês {pasta_mes}), uma pasta por fundo. Em e-mails com mais de um fundo, o fundo é "
                "identificado pelo nome do arquivo, pelo conteúdo do PDF, pelo assunto ou pelo corpo da resposta; "
                "se nada identificar, o anexo vai para uma pasta com o nome do remetente. O extrato é reconhecido em "
                "respostas com anexo na Caixa de Entrada do Gmail, pelo remetente ou pelo assunto. Quem já tem rascunho "
                "no Gmail não entra em 'Reenviar pendentes', para evitar e-mail duplicado."
            )
