import html
import json
import os
import re
import shutil
import time
import unicodedata
from collections import Counter, OrderedDict
from datetime import date, datetime, timedelta
from functools import lru_cache

import pandas as pd
import pythoncom
import streamlit as st
import win32com.client as win32

try:
    from pypdf import PdfReader  # opcional: pip install pypdf
except ImportError:
    PdfReader = None

try:
    from watchdog.events import FileSystemEventHandler  # opcional: pip install watchdog
    from watchdog.observers import Observer
except ImportError:
    Observer = FileSystemEventHandler = None

from app.ambiente.config_ambiente import obterDiretorioDados  # noqa: E402

# Pasta de dados do app: não depende de onde o comando foi executado
BASE = str(obterDiretorioDados("extratos"))
ARQUIVO = os.path.join(BASE, "Template_Fundos_Ativos.xlsx")
EMAIL_RE = re.compile(r"^[^@\s;,]+@[^@\s;,]+\.[^@\s;,]+$")

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


@st.cache_data
def carregarPlanilha(caminho, mtime):
    # dtype=str preserva zeros à esquerda de CPF/CNPJ
    df = pd.read_excel(caminho, dtype=str).dropna(how="all")
    originais = [str(coluna_original) for coluna_original in df.columns]
    mapa = {}
    for col in df.columns:
        nm_coluna_norm = norm(col)
        for campo, nomes in ALIASES.items():
            if nm_coluna_norm in nomes and campo not in mapa.values():
                mapa[col] = campo
    return df.rename(columns=mapa), originais


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
    """Coloca o texto logo após <body>, preservando a assinatura do Outlook."""
    correspondencia = re.search(r"<body[^>]*>", html_existente, flags=re.IGNORECASE)
    if correspondencia:
        return html_existente[: correspondencia.end()] + corpo + html_existente[correspondencia.end():]
    return corpo + html_existente


def abrirEmailsOutlook(itens, data_ref, enviar=False):
    data_fmt = data_ref.strftime("%d/%m")
    abertos = 0
    pythoncom.CoInitialize()
    try:
        aplicativo_outlook = win32.Dispatch("outlook.application")
        for item in itens:
            try:
                mensagem_email = aplicativo_outlook.CreateItem(0)
                mensagem_email.To = item["emails"]

                # Insere os e-mails em cópia (CC)
                if EMAILS_EM_COPIA:
                    mensagem_email.CC = EMAILS_EM_COPIA

                mensagem_email.Subject = montarAssunto(item, data_fmt)
                mensagem_email.Display()  # carrega a assinatura padrão
                for _ in range(10):  # espera a assinatura carregar antes de inserir o texto
                    try:
                        if re.search(r"<body", mensagem_email.HTMLBody, flags=re.IGNORECASE):
                            break
                    except Exception:
                        pass
                    time.sleep(0.2)
                mensagem_email.HTMLBody = inserirNoCorpo(mensagem_email.HTMLBody, montarCorpoHtml(item, data_fmt))
                if enviar:
                    mensagem_email.Send()
                abertos += 1
            except Exception as erro:
                st.error(f"Não foi possível abrir o e-mail para {item['emails']}: {erro}")
    except Exception as erro:
        st.error(f"Não foi possível conectar ao Outlook. Abra o Outlook e tente de novo. Detalhe: {erro}")
    finally:
        pythoncom.CoUninitialize()
    return abertos


PR_SMTP = "http://schemas.microsoft.com/mapi/proptag/0x39FE001E"
NDR_MARCAS = (
    "undeliverable", "delivery status notification", "mail delivery", "returned mail",
    "não foi possível entregar", "nao foi possivel entregar", "falha na entrega", "não entregue",
)


def _smtp(rec):
    try:
        endereco = rec.PropertyAccessor.GetProperty(PR_SMTP)
        if endereco:
            return str(endereco).lower()
    except Exception:
        pass
    try:
        return str(rec.Address).lower()
    except Exception:
        return ""


