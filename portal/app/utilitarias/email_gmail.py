"""E-mail do portal pela API do Gmail (no lugar do Outlook via win32/COM).

Cada usuário do portal conecta o próprio Gmail uma vez ("Conectar ao Gmail"). O portal guarda só o refresh token,
criptografado, um arquivo por usuário do portal, em dados/gmail/tokens. A senha do Google nunca passa pelo portal.

Variáveis (config_ambiente): PATH_CREDENCIAIS_GMAIL (credentials.json do cliente OAuth, fora do git),
URL_PORTAL (igual ao URI de redirecionamento do cliente OAuth) e CHAVE_GMAIL (chave Fernet; no local, se faltar,
é criada em dados/gmail/chave.key).
"""
import base64
import hashlib
import html
import json
import mimetypes
import os
import re
import secrets
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import getaddresses
from pathlib import Path

import streamlit as st

from app.ambiente.config_ambiente import APP_ENV, obterDiretorioDados, obterVariavel
from app.seguranca import controle_acesso
from app.utilitarias.tema import COR

LISTA_ESCOPOS = [
    "https://www.googleapis.com/auth/gmail.compose",   # criar rascunhos e enviar
    "https://www.googleapis.com/auth/gmail.readonly",  # conferir enviados/respostas e baixar anexos
    "https://www.googleapis.com/auth/drive",           # ler e gravar arquivos no Google Drive (módulo drive_google)
]

dict_pendentes = {}  # estado -> (login do portal, quando); o retorno do Google abre uma sessão nova
trava_pendentes = threading.Lock()


class GmailNaoConectadoErro(Exception):
    """Usuário sem autorização (ou autorização revogada): precisa clicar em "Conectar ao Gmail"."""


class Anexo:
    def __init__(self, id_anexo, nm_arquivo, vl_tamanho, ic_embutido=False, ds_cid=""):
        self.id = id_anexo
        self.nome = nm_arquivo
        self.tamanho = vl_tamanho
        self.embutido = ic_embutido  # imagem embutida no corpo (logo de assinatura)
        self.cid = ds_cid  # Content-ID da imagem embutida (aparece como cid:... no HTML do corpo)


class Mensagem:
    def __init__(self, id_mensagem):
        self.id = id_mensagem
        self.assunto = ""
        self.remetente = ""  # e-mail em minúsculas
        self.nome_remetente = ""
        self.para = set()
        self.quando = None  # horário local, sem fuso
        self.corpo = ""
        self.corpo_html = ""
        self.anexos = []
        self.id_conversa = ""  # threadId: o envio e as respostas ficam na mesma conversa
        self.rotulos = set()  # INBOX, SENT, ...


# ==========================================
# AUTORIZAÇÃO (OAuth) E GUARDA DO TOKEN
# ==========================================
def diretorioGmail():
    return obterDiretorioDados("gmail")


def carregarFernet():
    from cryptography.fernet import Fernet

    ds_chave = obterVariavel("CHAVE_GMAIL")
    if not ds_chave:
        if APP_ENV != "local":
            raise RuntimeError("CHAVE_GMAIL não definida (Parameter Store em hom/prd)")
        arquivo_chave = diretorioGmail() / "chave.key"
        if not arquivo_chave.exists():
            arquivo_chave.write_bytes(Fernet.generate_key())
        ds_chave = arquivo_chave.read_text().strip()
    return Fernet(ds_chave.encode())


def arquivoToken(login):
    pasta_tokens = diretorioGmail() / "tokens"
    pasta_tokens.mkdir(parents=True, exist_ok=True)
    return pasta_tokens / (hashlib.sha256(login.lower().encode()).hexdigest()[:24] + ".tok")


def horasSessaoGoogle():
    """Quanto tempo vale a conexão com o Google depois do login (padrão 24h); passado isso, é preciso reconectar."""
    try:
        return float(obterVariavel("GOOGLE_SESSAO_HORAS") or 24)
    except ValueError:
        return 24.0