def _destinatarios(texto_mensagem):
    """Endereços SMTP dos destinatários 'Para' da mensagem."""
    try:
        return {_smtp(destinatario) for destinatario in texto_mensagem.Recipients if destinatario.Type == 1} - {""}
    except Exception:
        return set()


def _recentes(pasta, campo, desde):
    """Itens da pasta com data >= desde, do mais novo para o mais antigo."""
    itens = pasta.Items
    itens.Sort(f"[{campo}]", True)
    achados = []
    for mensagem in itens:
        try:
            quando = getattr(mensagem, campo).replace(tzinfo=None)
        except Exception:
            continue
        if quando < desde:
            break
        achados.append(mensagem)
    return achados


def conferirEnvios(itens, desde):
    """Confere no Outlook o que aconteceu com cada e-mail aberto. Retorna {indice: status}."""
    desde = desde - timedelta(minutes=1)
    status = {ordem_item: "Aguardando envio" for ordem_item in range(len(itens))}
    pythoncom.CoInitialize()
    try:
        ns = win32.Dispatch("outlook.application").GetNamespace("MAPI")
        enviados = []
        for mensagem in _recentes(ns.GetDefaultFolder(5), "SentOn", desde):
            try:
                enviados.append((_destinatarios(mensagem), str(mensagem.Subject).lower(), mensagem.SentOn.replace(tzinfo=None)))
            except Exception:
                continue
        saida = [(_destinatarios(mensagem), str(mensagem.Subject).lower()) for mensagem in ns.GetDefaultFolder(4).Items]
        devolvidos = []
        for mensagem in _recentes(ns.GetDefaultFolder(6), "ReceivedTime", desde):
            try:
                if any(chave_item in str(mensagem.Subject).lower() for chave_item in NDR_MARCAS):
                    devolvidos.append((mensagem.ReceivedTime.replace(tzinfo=None), str(mensagem.Body).lower()))
            except Exception:
                continue

        for ordem_item, elemento in enumerate(itens):
            esperados = {email.lower() for email in listaEmails(elemento["emails"])}
            casados = [dict_ambiente for dest, assunto, dict_ambiente in enviados if esperados <= dest and "extrato" in assunto]
            if casados:
                status[ordem_item] = "Enviado"
                # só vale devolução recebida depois do envio mais antigo deste e-mail
                primeiro = min(casados)
                if any(rec >= primeiro and email_esperado in corpo for rec, corpo in devolvidos for email_esperado in esperados):
                    status[ordem_item] = "Erro de entrega"
            elif any(esperados <= dest and "extrato" in assunto for dest, assunto in saida):
                status[ordem_item] = "Na caixa de saída"
        return status
    except Exception as erro:
        st.error(f"Não foi possível conferir no Outlook: {erro}")
        return None
    finally:
        pythoncom.CoUninitialize()


PASTA_EXTRATOS = os.path.join(BASE, "Extratos")
PR_ANEXO_OCULTO = "http://schemas.microsoft.com/mapi/proptag/0x7FFE000B"
PREFIXO_REVISAR = "_Revisar"  # anexos sem fundo identificado; também reclassificados a cada conferência


def _nomeSeguro(txt):
    limpo = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(txt))
    return re.sub(r"\s+", " ", limpo).strip(" .") or "sem_nome"


def _assuntoBase(assunto):
    """Tira prefixos de resposta/encaminhamento (RE:, RES:, ENC:, FW:...)."""
    return re.sub(r"^\s*((re|res|enc|fw|fwd|rv)\s*:\s*)+", "", str(assunto), flags=re.I).strip().lower()


def _remetente(texto_mensagem):
    try:
        if str(texto_mensagem.SenderEmailType).upper() == "SMTP":
            return str(texto_mensagem.SenderEmailAddress).lower()
        return str(texto_mensagem.Sender.GetExchangeUser().PrimarySmtpAddress).lower()
    except Exception:
        return ""