def salvarToken(login, ds_email, credenciais, dt_conectado=None):
    """Guarda o token. `dt_conectado` é o momento do login no Google e não muda nas renovações do token."""
    dict_token = {"email": ds_email, "credenciais": json.loads(credenciais.to_json()),
                  "conectado_em": (dt_conectado or datetime.now()).isoformat()}
    arquivoToken(login).write_bytes(carregarFernet().encrypt(json.dumps(dict_token).encode()))


def lerToken(login):
    arquivo_token = arquivoToken(login)
    if not arquivo_token.exists():
        return None
    return json.loads(carregarFernet().decrypt(arquivo_token.read_bytes()))


def criarFluxo():
    from google_auth_oauthlib.flow import Flow

    arquivo_credenciais = obterVariavel("PATH_CREDENCIAIS_GMAIL")
    if not arquivo_credenciais or not Path(arquivo_credenciais).exists():
        raise FileNotFoundError(f"credentials.json não encontrado em PATH_CREDENCIAIS_GMAIL ({arquivo_credenciais or 'vazio'})")
    return Flow.from_client_secrets_file(
        arquivo_credenciais, scopes=LISTA_ESCOPOS, redirect_uri=obterVariavel("URL_PORTAL"), autogenerate_code_verifier=False,
    )


def urlDeLogin(login):
    """Endereço da tela de login/autorização do Google para este usuário do portal."""
    ds_estado = secrets.token_urlsafe(24)
    with trava_pendentes:
        vl_agora = time.time()
        for ds_antigo in [chave for chave, valor in dict_pendentes.items() if vl_agora - valor[1] > 900]:  # esquece pedidos com mais de 15 min
            del dict_pendentes[ds_antigo]
        dict_pendentes[ds_estado] = (login, vl_agora)
    ds_url, _ = criarFluxo().authorization_url(
        access_type="offline", prompt="consent", state=ds_estado, include_granted_scopes="true")
    return ds_url


def concluirLogin(login, ds_codigo, ds_estado):
    """Troca o código devolvido pelo Google por credenciais e guarda o token do usuário. Devolve o e-mail da conta."""
    with trava_pendentes:
        tupla_pedido = dict_pendentes.pop(ds_estado, None)
    if tupla_pedido is None or tupla_pedido[0] != login:
        raise ValueError("Pedido de login desconhecido ou expirado. Clique em Conectar ao Gmail de novo.")
    fluxo = criarFluxo()
    fluxo.fetch_token(code=ds_codigo)
    credenciais = fluxo.credentials
    if not credenciais.refresh_token:
        raise ValueError("O Google não devolveu a autorização permanente. Remova o acesso do app na conta Google e conecte de novo.")
    from googleapiclient.discovery import build

    ds_email = build("gmail", "v1", credentials=credenciais, cache_discovery=False).users().getProfile(userId="me").execute()["emailAddress"].lower()
    salvarToken(login, ds_email, credenciais)
    return ds_email


def desconectar(login):
    try:
        arquivoToken(login).unlink()
    except OSError:
        pass


def emailConectado(login):
    """E-mail do Gmail conectado a este usuário do portal (None se não conectou)."""
    try:
        dict_token = lerToken(login)
    except Exception:  # noqa: BLE001  (token ilegível = como se não tivesse conectado)
        return None
    return dict_token["email"] if dict_token else None


def obterCredenciais(login):
    """Credenciais Google do usuário, renovadas se preciso (servem para Gmail e Drive).
    Levanta GmailNaoConectadoErro se não houver autorização válida ou se faltar algum escopo."""
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    dict_token = lerToken(login)
    if not dict_token:
        raise GmailNaoConectadoErro(login)
    if not set(LISTA_ESCOPOS) <= set(dict_token["credenciais"].get("scopes") or []):  # conectou antes de um escopo novo: reconectar
        raise GmailNaoConectadoErro(login)
    dt_conectado = datetime.fromisoformat(dict_token["conectado_em"]) if dict_token.get("conectado_em") else datetime.min
    if datetime.now() - dt_conectado > timedelta(hours=horasSessaoGoogle()):  # passou o prazo: apaga o token e pede novo login
        desconectar(login)
        raise GmailNaoConectadoErro(login)
    try:
        credenciais = Credentials.from_authorized_user_info(dict_token["credenciais"], LISTA_ESCOPOS)
        if not credenciais.valid:
            credenciais.refresh(Request())
            salvarToken(login, dict_token["email"], credenciais, dt_conectado)
    except RefreshError as erro:  # acesso revogado ou senha trocada
        desconectar(login)
        raise GmailNaoConectadoErro(login) from erro
    return credenciais


def obterServico(login):
    """Cliente da API do Gmail do usuário. Levanta GmailNaoConectadoErro se não houver autorização válida."""
    from googleapiclient.discovery import build

    servico = build("gmail", "v1", credentials=obterCredenciais(login), cache_discovery=False)
    servico.login_portal = login  # identifica a conta no cache de mensagens (buscarMensagens)
    return servico


# ==========================================
# ENVIO
# ==========================================
def listarEnderecos(ds_lista):
    """Endereços de uma lista tipo "Nome <a@b.com>; c@d.com" (separa por ; ou ,)."""
    return [endereco for _, endereco in getaddresses([parte for parte in re.split(r"[;,]", ds_lista or "") if parte.strip()]) if endereco]


def montarMime(ds_para, ds_assunto, ds_html, ds_copia="", lista_imagens=None, lista_imagens_bytes=None, ds_texto_puro=None):
    """E-mail HTML. `lista_imagens` = [(cid, arquivo)] e `lista_imagens_bytes` = [(cid, bytes, subtipo)] embutidas no corpo
    (ex.: logos da assinatura, imagem do e-mail). `ds_texto_puro` é a versão em texto simples (padrão: um aviso)."""
    mensagem = EmailMessage()
    if listarEnderecos(ds_para):
        mensagem["To"] = ", ".join(listarEnderecos(ds_para))
    if ds_copia:
        mensagem["Cc"] = ", ".join(listarEnderecos(ds_copia))
    mensagem["Subject"] = ds_assunto
    mensagem.set_content(ds_texto_puro or "Este e-mail está em HTML. Abra em um leitor que exiba HTML.")
    mensagem.add_alternative(ds_html, subtype="html")
    for ds_cid, arquivo in lista_imagens or []:
        ds_tipo = {"png": "png", "gif": "gif", "bmp": "bmp"}.get(Path(arquivo).suffix.lower().lstrip("."), "jpeg")
        mensagem.get_payload()[1].add_related(Path(arquivo).read_bytes(), "image", ds_tipo, cid=f"<{ds_cid}>")
    for ds_cid, conteudo, ds_tipo in lista_imagens_bytes or []:
        mensagem.get_payload()[1].add_related(conteudo, "image", ds_tipo, cid=f"<{ds_cid}>")
    return mensagem


def montarMimeTexto(ds_para, ds_assunto, ds_texto, ds_copia="", lista_arquivos=None, ic_urgente=False):
    """E-mail em texto simples, com anexos opcionais (`lista_arquivos` = [Path]) e marca de alta importância."""
    mensagem = EmailMessage()
    if listarEnderecos(ds_para):
        mensagem["To"] = ", ".join(listarEnderecos(ds_para))
    if listarEnderecos(ds_copia):
        mensagem["Cc"] = ", ".join(listarEnderecos(ds_copia))
    mensagem["Subject"] = ds_assunto
    if ic_urgente:
        mensagem["Importance"] = "high"
        mensagem["X-Priority"] = "1"
    mensagem.set_content(ds_texto)
    for arquivo in lista_arquivos or []:
        ds_tipo, _ = mimetypes.guess_type(str(arquivo))
        ds_principal, _, ds_sub = (ds_tipo or "application/octet-stream").partition("/")
        mensagem.add_attachment(Path(arquivo).read_bytes(), maintype=ds_principal, subtype=ds_sub, filename=Path(arquivo).name)
    return mensagem


def codificarMensagem(mensagem):
    return base64.urlsafe_b64encode(mensagem.as_bytes()).decode()


def criarRascunho(servico, mensagem):
    """Cria o rascunho (não envia) e devolve o link para abri-lo no Gmail."""
    dict_rascunho = servico.users().drafts().create(userId="me", body={"message": {"raw": codificarMensagem(mensagem)}}).execute()
    return f"https://mail.google.com/mail/u/0/#drafts?compose={dict_rascunho['message']['id']}"