def _anexoValido(anexo):
    """Só arquivos de verdade: ignora itens embutidos, anexos ocultos e logos de assinatura."""
    try:
        if anexo.Type != 1:
            return False
        try:
            if anexo.PropertyAccessor.GetProperty(PR_ANEXO_OCULTO):
                return False
        except Exception:
            pass
        nome = str(anexo.FileName).lower()
        if nome.endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp")) and int(anexo.Size) < 50000:
            return False
        return True
    except Exception:
        return False


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
    """Texto das primeiras páginas do PDF (com cache por arquivo, para não reler a cada conferência)."""
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

    def corpo():
        try:
            return str(texto_mensagem.Body)
        except Exception:
            return ""

    def assunto():
        try:
            return str(texto_mensagem.Subject)
        except Exception:
            return ""

    total = {}
    for peso, fonte in ((3, nome_arquivo), (3, _textoPdf(caminho)), (1, assunto()), (0.5, corpo())):
        for fundo, vl_pontos in _pontuar(item, fonte).items():
            total[fundo] = total.get(fundo, 0) + vl_pontos * peso
    return _vencedor(total)


def _pastaSemFundo(texto_mensagem):
    """Pasta de revisão para anexos que não foram associados a nenhum fundo."""
    try:
        remetente = re.sub(r"\s+", " ", str(texto_mensagem.SenderName)).strip()
    except Exception:
        remetente = ""
    return f"{PREFIXO_REVISAR} - {remetente}" if remetente else f"{PREFIXO_REVISAR} - remetente desconhecido"


def _fundoDoAnexo(item, nome_arquivo, texto_mensagem, caminho):
    """Nome da pasta do anexo: o fundo identificado ou, na falta dele, a pasta de revisão."""
    return _fundoIdentificado(item, nome_arquivo, texto_mensagem, caminho) or _pastaSemFundo(texto_mensagem)


def _emPastaSemFundo(caminho):
    pasta = os.path.basename(os.path.dirname(caminho))
    return pasta.startswith((PREFIXO_REVISAR, "Remetente"))  # "Remetente" = nome antigo da pasta


def _moverParaPasta(origem, pasta_mes, nome_pasta, nome, evitar_duplicata=False):
    """Move o arquivo para <pasta_mes>/<nome_pasta>/ sem sobrescrever nada. Com evitar_duplicata,
    se a pasta já tem um arquivo de mesmo nome e tamanho, descarta a cópia e aponta para o existente."""
    pasta = os.path.join(pasta_mes, _nomeSeguro(nome_pasta))
    os.makedirs(pasta, exist_ok=True)
    base, extensao = os.path.splitext(nome)
    destino, nr_copia = os.path.join(pasta, nome), 1
    while os.path.exists(destino):
        if evitar_duplicata and os.path.getsize(destino) == os.path.getsize(origem):
            os.remove(origem)
            return destino
        destino = os.path.join(pasta, f"{base} ({nr_copia}){extensao}")
        nr_copia += 1
    shutil.move(origem, destino)
    return destino


def conferirRespostas(itens, desde, data_ref, pasta_mes):
    """Procura respostas com anexo na Caixa de Entrada e salva os arquivos em
    Extratos/AAAA-MM/<Fundo>/. Retorna ({indice: n_cotistas_recebidos}, n_salvos_agora, falhas) ou None."""
    desde = desde - timedelta(minutes=1)
    data_fmt = data_ref.strftime("%d/%m")
    esperados = [{email.lower() for email in listaEmails(elemento["emails"])} for elemento in itens]
    assuntos = [_assuntoBase(montarAssunto(elemento, data_fmt)) for elemento in itens]
    repetidos = Counter(assuntos)

    os.makedirs(pasta_mes, exist_ok=True)
    manifesto_path = os.path.join(pasta_mes, "_salvos.json")
    try:
        with open(manifesto_path, encoding="utf-8") as arquivo:
            manifesto = json.load(arquivo)
    except Exception:
        manifesto = {}

    cobertos, sem_ident, falhas, novos = {}, {}, [], 0
    pythoncom.CoInitialize()
    try:
        ns = win32.Dispatch("outlook.application").GetNamespace("MAPI")
        for mensagem in _recentes(ns.GetDefaultFolder(6), "ReceivedTime", desde):
            try:
                if mensagem.Class != 43 or mensagem.Attachments.Count == 0:
                    continue
                remetente, assunto = _remetente(mensagem), _assuntoBase(mensagem.Subject)
            except Exception:
                continue

            # ignora resposta que cita outra data de referência (ex.: extrato de outro mês)
            datas = re.findall(r"\b\d{2}/\d{2}\b", assunto)
            if datas and data_fmt not in datas:
                continue

            # todos os itens do remetente; se houver mais de um, o conteúdo do anexo desempata
            candidatos = [chave_item for chave_item, esperados_item in enumerate(esperados) if remetente in esperados_item and "extrato" in assunto]
            if not candidatos:
                candidatos = [chave_item for chave_item, assunto_item in enumerate(assuntos) if assunto_item == assunto and repetidos[assunto_item] == 1]
            if not candidatos:
                continue

            for anexo in mensagem.Attachments:
                if not _anexoValido(anexo):
                    continue
                nome = _nomeSeguro(anexo.FileName)
                chave = f"{mensagem.EntryID}|{nome}|{anexo.Size}"
                tmp_salvo = None
                try:
                    if chave in manifesto and os.path.exists(manifesto[chave]):
                        caminho, ja_salvo = manifesto[chave], True
                    else:
                        # salva numa pasta temporária; só depois de identificar o fundo vai para o destino
                        tmp = os.path.join(pasta_mes, "_tmp")
                        os.makedirs(tmp, exist_ok=True)
                        tmp_salvo = caminho = os.path.join(tmp, f"{os.getpid()}_{nome}")
                        anexo.SaveAsFile(caminho)
                        ja_salvo = False

                    ordem_item = _escolherItem(itens, candidatos, nome, caminho)

                    if not ja_salvo:
                        fundo = _fundoDoAnexo(itens[ordem_item], nome, mensagem, caminho)
                        destino = _moverParaPasta(caminho, pasta_mes, fundo, nome)
                        tmp_salvo = None
                        manifesto[chave] = destino
                        caminho = destino
                        novos += 1
                    elif _emPastaSemFundo(caminho):
                        # já salvo numa pasta de revisão: tenta de novo com as regras atuais
                        fundo = _fundoIdentificado(itens[ordem_item], nome, mensagem, caminho)
                        if fundo:
                            destino = _moverParaPasta(caminho, pasta_mes, fundo, nome, evitar_duplicata=True)
                            manifesto[chave] = caminho = destino
                except Exception as erro:
                    falhas.append(f"{nome}: {erro}")
                    if tmp_salvo and os.path.exists(tmp_salvo):
                        try:
                            os.remove(tmp_salvo)
                        except OSError:
                            pass
                    continue

                # só conta o que foi realmente salvo; conta por cotista identificado no anexo
                pasta_fundo = os.path.basename(os.path.dirname(caminho))  # fundo em que o anexo foi guardado
                achados = _cotistasCobertos(itens[ordem_item], nome, caminho, pasta_fundo if pasta_fundo in itens[ordem_item]["fundos"] else None)
                if achados:
                    cobertos.setdefault(ordem_item, set()).update(achados)
                else:
                    sem_ident[ordem_item] = sem_ident.get(ordem_item, 0) + 1
        with open(manifesto_path, "w", encoding="utf-8") as arquivo:
            json.dump(manifesto, arquivo, ensure_ascii=False, indent=1)

        recebidos = {}
        for ordem_item in set(cobertos) | set(sem_ident):
            n_cot = sum(len(cotistas_fundo) for cotistas_fundo in itens[ordem_item]["fundos"].values())
            recebidos[ordem_item] = max(1, min(n_cot, len(cobertos.get(ordem_item, ())) + sem_ident.get(ordem_item, 0)))
        return recebidos, novos, falhas
    except Exception as erro:
        st.error(f"Não foi possível procurar as respostas no Outlook: {erro}")
        return None
    finally:
        pythoncom.CoUninitialize()