def enviarEmail(servico, mensagem):
    servico.users().messages().send(userId="me", body={"raw": codificarMensagem(mensagem)}).execute()


def assinaturaHtml(servico):
    """Assinatura configurada no Gmail para o endereço principal ('' se não houver)."""
    try:
        for dict_envio in servico.users().settings().sendAs().list(userId="me").execute().get("sendAs", []):
            if dict_envio.get("isPrimary"):
                return dict_envio.get("signature", "") or ""
    except Exception:  # noqa: BLE001  (sem assinatura, o e-mail sai sem ela)
        pass
    return ""


# ==========================================
# LEITURA
# ==========================================
def _cabecalho(dict_conteudo, nm_cabecalho):
    for dict_item in dict_conteudo.get("headers", []):
        if dict_item["name"].lower() == nm_cabecalho.lower():
            return dict_item["value"]
    return ""


def _decodificar(ds_dados):
    return base64.urlsafe_b64decode(ds_dados + "=" * (-len(ds_dados) % 4)).decode("utf-8", errors="replace")


def _varrerPartes(lista_partes, lista_anexos, lista_textos, lista_htmls):
    for parte in lista_partes:
        if parte.get("parts"):
            _varrerPartes(parte["parts"], lista_anexos, lista_textos, lista_htmls)
        dict_corpo = parte.get("body", {})
        if parte.get("filename") and dict_corpo.get("attachmentId"):
            ds_cid = _cabecalho(parte, "Content-ID").strip().strip("<>")
            ic_embutido = bool(ds_cid) and _cabecalho(parte, "Content-Disposition").lower().startswith("inline")
            lista_anexos.append(Anexo(dict_corpo["attachmentId"], parte["filename"], int(dict_corpo.get("size", 0)), ic_embutido, ds_cid))
        elif parte.get("mimeType") == "text/plain" and dict_corpo.get("data"):
            lista_textos.append(_decodificar(dict_corpo["data"]))
        elif parte.get("mimeType") == "text/html" and dict_corpo.get("data"):
            lista_htmls.append(_decodificar(dict_corpo["data"]))


def _converterMensagem(dict_bruta):
    dict_conteudo = dict_bruta.get("payload", {})
    nm_remetente, ds_remetente = (getaddresses([_cabecalho(dict_conteudo, "From")]) or [("", "")])[0]
    lista_anexos, lista_textos, lista_htmls = [], [], []
    _varrerPartes([dict_conteudo], lista_anexos, lista_textos, lista_htmls)
    mensagem = Mensagem(dict_bruta["id"])
    mensagem.corpo_html = "\n".join(lista_htmls)
    mensagem.id_conversa = dict_bruta.get("threadId", "")
    mensagem.rotulos = set(dict_bruta.get("labelIds", []))
    mensagem.assunto = _cabecalho(dict_conteudo, "Subject")
    mensagem.remetente = ds_remetente.lower()
    mensagem.nome_remetente = nm_remetente
    mensagem.para = {endereco.lower() for _, endereco in getaddresses([_cabecalho(dict_conteudo, "To")]) if endereco}
    mensagem.quando = datetime.fromtimestamp(int(dict_bruta["internalDate"]) / 1000)
    mensagem.corpo = "\n".join(lista_textos)
    mensagem.anexos = lista_anexos
    return mensagem


TENTATIVAS_API = 5  # o Gmail limita as consultas por minuto: em caso de limite, repete com espera crescente
MAX_MENSAGENS_EM_CACHE = 2000
dict_mensagens_em_cache = OrderedDict()  # (conta, id da mensagem) -> Mensagem; o conteúdo de uma mensagem recebida não muda
trava_cache_mensagens = threading.Lock()


def buscarMensagens(servico, ds_consulta, vl_limite=500):
    """Mensagens que casam com a busca do Gmail (ex.: 'in:sent subject:extrato after:1700000000'), da mais nova para a mais antiga.
    Use sempre uma busca bem específica: cada mensagem é baixada por inteiro (e conta na cota do Gmail). As já baixadas ficam em
    memória, então conferências seguintes só baixam as novas."""
    lista_ids, ds_pagina = [], None
    while len(lista_ids) < vl_limite:
        dict_resposta = servico.users().messages().list(
            userId="me", q=ds_consulta, pageToken=ds_pagina, maxResults=min(100, vl_limite - len(lista_ids))).execute(num_retries=TENTATIVAS_API)
        lista_ids += [dict_item["id"] for dict_item in dict_resposta.get("messages", [])]
        ds_pagina = dict_resposta.get("nextPageToken")
        if not ds_pagina:
            break
    ds_conta = getattr(servico, "login_portal", "")
    lista_mensagens = []
    for id_mensagem in lista_ids:
        with trava_cache_mensagens:
            mensagem = dict_mensagens_em_cache.get((ds_conta, id_mensagem))
        if mensagem is None:
            dict_bruta = servico.users().messages().get(userId="me", id=id_mensagem, format="full").execute(num_retries=TENTATIVAS_API)
            mensagem = _converterMensagem(dict_bruta)
            with trava_cache_mensagens:
                dict_mensagens_em_cache[(ds_conta, id_mensagem)] = mensagem
                while len(dict_mensagens_em_cache) > MAX_MENSAGENS_EM_CACHE:
                    dict_mensagens_em_cache.popitem(last=False)
        lista_mensagens.append(mensagem)
    return lista_mensagens


def listarRascunhos(servico):
    """Destinatários e assunto dos rascunhos (equivale à Caixa de Saída do Outlook)."""
    lista_saida = []
    for dict_rascunho in servico.users().drafts().list(userId="me", maxResults=100).execute().get("drafts", []):
        dict_mensagem = servico.users().drafts().get(userId="me", id=dict_rascunho["id"], format="metadata").execute()["message"]
        dict_conteudo = dict_mensagem.get("payload", {})
        mensagem = Mensagem(dict_mensagem["id"])
        mensagem.assunto = _cabecalho(dict_conteudo, "Subject")
        mensagem.para = {endereco.lower() for _, endereco in getaddresses([_cabecalho(dict_conteudo, "To")]) if endereco}
        lista_saida.append(mensagem)
    return lista_saida


def mensagensDaConversa(servico, id_conversa):
    """Mensagens de uma conversa (o e-mail enviado e as respostas), da mais antiga para a mais nova."""
    dict_conversa = servico.users().threads().get(userId="me", id=id_conversa, format="full").execute()
    return [_converterMensagem(dict_mensagem) for dict_mensagem in dict_conversa.get("messages", [])]


def baixarAnexo(servico, id_mensagem, id_anexo):
    ds_dados = servico.users().messages().attachments().get(userId="me", messageId=id_mensagem, id=id_anexo).execute()["data"]
    return base64.urlsafe_b64decode(ds_dados + "=" * (-len(ds_dados) % 4))


def segundosEpoch(dt_referencia):
    """Segundos desde 1970 de um horário local (para o filtro `after:` do Gmail)."""
    return int(dt_referencia.timestamp())


# ==========================================
# INTERFACE (Streamlit)
# ==========================================
def tratarRetornoGoogle(login):
    """Chamar no main.py, depois do login do portal: se o Google acabou de devolver a pessoa com ?code=, conclui a conexão."""
    dict_consulta = st.query_params
    if "code" in dict_consulta and "state" in dict_consulta:
        try:
            concluirLogin(login, dict_consulta["code"], dict_consulta["state"])
            st.session_state.pop("gmail_erro", None)
        except Exception as erro:  # noqa: BLE001
            st.session_state["gmail_erro"] = f"Não foi possível conectar à conta Google: {erro}"
        st.query_params.clear()
    elif "error" in dict_consulta:
        st.session_state["gmail_erro"] = "A conexão com a conta Google foi cancelada."
        st.query_params.clear()


def servicoDaSessao():
    """Cliente do Gmail do usuário logado no portal; GmailNaoConectadoErro se ainda não conectou ou se a conexão expirou."""
    dict_usuario = controle_acesso.usuarioAtual()
    if not dict_usuario:
        raise GmailNaoConectadoErro("")
    return obterServico(dict_usuario["usuario"])