def fazerConferencia(rodada, pasta_mes):
    """Consulta o Outlook (envios e respostas) e guarda o resultado na sessão. True se deu certo."""
    status = conferirEnvios(rodada["itens"], rodada["inicio"])
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
    """Confere o Outlook e reenvia (de fato envia) os e-mails já enviados que seguem sem extrato
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
    qt_reenviados = abrirEmailsOutlook([rodada["itens"][ordem_item] for ordem_item in devidos], rodada["data"], enviar=True)
    for ordem_item in devidos:
        reenvios[ordem_item] = agora
    try:
        salvarRodada(rodada)
    except OSError:
        pass
    return qt_reenviados


def contarNaPasta(itens, pasta_mes):
    """{indice: cotistas recebidos} a partir dos arquivos nas pastas dos fundos, inclusive os colocados à mão."""
    recebidos = {}
    for ordem_item, elemento in enumerate(itens):
        cobertos, sem_ident = set(), 0
        for fundo in elemento["fundos"]:
            pasta = os.path.join(pasta_mes, _nomeSeguro(fundo)) if fundo else ""
            if not pasta or not os.path.isdir(pasta):
                continue
            for nome in sorted(os.listdir(pasta)):
                caminho = os.path.join(pasta, nome)
                if not os.path.isfile(caminho):
                    continue
                achados = _cotistasCobertos(elemento, nome, caminho, fundo)
                if achados:
                    cobertos |= achados
                else:
                    sem_ident += 1
        total = len(cobertos) + sem_ident
        if total:
            n_cot = sum(len(cotistas_fundo) for cotistas_fundo in elemento["fundos"].values())
            recebidos[ordem_item] = max(1, min(n_cot, total))
    return recebidos


@st.cache_resource
def iniciarVigia(pasta):
    """Vigia a pasta do mês (watchdog) e conta os eventos de arquivo; a tela compara o contador para se atualizar."""
    estado = {"n": 0}
    if Observer is None:
        return estado
    os.makedirs(pasta, exist_ok=True)

    class _Vigia(FileSystemEventHandler):
        def _tocou(self, registro_evento):
            caminho = str(getattr(registro_evento, "dest_path", "") or registro_evento.src_path)
            if registro_evento.is_directory or f"{os.sep}_tmp{os.sep}" in caminho or caminho.endswith("_salvos.json"):
                return
            estado["n"] += 1

        on_created = on_moved = on_deleted = _tocou

    try:
        obs = Observer()
        obs.daemon = True
        obs.schedule(_Vigia(), pasta, recursive=True)
        obs.start()
    except Exception:
        pass
    return estado


def _dirRodadas():
    return os.path.join(PASTA_EXTRATOS, "_rodadas")


def salvarRodada(rodada, encerrada=False):
    """Guarda a rodada em disco para retomar a conferência em outro dia."""
    os.makedirs(_dirRodadas(), exist_ok=True)
    # data+hora de abertura no nome: refazer a rodada da mesma data não sobrescreve a anterior
    caminho = rodada.get("arquivo") or os.path.join(
        _dirRodadas(), f"{rodada['data']:%Y-%m-%d}_{rodada['inicio']:%H%M%S}.json"
    )
    dados = {
        "inicio": rodada["inicio"].isoformat(),
        "data": rodada["data"].isoformat(),
        "encerrada": encerrada,
        "reenvios": {str(chave_item): dt_reenvio.isoformat() for chave_item, dt_reenvio in rodada.get("reenvios", {}).items()},
        "itens": [
            {
                "emails": elemento["emails"],
                "linhas": elemento["linhas"],
                "cnpjs": elemento["cnpjs"],
                "fundos": [[nm_fundo_item, [list(cotista) for cotista in cots]] for nm_fundo_item, cots in elemento["fundos"].items()],
            }
            for elemento in rodada["itens"]
        ],
    }
    with open(caminho, "w", encoding="utf-8") as arquivo:
        json.dump(dados, arquivo, ensure_ascii=False, indent=1)
    rodada["arquivo"] = caminho


def carregarUltimaRodada():
    """Retorna a rodada aberta mais recente (ou None) e quantas outras rodadas abertas existem."""
    pasta = _dirRodadas()
    if not os.path.isdir(pasta):
        return None, 0
    arquivos = sorted(
        (os.path.join(pasta, nm_arquivo) for nm_arquivo in os.listdir(pasta) if nm_arquivo.endswith(".json")),
        key=os.path.getmtime,
        reverse=True,
    )
    escolhida, outras = None, 0
    for caminho in arquivos:
        try:
            with open(caminho, encoding="utf-8") as arquivo:
                dict_rodada = json.load(arquivo)
            if dict_rodada.get("encerrada"):
                continue
            if escolhida is not None:
                outras += 1
                continue
            itens = [
                {
                    "emails": ordem_item["emails"],
                    "linhas": ordem_item["linhas"],
                    "cnpjs": ordem_item["cnpjs"],
                    "fundos": OrderedDict((fu, [tuple(cotista) for cotista in cots]) for fu, cots in ordem_item["fundos"]),
                }
                for ordem_item in dict_rodada["itens"]
            ]
            for elemento in itens:
                elemento["invalidos"] = [email for email in listaEmails(elemento["emails"]) if not EMAIL_RE.match(email)]
            escolhida = {
                "inicio": datetime.fromisoformat(dict_rodada["inicio"]),
                "data": datetime.fromisoformat(dict_rodada["data"]).date(),
                "itens": itens,
                "arquivo": caminho,
                "reenvios": {int(chave_item): datetime.fromisoformat(dt_reenvio) for chave_item, dt_reenvio in dict_rodada.get("reenvios", {}).items()},
            }
        except Exception:
            continue
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

topo("Solicitação de extratos", "Gere os e-mails de extratos direto no Outlook e envie", app="extratos")

if not os.path.exists(ARQUIVO):
    st.error(f"Não encontrei '{os.path.basename(ARQUIVO)}'. Coloque a planilha na mesma pasta do app.py e recarregue a página.")
    st.stop()

mtime = os.path.getmtime(ARQUIVO)
df, originais = carregarPlanilha(ARQUIVO, mtime)

faltando = [rotulo for campo, rotulo in OBRIGATORIAS.items() if campo not in df.columns]
if faltando:
    st.error(f"Faltam colunas na planilha: {', '.join(faltando)}.")
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
            f"Abrir todos ({len(validos)})",
            type="primary",
            use_container_width=True,
            disabled=data is None or not validos,
        ):
            st.session_state["confirmar_todos"] = True

        if data is None:
            st.caption("Escolha a data para liberar os botões de envio.")
        elif validos:
            st.caption(f"{len(validos)} e-mails serão abertos no Outlook, um por destinatário. Você revisa e envia cada um.")

        if st.session_state.get("confirmar_todos") and not (data and validos):
            st.session_state["confirmar_todos"] = False

        if st.session_state.get("confirmar_todos"):
            aviso = f"O Outlook vai abrir {len(validos)} janelas de e-mail."
            if sem_email:
                aviso += f" {sem_email} sem e-mail cadastrado ficam de fora."
            st.warning(aviso)
            b1, b2 = st.columns(2)
            if b1.button("Sim, abrir", key="confirma", type="primary", use_container_width=True):
                st.session_state["confirmar_todos"] = False
                inicio = datetime.now()
                abertos = abrirEmailsOutlook(validos, data)
                if abertos:
                    st.session_state["rodada"] = {"inicio": inicio, "data": data, "itens": validos}
                    salvarRodada(st.session_state["rodada"])
                    st.session_state.pop("conferencia", None)
                    st.toast(f"{abertos} e-mails abertos no Outlook.")
            if b2.button("Cancelar", key="cancela", use_container_width=True):
                st.session_state["confirmar_todos"] = False
                st.rerun()

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

        st.caption(f"Planilha {os.path.basename(ARQUIVO)}, atualizada em {datetime.fromtimestamp(mtime):%d/%m/%Y %H:%M}.")

# ---------- Conferência de envios e respostas ----------
if "rodada" not in st.session_state and not st.session_state.get("rodada_carregada"):
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
        "Ela aparece aqui depois que você abrir os e-mails no Outlook.</div>",
        unsafe_allow_html=True,
    )
if rodada:
    st.write("")
    pasta_mes = os.path.join(PASTA_EXTRATOS, rodada["data"].strftime("%Y-%m"))
    vigia = iniciarVigia(pasta_mes)
    conf = st.session_state.get("conferencia")
    pend = []
    if conf:
        # soma ao que veio do Outlook os arquivos que estão nas pastas (inclusive os colocados à mão)
        chave_disco = (pasta_mes, vigia["n"], conf["hora"])
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
            with st.spinner("Consultando o Outlook..."):
                ok = fazerConferencia(rodada, pasta_mes)
            if ok:
                st.rerun()

        if b2.button(f"Reabrir pendentes ({len(pend)})", key="reabrir", disabled=not pend, use_container_width=True):
            if abrirEmailsOutlook([rodada["itens"][ordem_item] for ordem_item in pend], rodada["data"]):
                st.toast("E-mails pendentes abertos no Outlook.")

        if b3.button("Abrir pasta dos extratos", key="pasta", use_container_width=True):
            try:
                os.makedirs(pasta_mes, exist_ok=True)
                os.startfile(pasta_mes)
            except (AttributeError, OSError) as erro:
                st.error(f"Não foi possível abrir a pasta: {erro}")

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
            help="Com o app aberto, consulta o Outlook sozinho no intervalo escolhido e salva as respostas.",
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
                    with st.spinner("Conferindo automaticamente no Outlook..."):
                        ok = fazerConferencia(rodada, pasta_mes)
                    if ok:
                        st.rerun()

            st.fragment(run_every=timedelta(minutes=1))(_auto)()

        r1, r2, r3 = st.columns([2, 1, 1])
        reenviar = r1.checkbox(
            "Reenviar automaticamente quem não respondeu",
            key="auto_reenvio",
            help="Com o app aberto, a cada intervalo confere o Outlook e reenvia o e-mail a quem já recebeu "
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

        # vigia da pasta: atualiza a tela quando chega ou sai arquivo (também os colocados à mão)
        def _vigiar():
            chave_item = f"vigia_{pasta_mes}"
            visto = st.session_state.setdefault(chave_item, vigia["n"])
            if vigia["n"] != visto:
                st.session_state[chave_item] = vigia["n"]
                st.rerun()

        st.fragment(run_every="3s")(_vigiar)()

        if st.session_state.get("rodadas_outras"):
            st.caption(
                f"Há outras {st.session_state['rodadas_outras']} rodada(s) antiga(s) abertas em Extratos/_rodadas. "
                "Esta é a mais recente; encerre as que não usa mais."
            )

        if conf and conf.get("falhas"):
            st.warning(
                f"{len(conf['falhas'])} anexo(s) não puderam ser salvos e não foram contados: "
                + "; ".join(conf["falhas"][:5])
            )

        if conf:
            classes = {"Enviado": "ok", "Erro de entrega": "sem", "Na caixa de saída": "pend", "Aguardando envio": "pend"}
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
                            if abrirEmailsOutlook([elemento], rodada["data"]):
                                st.toast("E-mail aberto no Outlook.")
                    else:
                        cols[5].markdown('<span class="ativo">-</span>', unsafe_allow_html=True)
                    st.markdown('<div class="sep"></div>', unsafe_allow_html=True)
            st.caption(
                f"Arquivos salvos em {pasta_mes}, uma pasta por fundo. Em e-mails com mais de um fundo, o fundo é "
                "identificado pelo nome do arquivo, pelo conteúdo do PDF, pelo assunto ou pelo corpo da resposta; "
                "se nada identificar, o anexo vai para uma pasta com o nome do remetente. O extrato é reconhecido em "
                "respostas com anexo na Caixa de Entrada padrão, pelo remetente ou pelo assunto. Na caixa de saída "
                "não entra em 'Reabrir pendentes', para evitar e-mail duplicado."
            )