def contaConectada(login):
    """E-mail da conta Google conectada e ainda válida (None se não conectou, expirou ou foi revogada)."""
    ds_email = emailConectado(login)
    if not ds_email:
        return None
    try:
        obterCredenciais(login)
    except GmailNaoConectadoErro:
        return None
    except Exception:  # noqa: BLE001  (falha de rede ao renovar não derruba o portal)
        pass
    return ds_email


def emailDaSessao():
    """E-mail da conta Google conectada pelo usuário logado no portal (None se não conectou ou expirou)."""
    dict_usuario = controle_acesso.usuarioAtual()
    return contaConectada(dict_usuario["usuario"]) if dict_usuario else None


def exigirConexaoGoogle(login):
    """Chamar no main.py logo depois do login do portal. Sem conexão válida com o Google (Gmail e Drive), mostra a tela
    de conexão e interrompe a página. A conexão vale `horasSessaoGoogle()` horas; depois disso a pessoa conecta de novo.
    Devolve o e-mail da conta conectada, ou None se a pessoa escolheu continuar sem conectar."""
    if st.session_state.get("google_pular"):
        return contaConectada(login)
    ds_email = contaConectada(login)
    if ds_email:
        return ds_email

    nr_horas = f"{horasSessaoGoogle():g}"
    centro = controle_acesso.molduraPainel("Conecte a sua conta Google")
    with centro, st.container(key="login_card"):
        st.markdown('<p class="secao">Conectar à conta Google</p>', unsafe_allow_html=True)
        st.markdown(
            '<p class="secao-sub">Uma autorização única dá ao portal acesso a:</p>'
            "<ul style='margin:0 0 .8rem 1.1rem;padding:0;line-height:1.7'>"
            "<li><b>Gmail</b>: montar rascunhos e conferir envios e respostas</li>"
            "<li><b>Drive</b>: ler e gravar arquivos nas pastas do trabalho</li></ul>",
            unsafe_allow_html=True,
        )
        if st.session_state.get("gmail_erro"):
            st.error(st.session_state.pop("gmail_erro"))
        try:
            st.link_button("Conectar à conta Google", urlDeLogin(login), type="primary", use_container_width=True)
        except Exception as erro:  # noqa: BLE001
            st.error(f"Não foi possível iniciar a conexão com o Google: {erro}")
        st.markdown(
            "<style>"
            f".st-key-google_pular_botao button {{ background: #fff !important; border: 1px solid {COR['vinho']} !important; }}"
            f".st-key-google_pular_botao button * {{ color: {COR['vinho']} !important; font-weight: 600; }}"
            f".st-key-google_pular_botao button:hover {{ background: {COR['vinho_claro']} !important; box-shadow: none !important; }}"
            "</style>",
            unsafe_allow_html=True,
        )
        if st.button("Continuar sem conectar", key="google_pular_botao", use_container_width=True):
            st.session_state["google_pular"] = True
            st.rerun()
        st.markdown(
            f'<p class="login-rodape">A conexão vale {nr_horas} horas; depois é preciso conectar de novo. '
            "O portal não guarda a sua senha do Google.<br>Sem conectar, as telas que usam Gmail ou Drive não funcionam; "
            "depois, use \"Conectar ao Google\" na lateral.</p>",
            unsafe_allow_html=True,
        )
    st.stop()


def blocoGoogleSidebar(login):
    """Mostra na lateral qual conta Google está conectada (com o botão Desconectar) ou o botão para conectar."""
    ds_email = contaConectada(login)
    if not ds_email:
        if st.sidebar.button("Conectar ao Google", key="google_conectar_depois"):
            st.session_state.pop("google_pular", None)
            st.rerun()
        return
    # HTML em vez de caption: o markdown transforma o e-mail em link azul
    st.sidebar.markdown(
        f'<div style="font-size:.78rem;line-height:1.35;opacity:.85;word-break:break-all;margin-bottom:.3rem">'
        f'<b>Google conectado:</b><br>{html.escape(ds_email)}</div>',
        unsafe_allow_html=True,
    )
    if st.sidebar.button("Desconectar do Google", key="google_desconectar"):
        desconectar(login)
        st.session_state.pop("google_pular", None)
        st.rerun()
