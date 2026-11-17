"""Login do Portal TAG: usuários e senhas próprios, gerenciados por um administrador dentro do portal.

- As contas, sessões e vínculos de computador ficam no banco MySQL (tabelas portal_tb_usuario, portal_tb_sessao, portal_tb_dispositivo;
  conexão em app/database/db.py, variáveis BANCO_BKO_*).
- Senhas nunca são guardadas: só o hash PBKDF2-SHA256 com sal individual e "pimenta" (PORTAL_SEGREDO: variável do SO,
  Parameter Store ou env/.env.segredo, que fica fora do git).
- No primeiro acesso (sem nenhum usuário) o portal pede a criação do administrador.
- Login persistente: ao entrar, o navegador recebe um cookie com um token aleatório; no servidor fica só o hash do
  token (tabela portal_tb_sessao). Ao recarregar a página o token é validado e a pessoa continua logada, até a sessão expirar,
  a pessoa clicar em Sair, trocar a senha ou o administrador desativá-la.
- Uso no main.py (ponto de entrada de todas as páginas):  usuario = controle_acesso.exigir_login()
"""
import base64
import hashlib
import hmac
import html
import inspect
import ipaddress
import json
import os
import re
import secrets
import socket
import threading
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from app.ambiente.config_ambiente import diretorio_base
from app.database import seguranca as banco_seguranca
from app.seguranca import autenticador
from app.seguranca.registro_acessos import registrarEvento
from app.utilitarias.tema import COR, _logoBase64, topo
from app.utilitarias.versoes import rotulo

ARQ_ENV = diretorio_base / "env" / ".env.segredo"


def _envInt(nome, padrao):
    try:
        return max(1, int(os.environ.get(nome, padrao)))
    except ValueError:
        return padrao


COOKIE ="portal_tag_sessao"
COOKIE_DISP = "portal_tag_disp"  # identifica este navegador/computador (longa duração, aleatório)

ITERACOES = 240_000
SENHA_MIN = 10
SENHAS_FRACAS = {"senha", "password", "passw0rd", "admin", "administrador", "portal", "portaltag", "tag", "taginvest",
                 "qwerty", "qwertyuiop", "abcdefghij", "mudar", "trocar", "bemvindo", "temporaria", "changeme", "letmein"}
trava_usuarios = threading.Lock()  # login e gravação das contas nunca se misturam (evita desfazer uma desativação)
MAX_FALHAS = _envInt("PORTAL_MAX_FALHAS", 5)          # erros seguidos de senha antes de bloquear o usuário
BLOQUEIO_MIN = _envInt("PORTAL_BLOQUEIO_MIN", 5)        # minutos de bloqueio
SESSAO_MIN = _envInt("PORTAL_SESSAO_MIN", 30)       # a cada tanto tempo o portal pergunta se a pessoa ainda está ativa
GRACA_SEG = _envInt("PORTAL_GRACA_SEG", 10)         # segundos para responder; sem resposta, desloga
PERFIS = ["usuario", "admin"]
# Apps/telas que podem ser liberados por usuário (chave de home.FERRAMENTAS -> nome). Administrador vê todos.
APPS_PORTAL = {
    "extratos": "Solicitação de extratos", "boletas": "Mesa de Boletas", "solicitacoes": "Registro de Solicitações",
    "processos_externos": "Registro Solicitações de Fechamento", "rentabilidade": "Rentabilidade e Cotas",
    "bradesco": "Transactions Offshore", "caixa": "Conciliação de Caixa", "crava_cotas": "Crava Cotas",
}
ROTULO_PERFIL = {"usuario": "Usuário", "admin": "Administrador"}
CHAVE_SESSAO = "auth"


# ---------------------------------------------------------------- armazenamento
def agora():
    return datetime.now().replace(microsecond=0)


class ErroArquivoUsuarios(Exception):
    """O cadastro de usuários (banco de dados) não pôde ser lido: o portal para em vez de tratar como "sem contas"."""


def carregarUsuarios():
    """Contas cadastradas (tabela portal_tb_usuario). Tabela vazia = primeiro acesso. Falha do banco NUNCA vira lista vazia: senão
    qualquer visitante veria "Criar administrador" e criaria uma conta de administrador."""
    try:
        return banco_seguranca.carregarUsuarios()
    except Exception as erro:  # noqa: BLE001  (qualquer falha de banco bloqueia o portal)
        raise ErroArquivoUsuarios(str(erro)) from erro


def salvarUsuarios(usuarios):
    banco_seguranca.salvarUsuarios(usuarios)  # uma transação: ou grava tudo ou nada


def buscar(usuarios, login):
    login = (login or "").strip().lower()
    return next((usuario for usuario in usuarios if usuario["usuario"] == login), None)


# ---------------------------------------------------------------- segredo (.env)
_SEGREDO = None


def segredo():
    """Segredo do servidor (PORTAL_SEGREDO no .env): "pimenta" das senhas e chave dos tokens de sessão.

    Se não existir e ainda não há conta protegida por ele, gera um e grava no .env. Se já há contas protegidas e o segredo
    sumiu, interrompe com aviso: gerar outro travaria todo mundo para fora.
    """
    global _SEGREDO
    if _SEGREDO:
        return _SEGREDO
    valor = os.environ.get("PORTAL_SEGREDO", "").strip()
    if len(valor) < 32:
        if any(usuario.get("pimenta") for usuario in carregarUsuarios()):
            st.error("PORTAL_SEGREDO não encontrado no arquivo .env do portal. Restaure o .env (backup) e reinicie o portal.")
            st.stop()
        valor = secrets.token_hex(32)
        quebra = "\n" if ARQ_ENV.exists() and ARQ_ENV.stat().st_size else ""
        with ARQ_ENV.open("a", encoding="utf-8") as arquivo_env:
            arquivo_env.write(f"{quebra}PORTAL_SEGREDO={valor}\n")
        try:
            os.chmod(ARQ_ENV, 0o600)
        except OSError:
            pass
        os.environ["PORTAL_SEGREDO"] = valor
    _SEGREDO = valor.encode("utf-8")
    return _SEGREDO


# ---------------------------------------------------------------- senhas
def _material(senha, pimenta):
    """Com pimenta, a senha passa antes por HMAC com o segredo do .env: só o hash do usuarios.json não basta para quebrar."""
    if pimenta:
        return hmac.new(segredo(), senha.encode("utf-8"), hashlib.sha256).digest()
    return senha.encode("utf-8")


def gerarHash(senha, salt=None, iteracoes=ITERACOES):
    salt = salt or secrets.token_bytes(16)
    hash_senha = hashlib.pbkdf2_hmac("sha256", _material(senha, True), salt, iteracoes)
    return {"salt": salt.hex(), "hash": hash_senha.hex(), "iteracoes": iteracoes, "pimenta": True}


def senhaConfere(senha, usuario):
    hash_calculado = hashlib.pbkdf2_hmac("sha256", _material(senha, bool(usuario.get("pimenta"))), bytes.fromhex(usuario["salt"]),
                            usuario.get("iteracoes", ITERACOES))
    return hmac.compare_digest(hash_calculado.hex(), usuario["hash"])


def validarSenha(senha, confirmacao):
    """Retorna a mensagem de erro, ou None se a senha é aceitável."""
    if len(senha) < SENHA_MIN:
        return f"A senha precisa ter pelo menos {SENHA_MIN} caracteres."
    if senha.lower() == senha or senha.upper() == senha or not any(caractere.isdigit() for caractere in senha):
        return "Use letras maiúsculas e minúsculas e pelo menos um número."
    if re.sub(r"\d+$", "", senha.lower()) in SENHAS_FRACAS:
        return "Essa senha é muito comum. Escolha outra."
    if senha != confirmacao:
        return "A confirmação não é igual à senha."
    return None


def senhaTemporaria():
    alfabeto = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
    while True:
        senha = "".join(secrets.choice(alfabeto) for _ in range(10))
        if validarSenha(senha, senha) is None:
            return senha


def appsPermitidos(usuario, todos):
    """Chaves de apps que o usuário vê. Administrador vê tudo; usuário sem o campo `apps` (conta antiga) também."""
    if usuario.get("perfil") == "admin" or usuario.get("apps") is None:
        return list(todos)
    return [app for app in todos if app in usuario["apps"]]


def novoUsuario(login, nome, perfil, senha, trocar_senha, apps=None):
    return {
        "usuario": login.strip().lower(), "nome": " ".join(nome.split()), "perfil": perfil, "ativo": True, "apps": apps,
        **gerarHash(senha), "trocar_senha": trocar_senha, "falhas": 0, "bloqueado_ate": None,
        "criado_em": agora().isoformat(sep=" "), "ultimo_acesso": None,
    }


# ---------------------------------------------------------------- tokens de sessão (login persistente)
def _hashToken(token):
    return hmac.new(segredo(), token.encode("utf-8"), hashlib.sha256).hexdigest()


def criarToken(login):
    """Gera o token do navegador. Só o hash dele é guardado (tabela portal_tb_sessao)."""
    token = secrets.token_urlsafe(32)
    banco_seguranca.criarSessao(
        _hashToken(token), login, agora().isoformat(),
        (agora() + timedelta(minutes=SESSAO_MIN, seconds=GRACA_SEG)).isoformat())
    return token


def tokenAtivo(token):
    """True se o token desta sessão ainda existe no servidor (troca de senha, desativação e logout o removem)."""
    if not token:
        return False
    sessao = banco_seguranca.buscarSessao(_hashToken(token))
    return bool(sessao and sessao["expira_em"] > agora().isoformat())


def usuarioDoToken(token):
    """Valida o token do cookie. Retorna (usuário, início da sessão, ativo até) ou None se inválido/expirado/usuário inativo."""
    if not token:
        return None
    reg = banco_seguranca.buscarSessao(_hashToken(token))
    if reg is None or reg["expira_em"] <= agora().isoformat():
        return None
    usuario = buscar(carregarUsuarios(), reg["usuario"])
    if usuario is None or not usuario.get("ativo", True):
        return None
    ativo_ate = (datetime.fromisoformat(reg["expira_em"]) - timedelta(seconds=GRACA_SEG)).isoformat()
    return usuario, reg["criado_em"], ativo_ate


def revogarToken(token):
    if token:
        banco_seguranca.removerSessao(_hashToken(token))


def revogarSessoes(login):
    """Derruba todos os navegadores logados desse usuário (troca de senha, desativação, mudança de perfil)."""
    banco_seguranca.removerSessoesUsuario(login)


def _cookieDoNavegador():
    try:
        valor = st.context.cookies.get(COOKIE)
        return valor if isinstance(valor, str) and valor else None
    except Exception:  # noqa: BLE001  (versões antigas do Streamlit ou execução sem navegador)
        return None


def _emitirCookie():
    """Grava ou apaga o cookie no navegador (JavaScript num iframe do mesmo domínio), se houver algo pendente."""
    gravar = st.session_state.pop("_cookie_gravar", None)
    apagar = st.session_state.pop("_cookie_apagar", False)
    disp = st.session_state.pop("_disp_gravar", None)
    valores = []
    if gravar:
        valores.append(f"{COOKIE}={gravar}; path=/; max-age={SESSAO_MIN * 60 + GRACA_SEG}; SameSite=Strict")
    elif apagar:
        valores.append(f"{COOKIE}=; path=/; max-age=0; SameSite=Strict")
    if disp:
        valores.append(f"{COOKIE_DISP}={disp}; path=/; max-age={365 * 86400}; SameSite=Strict")  # não some ao sair
    if not valores:
        return
    seguro = json.dumps(os.environ.get("PORTAL_COOKIE_SECURE") == "1")
    js = (f"<script>for(const v of {json.dumps(valores)}){{const c=v+((window.parent.location.protocol==='https:'||{seguro})?'; Secure':'');"
          "try{window.parent.document.cookie=c}catch(e){document.cookie=c}}</script>")
    with st.container(key="cookie_js"):
        st.markdown('<style>[class*="st-key-cookie_js"]{position:absolute;width:0;height:0;overflow:hidden;margin:0;padding:0}</style>',
                    unsafe_allow_html=True)
        if hasattr(st, "iframe"):  # API nova; components.v1.html está sendo descontinuado
            st.iframe(js, height=1)
        else:
            components.html(js, height=0)


# ---------------------------------------------------------------- sessão
def usuarioAtual():
    sessao = st.session_state.get(CHAVE_SESSAO)
    if not sessao:
        return None
    limite = datetime.fromisoformat(sessao["ativo_ate"]) + timedelta(seconds=GRACA_SEG)
    if agora() > limite:  # passou o prazo e a pessoa não confirmou que está ativa
        registrarEvento("sessao_expirada", sessao["usuario"], "prazo vencido sem confirmação")
        st.session_state.pop(CHAVE_SESSAO, None)
        return None
    return sessao


def _abrirSessao(usuario, token=None, desde=None, ativo_ate=None):
    """Abre a sessão. Sem `token` (login novo) gera um e agenda a gravação do cookie; com `token` (restaurada do cookie) só reaproveita."""
    if token is None:
        token = criarToken(usuario["usuario"])
        st.session_state["_cookie_gravar"] = token
    st.session_state["_token"] = token
    st.session_state[CHAVE_SESSAO] = {
        "usuario": usuario["usuario"], "nome": usuario["nome"], "perfil": usuario["perfil"],
        "trocar_senha": usuario.get("trocar_senha", False), "apps": usuario.get("apps"), "desde": desde or agora().isoformat(),
        "ativo_ate": ativo_ate or (agora() + timedelta(minutes=SESSAO_MIN)).isoformat(),
    }


def _encerrarSessao():
    """Esquece a sessão neste navegador: revoga o token no servidor e agenda a limpeza do cookie."""
    revogarToken(st.session_state.pop("_token", None))
    revogarToken(_cookieDoNavegador())
    st.session_state.pop(CHAVE_SESSAO, None)
    st.session_state.pop("_cookie_gravar", None)
    st.session_state.pop("senha_gerada_novo", None)  # senha temporária nunca sobrevive ao logout
    st.session_state["_cookie_apagar"] = True


def sair():
    sessao = st.session_state.get(CHAVE_SESSAO) or {}
    registrarEvento("logout", sessao.get("usuario", ""))
    _encerrarSessao()
    st.rerun()


def autenticar(login, senha, disp=None):
    """Valida usuário e senha. Retorna (usuário, '') se entrou, ou (None, mensagem)."""
    with trava_usuarios:
        return _autenticarSemTrava(login, senha, disp)


def _autenticarSemTrava(login, senha, disp=None):
    login, senha = (login or "")[:100], (senha or "")[:256]  # limita o tamanho: evita gastar CPU com entradas gigantes
    usuarios = carregarUsuarios()
    usuario = buscar(usuarios, login)
    generica = f"Usuário ou senha incorretos. Se errou várias vezes, aguarde alguns minutos ou fale com um administrador."
    ds_ip, nm_computador = (disp or {}).get("ip", ""), (disp or {}).get("host", "")
    if usuario is None:
        gerarHash(senha or "x")  # gasta o mesmo tempo, para não revelar quais usuários existem
        registrarEvento("login_falha", "", "usuário inexistente", ds_ip, nm_computador)
        return None, generica
    bloqueio = usuario.get("bloqueado_ate")
    if bloqueio and datetime.fromisoformat(bloqueio) > agora():
        gerarHash(senha or "x")  # mesmo tempo de resposta de uma tentativa normal
        registrarEvento("login_falha", usuario["usuario"], "conta bloqueada por tentativas", ds_ip, nm_computador)
        return None, generica
    if not senhaConfere(senha or "", usuario):
        usuario["falhas"] = usuario.get("falhas", 0) + 1
        if usuario["falhas"] >= MAX_FALHAS:
            usuario["bloqueios"] = usuario.get("bloqueios", 0) + 1  # cada bloqueio seguido dobra a espera (máx. 32x)
            nr_minutos = BLOQUEIO_MIN * 2 ** min(usuario["bloqueios"] - 1, 5)
            usuario["bloqueado_ate"] = (agora() + timedelta(minutes=nr_minutos)).isoformat()
            usuario["falhas"] = 0
            registrarEvento("login_bloqueado", usuario["usuario"], f"{MAX_FALHAS} erros seguidos de senha ({nr_minutos} min)", ds_ip, nm_computador)
        else:
            registrarEvento("login_falha", usuario["usuario"], "senha incorreta", ds_ip, nm_computador)
        salvarUsuarios(usuarios)
        return None, generica
    if not usuario.get("ativo", True):
        registrarEvento("login_falha", usuario["usuario"], "usuário desativado", ds_ip, nm_computador)
        return None, "Este usuário está desativado. Fale com um administrador."
    if usuario["perfil"] != "admin":
        if usuario.get("bloqueio_dispositivo"):
            registrarEvento("login_falha", usuario["usuario"], "conta bloqueada por uso em 2 contas no mesmo computador", ds_ip, nm_computador)
            return None, MSG_BLOQUEIO_DISPOSITIVO
        if disp and (texto_mensagem := _checarDispositivo(usuario, usuarios, disp)):
            salvarUsuarios(usuarios)
            registrarEvento("bloqueio_dispositivo", usuario["usuario"], ", ".join(usuario["bloqueio_dispositivo"]["com"]) + " no mesmo computador", ds_ip, nm_computador)
            return None, texto_mensagem
    usuario["falhas"], usuario["bloqueado_ate"], usuario["ultimo_acesso"] = 0, None, agora().isoformat(sep=" ")
    usuario["bloqueios"] = 0
    if not usuario.get("pimenta"):
        usuario.update(gerarHash(senha))  # conta antiga: regrava o hash já protegido pelo segredo do .env
    salvarUsuarios(usuarios)
    registrarEvento("login", usuario["usuario"], "", ds_ip, nm_computador)
    return usuario, ""


# ---------------------------------------------------------------- confirmação de presença (a cada SESSAO_MIN)
def renovarSessao():
    """A pessoa confirmou que está ativa: estende a sessão e o token por mais SESSAO_MIN minutos."""
    if not tokenAtivo(st.session_state.get("_token")):  # sessão derrubada (ex.: senha trocada em outro lugar): não renova
        _encerrarSessao()
        return
    registrarEvento("sessao_renovada", (st.session_state.get(CHAVE_SESSAO) or {}).get("usuario", ""))
    token = st.session_state.get("_token")
    novo_fim = agora() + timedelta(minutes=SESSAO_MIN)
    if token:
        banco_seguranca.renovarSessaoBanco(_hashToken(token), (novo_fim + timedelta(seconds=GRACA_SEG)).isoformat())
        st.session_state["_cookie_gravar"] = token  # renova também o prazo do cookie no navegador
    st.session_state[CHAVE_SESSAO]["ativo_ate"] = novo_fim.isoformat()
    st.session_state["_dlg_presenca"] = False


def _segundosParaResponder():
    sessao = st.session_state.get(CHAVE_SESSAO)
    if not sessao:
        return 0
    passou = (agora() - datetime.fromisoformat(sessao["ativo_ate"])).total_seconds()
    return GRACA_SEG - passou


# `dismissible` (impedir fechar clicando fora) só existe em versões novas do Streamlit; sem ele, o servidor encerra a sessão igual
_ARGS_DIALOGO = {"dismissible": False} if "dismissible" in inspect.signature(st.dialog).parameters else {}


@st.dialog("Você ainda está aí?", **_ARGS_DIALOGO)
def _dialogoPresenca():
    @st.fragment(run_every="1s")
    def contagem():
        faltam = _segundosParaResponder()
        if faltam <= 0:
            st.session_state["_dlg_presenca"] = False
            registrarEvento("sessao_expirada", (st.session_state.get(CHAVE_SESSAO) or {}).get("usuario", ""), "sem resposta ao aviso de presença")
            _encerrarSessao()
            st.rerun(scope="app")
        st.markdown(f"Por segurança, sua sessão será encerrada em **{int(faltam) + 1} s** se não houver resposta.")

    contagem()
    if st.button("Sim, continuar conectado", type="primary", use_container_width=True):
        renovarSessao()
        st.rerun()


@st.fragment(run_every="5s")
def _vigia():
    sessao = st.session_state.get(CHAVE_SESSAO)
    if not sessao:
        return
    if st.session_state.get("_dlg_presenca"):
        if _segundosParaResponder() <= 0:  # o aviso foi fechado sem resposta: o prazo vence do mesmo jeito
            st.session_state["_dlg_presenca"] = False
            registrarEvento("sessao_expirada", sessao["usuario"], "sem resposta ao aviso de presença")
            _encerrarSessao()
            st.rerun(scope="app")
        return
    if agora() >= datetime.fromisoformat(sessao["ativo_ate"]):
        st.session_state["_dlg_presenca"] = True
        _dialogoPresenca()


def vigiaSessao():
    """Chame no home.py depois do login: a cada SESSAO_MIN minutos pergunta se a pessoa ainda está ativa."""
    if st.session_state.get("_dlg_presenca"):
        _dialogoPresenca()  # reabre o aviso se a página recarregou enquanto ele estava aberto
    _vigia()


# ---------------------------------------------------------------- dispositivo (duas contas no mesmo computador)
MSG_BLOQUEIO_DISPOSITIVO = ("Conta bloqueada: foram usadas duas contas diferentes neste mesmo computador. "
                            "Apenas um administrador pode desbloquear.")


def _nomeDoComputador(ip):
    """Nome do computador do IP (DNS reverso, ex.: TAG83), com limite de 2 s. Vazio se não resolver."""
    if not ip:
        return ""
    resultado = []

    def consulta():
        try:
            resultado.append(socket.gethostbyaddr(ip)[0].split(".")[0].upper())
        except OSError:
            pass

    thread_consulta = threading.Thread(target=consulta, daemon=True)
    thread_consulta.start()
    thread_consulta.join(2)
    return resultado[0] if resultado else ""


def _ipDoCliente():
    """IP de quem acessa. `st.context.ip_address` só existe em versões novas; antes disso lê da conexão do servidor."""
    def validar(ds_ip):
        try:
            return str(ipaddress.ip_address(ds_ip)) if isinstance(ds_ip, str) else ""
        except ValueError:
            return ""

    try:
        ds_ip = validar(st.context.ip_address)
        if ds_ip:
            return ds_ip
    except Exception:  # noqa: BLE001
        pass
    try:
        from streamlit.runtime import Runtime
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        cliente = Runtime.instance().get_client(get_script_run_ctx().session_id)
        return validar(cliente.request.remote_ip)
    except Exception:  # noqa: BLE001
        return ""


def identificarDispositivo():
    """Id do navegador (cookie), IP e nome do computador. O servidor não consegue ler o hostname direto do
    navegador, então o nome vem do DNS reverso do IP."""
    try:
        valor = st.context.cookies.get(COOKIE_DISP)
    except Exception:  # noqa: BLE001
        valor = None
    if not (isinstance(valor, str) and re.fullmatch(r"[A-Za-z0-9_-]{20,64}", valor)):
        valor = st.session_state.get("_disp_id") or secrets.token_urlsafe(24)  # navegador novo
    st.session_state["_disp_id"] = valor
    ip = _ipDoCliente()
    return {"id": valor, "ip": ip, "host": _nomeDoComputador(ip)}


def _checarDispositivo(usuario, usuarios, disp):
    """Registra o uso do computador por `u` (não administrador). Se outra conta não administradora já usou o mesmo
    computador (mesmo navegador ou mesmo nome de computador), bloqueia as duas e devolve a mensagem."""
    vinculos = banco_seguranca.listarDispositivos()

    def mesmo(vinculo):
        return vinculo["usuario"] != usuario["usuario"] and (vinculo.get("id") == disp["id"] or (disp["host"] and vinculo.get("host") == disp["host"]))

    outros = sorted({vinculo["usuario"] for vinculo in vinculos if mesmo(vinculo)})
    outros = [login_outro for login_outro in outros if (conta_outra := buscar(usuarios, login_outro)) and conta_outra["perfil"] != "admin"]
    quando = agora().isoformat(sep=" ", timespec="seconds")
    banco_seguranca.registrarDispositivo(usuario["usuario"], disp["id"], disp["ip"], disp["host"], quando)  # insere ou atualiza o vínculo
    st.session_state["_disp_gravar"] = disp["id"]
    if not outros:
        return None
    base = {"em": quando, "host": disp["host"], "ip": disp["ip"]}
    usuario["bloqueio_dispositivo"] = {**base, "com": outros}
    for login_outro in outros:
        conta_outra = buscar(usuarios, login_outro)
        conta_outra["bloqueio_dispositivo"] = {**base, "com": [usuario["usuario"]]}
        revogarSessoes(login_outro)
    return MSG_BLOQUEIO_DISPOSITIVO


def excluirUsuario(usuarios, login):
    """Apaga a conta de vez, derruba as sessões e remove os vínculos de computador dela."""
    usuarios[:] = [usuario for usuario in usuarios if usuario["usuario"] != login]
    salvarUsuarios(usuarios)
    revogarSessoes(login)
    banco_seguranca.removerDispositivosUsuario(login)
    for outra_conta in usuarios:  # quem foi bloqueado por dividir computador com a conta apagada fica livre
        bloqueio = outra_conta.get("bloqueio_dispositivo")
        if bloqueio and login in bloqueio.get("com", []):
            bloqueio["com"] = [com_login for com_login in bloqueio["com"] if com_login != login]
            if not bloqueio["com"]:
                outra_conta.pop("bloqueio_dispositivo")
    salvarUsuarios(usuarios)


def desbloquearDispositivo(alvo):
    """Admin libera a conta e apaga os vínculos dela, para recomeçar do zero."""
    alvo.pop("bloqueio_dispositivo", None)
    registrarEvento("desbloqueio", (st.session_state.get(CHAVE_SESSAO) or {}).get("usuario", ""), f"desbloqueou {alvo['usuario']}")
    banco_seguranca.removerDispositivosUsuario(alvo["usuario"])


# ---------------------------------------------------------------- telas
_CSS_LOGIN = f"""
<style>
/* Tela de login dividida: painel da marca (esquerda) e formulário (direita) */
[class*="st-key-login_wrap"] {{
    background: #fff; border: 1px solid {COR['borda']}; border-radius: 18px; overflow: hidden;
    box-shadow: 0 16px 44px rgba(74, 10, 30, .20);
}}
[class*="st-key-login_wrap"] [data-testid="stHorizontalBlock"] {{ gap: 0; align-items: stretch; }}
[class*="st-key-login_wrap"] [data-testid="stColumn"] {{ padding: 0; }}
[class*="st-key-login_wrap"] [data-testid="stColumn"] > div {{ height: 100%; }}
[class*="st-key-login_wrap"] [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"] {{ flex: 1 1 auto; align-items: stretch; }}
[class*="st-key-login_esq"] {{
    height: 100%; min-height: 470px; padding: 2.6rem 2.3rem; justify-content: center; gap: 0;
    background: linear-gradient(155deg, {COR['vinho_escuro']} 0%, {COR['vinho']} 55%, {COR['vinho_medio']} 100%);
    border-right: 4px solid {COR['dourado']};
}}
.le-logo {{ display: block; width: 240px; max-width: 100%; height: auto; margin: 0 0 1.7rem 0; }}
.le-titulo {{ color: #fff; font-size: 1.75rem; font-weight: 700; letter-spacing: -.01em; line-height: 1.15; margin: 0 0 .45rem; }}
.le-sub {{ color: #E9CFD7; font-size: .98rem; line-height: 1.45; margin: 0; }}
.le-linha {{ width: 56px; height: 3px; background: {COR['dourado']}; margin: 1.5rem 0 1.1rem; border-radius: 2px; }}
.le-versao {{ color: {COR['dourado']}; font-size: .72rem; letter-spacing: .06em; margin: 0; }}
[class*="st-key-login_card"] {{ height: 100%; justify-content: center; padding: 2.4rem 2.4rem 1.7rem; gap: .4rem; }}
[class*="st-key-login_card"] .secao {{ font-size: 1.35rem; margin: 0 0 .35rem; line-height: 1.3; }}
[class*="st-key-login_card"] .secao-sub {{ margin: 0 0 .9rem; line-height: 1.45; }}
[class*="st-key-login_card"] [data-testid="stForm"] {{ margin-top: .6rem; }}
@media (max-width: 640px) {{
    [class*="st-key-login_esq"] {{ min-height: auto; padding: 1.8rem 1.6rem; border-right: none; border-bottom: 4px solid {COR['dourado']}; }}
    [class*="st-key-login_card"] {{ padding: 1.6rem 1.4rem 1.2rem; }}
    .le-logo {{ width: 180px; margin-bottom: 1rem; }}
}}
[data-testid="stFormSubmitButton"] button[kind="primaryFormSubmit"] p {{ color: #fff !important; font-weight: 600; }}
[data-testid="stFormSubmitButton"] button[kind="primaryFormSubmit"]:hover {{ background: {COR['vinho_medio']}; border-color: {COR['vinho_medio']}; }}
[class*="st-key-cookie_js"] {{ position: absolute; width: 0; height: 0; overflow: hidden; margin: 0; padding: 0; }}
.detalhe-conta {{ background: #fff; border: 1px solid {COR['borda']}; border-radius: 12px; padding: .9rem 1.1rem; margin-bottom: 1rem; }}
.detalhe-conta p {{ margin: .15rem 0; }}
.login-rodape {{ color: {COR['texto_suave']}; font-size: .8rem; text-align: center; margin-top: .9rem; }}
</style>
"""

# Esconde o menu lateral enquanto não há login
_CSS_SEM_MENU = """
<style>
html body section[data-testid="stSidebar"], html body [data-testid="stExpandSidebarButton"],
html body [data-testid="stSidebarCollapsedControl"] { display: none !important; }
html body .block-container { max-width: 1020px; padding-top: 9vh; }
@media (max-width: 640px) { html body .block-container { padding-top: 1.5rem; } }
</style>
"""


@st.cache_data(show_spinner=False)
def _logoPortalBase64():
    """Logo do painel de acesso: TAG + "Portal de Automações" (app/assets/logo_portal_automacoes.png)."""
    return base64.b64encode((diretorio_base / "app" / "assets" / "logo_portal_automacoes.png").read_bytes()).decode()


def _moldura(subtitulo):
    """Painel dividido: marca à esquerda (já desenhada aqui); devolve a coluna da direita para o formulário."""
    st.markdown(_CSS_SEM_MENU + _CSS_LOGIN + _CSS_TELA_CHEIA, unsafe_allow_html=True)
    logo = f'<img class="le-logo" src="data:image/png;base64,{_logoPortalBase64()}" alt="TAG - Portal de Automações">'
    with st.container(key="login_wrap"):
        esquerda, direita = st.columns([1.05, 1], gap="small")
        with esquerda, st.container(key="login_esq"):
            st.markdown(
                f'<div class="le-marca">{logo}</div><div class="le-linha"></div>'
                '<p class="le-sistema">SISTEMA DE AUTENTICAÇÃO</p><p class="le-sub">Bem-vindo ao seu espaço de trabalho.</p>'
                f'<p class="le-rodape">© {datetime.now().year} TAG · Todos os direitos reservados</p>',
                unsafe_allow_html=True,
            )
    return direita


def molduraPainel(subtitulo):
    """Mesmo painel dividido da tela de login, para outras telas que vêm logo após o login. Devolve a coluna da direita."""
    return _moldura(subtitulo)


def telaLogin():
    centro = _moldura("Acesse com seu usuário e senha")
    with centro, st.container(key="login_card"):
        st.markdown('<p class="lg-titulo">Bem-vindo</p><p class="lg-sub">Faça login para acessar o sistema</p>', unsafe_allow_html=True)
        with st.form("form_login"):
            login = st.text_input("Usuário", autocomplete="username")
            senha = st.text_input("Senha", type="password", autocomplete="current-password")
            enviar = st.form_submit_button("Entrar  →", type="primary", use_container_width=True)
        if enviar:
            usuario, erro = autenticar(login, senha, identificarDispositivo())
            if usuario:
                ds_cifrado = banco_seguranca.buscarSegredo2fa(usuario["usuario"])
                if ds_cifrado or usuario["perfil"] == "admin":  # admin é obrigatório: sem segredo, cadastra agora
                    st.session_state["_2fa"] = {"usuario": usuario, "cadastrar": not ds_cifrado, "segredo": autenticador.novoSegredo(),
                                                "erros": 0, "expira": (agora() + timedelta(minutes=5)).isoformat()}
                    if (espaco_reservado := st.session_state.pop("_ph_login", None)) is not None:
                        espaco_reservado.empty()
                    st.rerun()
                _concluirLogin(usuario)
            st.error(erro)
        st.markdown('<p class="login-rodape">Esqueceu a senha? Fale com um administrador do portal.</p>',
                    unsafe_allow_html=True)


def _concluirLogin(usuario):
    _abrirSessao(usuario)
    st.session_state.pop("_2fa", None)
    if (espaco_reservado := st.session_state.pop("_ph_login", None)) is not None:
        espaco_reservado.empty()
    st.rerun()


def _mostrarQr(ds_segredo, nm_usuario):
    st.image(autenticador.qrPng(ds_segredo, nm_usuario), width=190)
    st.caption("Não consegue escanear? Digite esta chave no app:")
    st.code(ds_segredo, language=None)


# Telas de acesso ocupam a janela toda: painel da marca inteiro à esquerda (conteúdo centralizado) e formulário inteiro à direita
_CSS_TELA_CHEIA = f"""
<style>
html body [class*="st-key-login_wrap"] {{
    position: fixed; inset: 0; z-index: 999; width: 100vw; height: 100vh; max-width: none; margin: 0;
    border: none; border-radius: 0; box-shadow: none; overflow-y: auto;
}}
html body [class*="st-key-login_wrap"] > [data-testid="stHorizontalBlock"] {{ min-height: 100vh; }}
html body [class*="st-key-login_esq"] {{ min-height: 100vh; padding: 3rem 8%; align-items: stretch; text-align: center; }}
[class*="st-key-login_esq"] .le-logo, [class*="st-key-login_esq"] .le-linha {{ margin-left: auto; margin-right: auto; }}
html body [class*="st-key-login_card"] {{ min-height: 100vh; padding: 2rem 0; width: 100%; max-width: 380px; margin: 0 auto; align-items: stretch; }}
[class*="st-key-login_card"] [data-testid="stImage"] img {{ border-radius: 8px; }}
[class*="st-key-login_card"] [data-testid="stImage"] {{ display: flex; justify-content: center; width: 100%; }}
[class*="st-key-login_card"] [data-testid="stImage"] > div, [class*="st-key-login_card"] [data-testid="stImage"] img {{ margin: 0 auto; }}
[class*="st-key-login_card"] [data-testid="stCaptionContainer"] {{ text-align: center; }}
[class*="st-key-login_card"] [data-testid="stCode"] {{ text-align: center; }}
/* Painel da marca: degradê vinho com pontinhos, marca centralizada e direitos reservados no rodapé */
html body [class*="st-key-login_esq"] {{
    position: relative; border-right: none;
    background: radial-gradient(rgba(255, 255, 255, .07) 1px, transparent 1.5px) 0 0 / 28px 28px,
                linear-gradient(160deg, #7A1030 0%, #5C0C24 45%, #3A0416 100%);
}}
.le-marca {{ display: inline-block; text-align: right; }}
.le-marca .le-logo {{ width: 330px; max-width: 100%; margin: 0; }}
.le-invest {{ color: #fff; font-size: .72rem; font-weight: 700; letter-spacing: .14em; margin: .1rem 0 0; }}
.le-sistema {{ color: #D9B9C3; font-size: 1.02rem; font-weight: 700; letter-spacing: .12em; margin: 0 0 .55rem; }}
.le-sub {{ color: #A98592; font-size: .9rem; margin: 0; }}
.le-rodape {{ position: absolute; left: 0; right: 0; bottom: 1.5rem; text-align: center; color: rgba(255, 255, 255, .32); font-size: .72rem; margin: 0; }}
.le-linha {{ width: 40px; height: 1px; background: rgba(255, 255, 255, .35); margin: 2rem auto 1.6rem; border-radius: 0; }}
/* Lado direito: título, campos com rótulo em maiúsculas e asterisco, sem moldura em volta do formulário */
[class*="st-key-login_card"] .lg-titulo {{ color: #111827; font-size: 1.9rem; font-weight: 700; letter-spacing: -.01em; line-height: 1.2; margin: 0 0 .5rem; }}
[class*="st-key-login_card"] .lg-sub {{ color: #6B7280; font-size: .92rem; margin: 0 0 1.6rem; }}
/* Painel esquerdo: o Streamlit deixa o texto à esquerda e o rodapé preso ao bloco errado; força centro e ancora no painel */
html body [class*="st-key-login_esq"] [data-testid="stElementContainer"] {{ position: static; width: 100%; }}
html body [class*="st-key-login_esq"] .stMarkdown, html body [class*="st-key-login_esq"] .stMarkdown * {{ text-align: center; }}
html body [class*="st-key-login_esq"] .le-marca {{ display: table; margin: 0 auto; }}
html body [class*="st-key-login_esq"] .le-marca * {{ text-align: right; }}
[class*="st-key-login_card"] [data-testid="stForm"] {{ border: none; padding: 0; margin-top: 0; }}
[class*="st-key-login_card"] [data-testid="stWidgetLabel"] p {{
    text-transform: uppercase; font-size: .68rem; font-weight: 700; letter-spacing: .08em; color: #374151; margin-bottom: .2rem;
}}
[class*="st-key-login_card"] [data-testid="stWidgetLabel"] p::after {{ content: " *"; color: #DC2626; }}
[class*="st-key-login_card"] [data-baseweb="input"] {{
    background: #fff; border: 1px solid #D5DAE3; border-radius: 8px; overflow: hidden;
}}
[class*="st-key-login_card"] [data-baseweb="input"] input {{ border: none !important; background: transparent !important; height: 2.75rem; padding-left: .9rem; }}
[class*="st-key-login_card"] [data-baseweb="input"] > div {{ background: transparent !important; }}
[class*="st-key-login_card"] [data-testid="stFormSubmitButton"] button,
[class*="st-key-voltar_2fa"] button {{ width: 100%; height: 2.7rem; min-height: 2.7rem; }}
[class*="st-key-voltar_2fa"] button p {{ color: #fff !important; font-weight: 600; }}
@media (max-width: 640px) {{
    html body [class*="st-key-login_esq"] {{ min-height: auto; padding: 1.8rem 1.6rem 3.4rem; }}
    html body [class*="st-key-login_card"] {{ min-height: auto; padding: 1.6rem 1.4rem; }}
}}
</style>
"""


def tela2fa():
    """Código do autenticador, logo depois da senha. No primeiro acesso mostra o QR code para cadastrar o app."""
    pendente = st.session_state["_2fa"]
    usuario = pendente["usuario"]
    centro = _moldura("Verificação em duas etapas")
    with centro, st.container(key="login_card"):
        st.markdown('<p class="lg-titulo">Código do autenticador</p>', unsafe_allow_html=True)
        if pendente["cadastrar"]:
            st.markdown('<p class="secao-sub">Escaneie o QR code com o Google ou Microsoft Authenticator e digite o código de 6 dígitos '
                        'que aparecer no app.</p>', unsafe_allow_html=True)
            _mostrarQr(pendente["segredo"], usuario["usuario"])
        else:
            st.markdown('<p class="secao-sub">Digite o código de 6 dígitos que aparece no seu app autenticador.</p>', unsafe_allow_html=True)
        with st.form("form_2fa"):
            ds_codigo = st.text_input("Código", max_chars=7, autocomplete="one-time-code")
            enviar = st.form_submit_button("Confirmar", type="primary", use_container_width=True)
        if st.button("Voltar", key="voltar_2fa", use_container_width=True):
            st.session_state.pop("_2fa", None)
            st.rerun()
        if enviar:
            _conferirCodigo2fa(pendente, usuario, ds_codigo)


def _conferirCodigo2fa(pendente, usuario, ds_codigo):
    segredo_servidor = segredo()
    if pendente["cadastrar"]:
        ds_segredo = pendente["segredo"]
    else:
        ds_segredo = autenticador.decifrar(banco_seguranca.buscarSegredo2fa(usuario["usuario"]) or "", segredo_servidor)
    if ds_segredo and autenticador.codigoConfere(ds_segredo, ds_codigo):
        if pendente["cadastrar"]:
            banco_seguranca.gravarSegredo2fa(usuario["usuario"], autenticador.cifrar(ds_segredo, segredo_servidor))
            registrarEvento("2fa_ativado", usuario["usuario"], "")
        _concluirLogin(usuario)
    pendente["erros"] += 1
    registrarEvento("login_falha", usuario["usuario"], "código do autenticador incorreto")
    if pendente["erros"] >= MAX_FALHAS:
        with trava_usuarios:
            usuarios = carregarUsuarios()
            alvo = buscar(usuarios, usuario["usuario"])
            if alvo:
                alvo["bloqueado_ate"] = (agora() + timedelta(minutes=BLOQUEIO_MIN)).isoformat()
                salvarUsuarios(usuarios)
        st.session_state.pop("_2fa", None)
        registrarEvento("login_bloqueado", usuario["usuario"], f"{MAX_FALHAS} erros seguidos no código do autenticador")
        st.rerun()
    st.error("Código incorreto ou expirado. Confira o horário do celular e tente de novo.")


def telaPrimeiroAcesso():
    centro = _moldura("Primeiro acesso: crie o administrador do portal")
    with centro, st.container(key="login_card"):
        st.markdown('<p class="secao">Criar administrador</p>'
                    '<p class="secao-sub">Esta conta poderá cadastrar os demais usuários. Guarde a senha em local seguro.</p>',
                    unsafe_allow_html=True)
        with st.form("form_primeiro_acesso"):
            nome = st.text_input("Nome completo")
            login = st.text_input("Usuário (para entrar)", help="Sem espaços. Ex.: marcelo.jordao")
            senha = st.text_input("Senha", type="password", autocomplete="new-password")
            conf = st.text_input("Confirmar senha", type="password", autocomplete="new-password")
            enviar = st.form_submit_button("Criar administrador", type="primary", use_container_width=True)
        if enviar:
            erro = _validarCadastro(nome, login) or validarSenha(senha, conf)
            if erro:
                st.error(erro)
            else:
                usuario = novoUsuario(login, nome, "admin", senha, trocar_senha=False)
                salvarUsuarios([usuario])
                _abrirSessao(usuario)
                st.rerun()


def _validarCadastro(nome, login):
    if not nome.strip():
        return "Informe o nome."
    login = login.strip().lower()
    if not re.fullmatch(r"[a-z0-9._-]{3,40}", login):
        return "O usuário precisa ter de 3 a 40 caracteres: letras minúsculas, números, ponto, hífen ou sublinhado (sem espaços)."
    return None


def telaTrocarSenhaObrigatoria():
    centro = _moldura("Defina uma nova senha para continuar")
    with centro, st.container(key="login_card"):
        st.markdown('<p class="secao">Nova senha</p>'
                    '<p class="secao-sub">Sua senha foi definida por um administrador. Escolha uma só sua.</p>',
                    unsafe_allow_html=True)
        _formTrocarSenha("form_troca_obrigatoria")
        if st.button("Sair", key="sair_troca"):
            sair()


def _formTrocarSenha(chave):
    sessao = usuarioAtual()
    with st.form(chave, clear_on_submit=True):
        atual = st.text_input("Senha atual", type="password", autocomplete="current-password")
        nova = st.text_input("Nova senha", type="password", autocomplete="new-password",
                             help=f"Mínimo de {SENHA_MIN} caracteres, com maiúsculas, minúsculas e número.")
        conf = st.text_input("Confirmar nova senha", type="password", autocomplete="new-password")
        enviar = st.form_submit_button("Salvar nova senha", type="primary", use_container_width=True)
    if not enviar:
        return
    usuarios = carregarUsuarios()
    usuario = buscar(usuarios, sessao["usuario"])
    if usuario is None or not senhaConfere(atual, usuario):
        st.error("A senha atual não confere.")
    elif atual == nova:
        st.error("A nova senha precisa ser diferente da atual.")
    elif (erro := validarSenha(nova, conf)):
        st.error(erro)
    else:
        usuario.update(gerarHash(nova))
        usuario["trocar_senha"] = False
        salvarUsuarios(usuarios)
        revogarSessoes(usuario["usuario"])  # derruba os outros navegadores; este recebe um token novo
        novo = criarToken(usuario["usuario"])
        st.session_state["_token"], st.session_state["_cookie_gravar"] = novo, novo
        st.session_state[CHAVE_SESSAO]["trocar_senha"] = False
        st.session_state["aviso_conta"] = "Senha alterada com sucesso."
        st.rerun()


def exigirLogin():
    """Chame no começo do home.py: mostra o login e interrompe a página se não houver sessão válida."""
    # Posição fixa: o Streamlit troca elementos por ordem de criação. Se algo (ex.: o cookie) aparecer antes do login só em
    # algumas execuções, o login antigo não é substituído e fica duplicado na tela até a página carregar.
    espaco_reservado = st.empty()
    try:
        lista_usuarios = carregarUsuarios()  # lida uma só vez por execução (era 2 a 3 idas ao banco por clique)
    except ErroArquivoUsuarios:
        st.error("Não foi possível ler o cadastro de usuários no banco de dados. Por segurança o portal foi bloqueado. "
                 "Avise a TI: confira se o servidor MySQL está no ar e se a conexão (BANCO_BKO_*) está correta.")
        st.stop()
    usuario = usuarioAtual()
    if usuario is None:  # tenta restaurar pelo cookie (ex.: a página foi recarregada)
        achado = usuarioDoToken(_cookieDoNavegador())
        if achado:
            _abrirSessao(achado[0], token=_cookieDoNavegador(), desde=achado[1], ativo_ate=achado[2])
            usuario = usuarioAtual()
    elif (not tokenAtivo(st.session_state.get("_token")) or (reg := buscar(lista_usuarios, usuario["usuario"])) is None or not reg.get("ativo", True)
          or (reg["perfil"] != "admin" and reg.get("bloqueio_dispositivo"))):
        _encerrarSessao()  # o usuário foi desativado ou removido: derruba a sessão na hora
        usuario = None
    else:
        usuario["perfil"], usuario["nome"], usuario["trocar_senha"] = reg["perfil"], reg["nome"], reg.get("trocar_senha", False)
        usuario["apps"] = reg.get("apps")  # permissão alterada pelo admin vale na hora
    _emitirCookie()
    if usuario is None:
        # Tela dentro de um placeholder: ao entrar ele é esvaziado antes do rerun, para o login não ficar como "fantasma" na página seguinte.
        st.session_state["_ph_login"] = espaco_reservado
        with espaco_reservado.container():
            pendente = st.session_state.get("_2fa")
            if pendente and datetime.fromisoformat(pendente["expira"]) <= agora():
                st.session_state.pop("_2fa", None)
                pendente = None
            if not lista_usuarios:
                telaPrimeiroAcesso()
            elif pendente:
                tela2fa()
            else:
                telaLogin()
        st.stop()
    if usuario.get("trocar_senha"):  # senha temporária: todo perfil precisa trocar no primeiro acesso
        telaTrocarSenhaObrigatoria()
        st.stop()
    return usuario


def blocoUsuario(usuario):
    """Quem está logado, com o ícone de sair ao lado, no rodapé do menu lateral."""
    col_nome, col_sair = st.sidebar.columns([4, 1], vertical_alignment="center", gap="small")
    col_nome.markdown(
        f'<div class="bloco-usuario"><span class="bu-nome">{html.escape(usuario["nome"])}</span>'
        f'<span class="bu-perfil">{ROTULO_PERFIL.get(usuario["perfil"], usuario["perfil"])}</span></div>',
        unsafe_allow_html=True,
    )
    # O texto "Sair" fica só para leitores de tela e dica; o desenho do ícone vem do CSS (sem fonte de ícones)
    if col_sair.button("Sair", key="botao_sair", help="Sair", use_container_width=True):
        sair()


# Ícone "sair" (porta com seta), desenhado por máscara SVG para não depender da fonte de ícones do Streamlit
_ICONE_SAIR = (
    "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' "
    "stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 "
    "2-2h4'/%3E%3Cpolyline points='16 17 21 12 16 7'/%3E%3Cline x1='21' y1='12' x2='9' y2='12'/%3E%3C/svg%3E\")"
)

CSS_BLOCO_USUARIO = f"""
<style>
[data-testid="stSidebar"] [data-testid="stHorizontalBlock"]:has([class*="st-key-botao_sair"]) {{
    margin: 1rem 0 .4rem; padding: 0; flex-wrap: nowrap; align-items: center;
}}
[data-testid="stSidebar"] [data-testid="stHorizontalBlock"]:has([class*="st-key-botao_sair"]) > [data-testid="stColumn"]:first-child {{ flex: 1 1 auto; min-width: 0; width: auto; }}
[data-testid="stSidebar"] [data-testid="stHorizontalBlock"]:has([class*="st-key-botao_sair"]) > [data-testid="stColumn"]:last-child {{ flex: 0 0 38px; width: 38px; min-width: 38px; }}
.bloco-usuario {{ display: flex; flex-direction: column; gap: .1rem; min-width: 0; }}
.bu-nome {{ color: #fff; font-weight: 600; font-size: .92rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.bu-perfil {{ color: {COR['dourado']}; font-size: .7rem; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; }}
[class*="st-key-botao_sair"] button {{
    width: 38px; min-width: 38px; height: 38px; min-height: 38px; padding: 0; margin: 0; border-radius: 10px; line-height: 0; box-sizing: border-box;
    background: rgba(255, 255, 255, .16) !important; border: 1px solid {COR['dourado']} !important;
    display: flex; align-items: center; justify-content: center; transition: background .15s ease, border-color .15s ease;
}}
[class*="st-key-botao_sair"] button:hover {{ background: rgba(255, 255, 255, .28) !important; }}
[class*="st-key-botao_sair"] button p {{ font-size: 0; line-height: 0; margin: 0; }}
/* o texto "Sair" fica só para leitores de tela: sem ocupar espaço no botão, o ícone fica no centro */
[class*="st-key-botao_sair"] button > div {{ position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }}
[class*="st-key-botao_sair"] button::after {{
    content: ""; flex: none; width: 19px; height: 19px; background-color: #fff;
    -webkit-mask: {_ICONE_SAIR} center / contain no-repeat; mask: {_ICONE_SAIR} center / contain no-repeat;
}}
[class*="st-key-botao_sair"] button:hover::after {{ background-color: {COR['dourado']}; }}
</style>
"""


# ---------------------------------------------------------------- páginas
def paginaMinhaConta():
    usuario = usuarioAtual()
    st.markdown(_CSS_LOGIN, unsafe_allow_html=True)
    topo("Minha conta", "Seus dados de acesso e senha", app="portal")
    if "aviso_conta" in st.session_state:
        st.success(st.session_state.pop("aviso_conta"))
    dados = buscar(carregarUsuarios(), usuario["usuario"]) or {}
    st.markdown(
        f'<div class="detalhe-conta"><p><b>{html.escape(usuario["nome"])}</b></p>'
        f'<p>Usuário: {html.escape(usuario["usuario"])} · Perfil: {ROTULO_PERFIL.get(usuario["perfil"], usuario["perfil"])}</p>'
        f'<p>Último acesso anterior: {dados.get("ultimo_acesso") or "–"}</p></div>',
        unsafe_allow_html=True,
    )
    _secaoAutenticador(usuario)
    st.markdown('<p class="secao">Alterar senha</p>', unsafe_allow_html=True)
    if usuario["perfil"] != "admin":
        st.info("A senha só pode ser alterada por um administrador. Se precisar trocar, peça a redefinição.")
        return
    col, _ = st.columns([1.2, 1])
    with col:
        _formTrocarSenha("form_troca_senha")


def _secaoAutenticador(usuario):
    st.markdown('<p class="secao">Autenticador (verificação em duas etapas)</p>', unsafe_allow_html=True)
    nm_usuario = usuario["usuario"]
    ds_cifrado = banco_seguranca.buscarSegredo2fa(nm_usuario)
    if ds_cifrado:
        st.success("Ativo: o login pede o código do seu app autenticador.")
        if usuario["perfil"] == "admin":
            st.caption("Para administradores é obrigatório. Se trocar de celular, peça a outro administrador para redefinir.")
            return
        with st.form("form_desativar_2fa", clear_on_submit=True):
            ds_codigo = st.text_input("Para desativar, digite o código atual", max_chars=7, autocomplete="one-time-code")
            if st.form_submit_button("Desativar autenticador"):
                ds_segredo = autenticador.decifrar(ds_cifrado, segredo())
                if ds_segredo and autenticador.codigoConfere(ds_segredo, ds_codigo):
                    banco_seguranca.removerSegredo2fa(nm_usuario)
                    registrarEvento("2fa_desativado", nm_usuario, "pelo próprio usuário")
                    st.session_state["aviso_conta"] = "Autenticador desativado."
                    st.rerun()
                st.error("Código incorreto.")
        return
    if "_2fa_conta" not in st.session_state:
        st.caption("Opcional: com o autenticador, o login passa a pedir também um código de 6 dígitos do seu celular.")
        if st.button("Ativar autenticador", key="ativar_2fa"):
            st.session_state["_2fa_conta"] = autenticador.novoSegredo()
            st.rerun()
        return
    ds_segredo = st.session_state["_2fa_conta"]
    _mostrarQr(ds_segredo, nm_usuario)
    with st.form("form_ativar_2fa"):
        ds_codigo = st.text_input("Digite o código que aparece no app", max_chars=7, autocomplete="one-time-code")
        if st.form_submit_button("Confirmar e ativar", type="primary"):
            if autenticador.codigoConfere(ds_segredo, ds_codigo):
                banco_seguranca.gravarSegredo2fa(nm_usuario, autenticador.cifrar(ds_segredo, segredo()))
                registrarEvento("2fa_ativado", nm_usuario, "pelo próprio usuário")
                st.session_state.pop("_2fa_conta", None)
                st.session_state["aviso_conta"] = "Autenticador ativado."
                st.rerun()
            st.error("Código incorreto.")
    if st.button("Cancelar", key="cancelar_2fa"):
        st.session_state.pop("_2fa_conta", None)
        st.rerun()


def paginaUsuarios():
    eu = usuarioAtual()
    topo("Usuários", "Cadastro e controle de acesso ao portal", app="portal")
    if eu["perfil"] != "admin":
        st.error("Apenas administradores podem acessar esta página.")
        return
    if "aviso_usuarios" in st.session_state:
        st.success(st.session_state.pop("aviso_usuarios"))

    usuarios = carregarUsuarios()
    qt_ativos = sum(1 for usuario in usuarios if usuario.get("ativo", True) and not usuario.get("bloqueio_dispositivo"))
    qt_desativados = sum(1 for usuario in usuarios if not usuario.get("ativo", True))
    qt_bloqueados = sum(1 for usuario in usuarios if usuario.get("ativo", True) and usuario.get("bloqueio_dispositivo"))
    qt_admins = sum(1 for usuario in usuarios if usuario["perfil"] == "admin")
    st.markdown(
        '<div class="kpis">'
        f'<div class="kpi"><div class="kpi-label">Total</div><div class="kpi-valor">{len(usuarios)}</div><div class="kpi-sub">{qt_admins} administrador(es)</div></div>'
        f'<div class="kpi ok"><div class="kpi-label">Ativos</div><div class="kpi-valor">{qt_ativos}</div><div class="kpi-sub">podem entrar</div></div>'
        f'<div class="kpi {"vazio" if qt_desativados else "ok"}"><div class="kpi-label">Desativados</div><div class="kpi-valor">{qt_desativados}</div><div class="kpi-sub">sem acesso</div></div>'
        f'<div class="kpi {"div" if qt_bloqueados else "ok"}"><div class="kpi-label">Bloqueados</div><div class="kpi-valor">{qt_bloqueados}</div><div class="kpi-sub">2 contas no mesmo computador</div></div>'
        '</div>', unsafe_allow_html=True)

    busca = st.text_input("Buscar usuário", placeholder="Nome ou usuário", label_visibility="collapsed")
    FILTROS_SITUACAO = {"Todos": None, "Ativos": "Ativo", "Desativados": "Desativado", "Bloqueados": "Bloqueado"}
    filtro = st.radio("Mostrar", list(FILTROS_SITUACAO), horizontal=True, label_visibility="collapsed")

    def situacao(usuario):
        if not usuario.get("ativo", True):
            return "Desativado", "div-suave"
        if usuario.get("bloqueio_dispositivo"):
            return "Bloqueado", "warn"
        return "Ativo", "ok"

    linhas = []
    for usuario in sorted(usuarios, key=lambda conta: (conta["perfil"] != "admin", conta["nome"].lower())):
        nm_situacao, classe = situacao(usuario)
        texto = f'{usuario["nome"]} {usuario["usuario"]}'.lower()
        if busca.strip().lower() not in texto or FILTROS_SITUACAO[filtro] not in (None, nm_situacao):
            continue
        apps = ("Todos" if usuario["perfil"] == "admin" or usuario.get("apps") is None
                else ", ".join(APPS_PORTAL.get(app, app) for app in usuario["apps"]) or "Nenhum")
        pendente = ' <span class="badge warn">troca de senha pendente</span>' if usuario.get("trocar_senha") else ""
        linhas.append(
            f'<tr><td><b>{html.escape(usuario["nome"])}</b><br><span class="u-sub">{html.escape(usuario["usuario"])}</span></td>'
            f'<td><span class="badge {"cat" if usuario["perfil"] == "admin" else "neutro"}">{ROTULO_PERFIL.get(usuario["perfil"], usuario["perfil"])}</span></td>'
            f'<td><span class="badge {classe}">{nm_situacao}</span>{pendente}</td>'
            f'<td class="u-apps">{html.escape(apps)}</td><td class="u-sub">{usuario.get("ultimo_acesso") or "–"}</td></tr>')
    st.markdown(
        """<style>
        .tb-users { width: 100%; border-collapse: collapse; background: #fff; border-radius: 10px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
        .tb-users th { text-align: left; font-size: .72rem; letter-spacing: .08em; text-transform: uppercase; color: #6B5560; padding: .6rem .8rem; background: #F7F2F4; }
        .tb-users td { padding: .65rem .8rem; border-top: 1px solid #F0E8EB; vertical-align: middle; font-size: .9rem; }
        .tb-users tr:hover td { background: #FCF9FA; }
        .u-sub { color: #6B5560; font-size: .8rem; } .u-apps { max-width: 320px; font-size: .82rem; }
        </style>""", unsafe_allow_html=True)
    st.markdown('<p class="secao">Usuários cadastrados</p>', unsafe_allow_html=True)
    if linhas:
        st.markdown('<table class="tb-users"><thead><tr><th>Usuário</th><th>Perfil</th><th>Situação</th><th>Apps liberados</th>'
                    '<th>Último acesso</th></tr></thead><tbody>' + "".join(linhas) + '</tbody></table>', unsafe_allow_html=True)
    else:
        st.caption("Nenhum usuário encontrado com esse filtro.")

    gerada = st.session_state.pop("senha_gerada_novo", None)  # aparece uma única vez: qualquer clique depois a apaga
    if gerada:
        st.warning(f"Senha temporária de **{gerada[0]}** (mostrada só agora; copie e entregue à pessoa. Ao clicar em qualquer coisa ela some):")
        st.code(gerada[1], language=None)

    aba_novo, aba_gerir = st.tabs(["Novo usuário", "Gerenciar usuário"])

    with aba_novo:
        with st.form("form_novo_usuario", clear_on_submit=True):
            c1, c2 = st.columns(2)
            nome = c1.text_input("Nome completo")
            login = c2.text_input("Usuário (para entrar)", help="Sem espaços. Ex.: amanda.silva")
            perfil = c1.selectbox("Perfil", PERFIS, format_func=ROTULO_PERFIL.get)
            senha = c2.text_input("Senha temporária", type="password", autocomplete="new-password",
                                  help="A pessoa será obrigada a trocar esta senha no primeiro acesso.")
            apps_sel = st.multiselect("Apps que pode acessar", list(APPS_PORTAL), format_func=APPS_PORTAL.get,
                                      help="Administradores veem todos, independentemente desta lista.")
            gerar = st.checkbox("Gerar uma senha temporária para mim", help="A senha gerada é mostrada uma única vez.")
            enviar = st.form_submit_button("Criar usuário", type="primary")
        if enviar:
            senha_final = senhaTemporaria() if gerar else senha
            erro = _validarCadastro(nome, login) or (None if gerar else validarSenha(senha, senha))
            if not erro and buscar(usuarios, login):
                erro = "Já existe um usuário com esse nome de acesso."
            if erro:
                st.error(erro)
            else:
                usuarios.append(novoUsuario(login, nome, perfil, senha_final, trocar_senha=True, apps=apps_sel))
                salvarUsuarios(usuarios)
                registrarEvento("usuario_criado", (st.session_state.get(CHAVE_SESSAO) or {}).get("usuario", ""), f"{login.strip().lower()} ({perfil})")
                st.session_state["aviso_usuarios"] = f"Usuário {login.strip().lower()} criado."
                if gerar:
                    st.session_state["senha_gerada_novo"] = (login.strip().lower(), senha_final)
                st.rerun()

    with aba_gerir:
        alvo_login = st.selectbox("Usuário", [usuario["usuario"] for usuario in usuarios],
                                  format_func=lambda login_usuario: f"{login_usuario} · {buscar(usuarios, login_usuario)['nome']}", key="gerir_alvo")
        alvo = buscar(usuarios, alvo_login)
        eh_eu = alvo["usuario"] == eu["usuario"]
        admins_ativos = [usuario for usuario in usuarios if usuario["perfil"] == "admin" and usuario.get("ativo", True)]
        ultimo_admin = alvo["perfil"] == "admin" and alvo.get("ativo", True) and len(admins_ativos) == 1

        g1, g2 = st.columns(2)
        novo_perfil = g1.selectbox("Perfil", PERFIS, index=PERFIS.index(alvo["perfil"]), format_func=ROTULO_PERFIL.get,
                                   key=f"perfil_{alvo_login}", disabled=eh_eu or ultimo_admin)
        ativo = g2.checkbox("Usuário ativo", value=alvo.get("ativo", True), key=f"ativo_{alvo_login}",
                            disabled=eh_eu or ultimo_admin)
        apps_atuais = list(APPS_PORTAL) if alvo.get("apps") is None else [app for app in alvo["apps"] if app in APPS_PORTAL]
        apps_novos = st.multiselect("Apps que pode acessar", list(APPS_PORTAL), default=apps_atuais, format_func=APPS_PORTAL.get,
                                    key=f"apps_{alvo_login}", disabled=novo_perfil == "admin",
                                    help="Administradores veem todos, independentemente desta lista.")
        if eh_eu or ultimo_admin:
            st.caption("Você não pode alterar o próprio perfil ou desativar a própria conta, e o último administrador ativo é protegido.")
        if st.button("Salvar perfil e situação", key=f"salvar_{alvo_login}"):
            mudou_acesso = (alvo["perfil"], alvo.get("ativo", True)) != (novo_perfil, ativo)
            alvo["perfil"], alvo["ativo"] = novo_perfil, ativo
            if novo_perfil != "admin":
                alvo["apps"] = apps_novos
            if ativo:
                alvo["falhas"], alvo["bloqueado_ate"] = 0, None
            salvarUsuarios(usuarios)
            registrarEvento("usuario_alterado", (st.session_state.get(CHAVE_SESSAO) or {}).get("usuario", ""), f"{alvo_login}: perfil {novo_perfil}, {'ativo' if ativo else 'desativado'}")
            if mudou_acesso:
                revogarSessoes(alvo_login)
            st.session_state["aviso_usuarios"] = f"Usuário {alvo_login} atualizado."
            st.rerun()

        bd = alvo.get("bloqueio_dispositivo")
        if bd and alvo["perfil"] != "admin":
            st.warning(f"Conta bloqueada em {bd.get('em', '–')}: usada no mesmo computador que {', '.join(bd.get('com', []))} "
                       f"(computador: {bd.get('host') or 'não identificado'} · IP {bd.get('ip') or '–'}).")
            if st.button("Desbloquear conta", key=f"desbloq_{alvo_login}", type="primary"):
                desbloquearDispositivo(alvo)
                salvarUsuarios(usuarios)
                st.session_state["aviso_usuarios"] = f"Conta {alvo_login} desbloqueada."
                st.rerun()

        st.markdown("**Redefinir senha**")
        r1, r2 = st.columns([2, 1])
        nova = r1.text_input("Nova senha temporária", type="password", key=f"nova_{alvo_login}", autocomplete="new-password")
        gerar_r = r2.checkbox("Gerar para mim", key=f"gerar_{alvo_login}")
        if st.button("Redefinir senha", key=f"redef_{alvo_login}"):
            senha_final = senhaTemporaria() if gerar_r else nova
            erro = None if gerar_r else validarSenha(nova, nova)
            if erro:
                st.error(erro)
            else:
                alvo.update(gerarHash(senha_final))
                alvo["trocar_senha"], alvo["falhas"], alvo["bloqueado_ate"] = True, 0, None
                salvarUsuarios(usuarios)
                registrarEvento("senha_redefinida", (st.session_state.get(CHAVE_SESSAO) or {}).get("usuario", ""), alvo_login)
                revogarSessoes(alvo_login)
                st.session_state["aviso_usuarios"] = f"Senha de {alvo_login} redefinida." + " A pessoa deverá trocá-la no próximo acesso."
                if gerar_r:
                    st.session_state["senha_gerada_novo"] = (alvo_login, senha_final)
                st.rerun()

        st.markdown("**Autenticador (2FA)**")
        if banco_seguranca.buscarSegredo2fa(alvo_login):
            st.caption("Ativo. Se a pessoa perdeu o celular, redefina: ela cadastra o app de novo no próximo login.")
            if st.button("Redefinir autenticador", key=f"redef2fa_{alvo_login}"):
                banco_seguranca.removerSegredo2fa(alvo_login)
                registrarEvento("2fa_redefinido", (st.session_state.get(CHAVE_SESSAO) or {}).get("usuario", ""), alvo_login)
                revogarSessoes(alvo_login)
                st.session_state["aviso_usuarios"] = f"Autenticador de {alvo_login} redefinido."
                st.rerun()
        else:
            st.caption("Não ativado." + (" Será exigido o cadastro no próximo login (administrador)." if alvo["perfil"] == "admin" else ""))

        st.markdown("**Excluir usuário**")
        if eh_eu or ultimo_admin:
            st.caption("Não é possível excluir a própria conta nem o último administrador ativo.")
        else:
            st.caption("Apaga a conta de vez e derruba o acesso dela. Para só suspender o acesso, desmarque “Usuário ativo” acima.")
            confirma = st.checkbox(f"Confirmo a exclusão de {alvo_login}", key=f"confirma_excluir_{alvo_login}")
            if st.button("Excluir usuário", key=f"excluir_{alvo_login}", disabled=not confirma):
                excluirUsuario(usuarios, alvo_login)
                registrarEvento("usuario_excluido", (st.session_state.get(CHAVE_SESSAO) or {}).get("usuario", ""), alvo_login)
                st.session_state["aviso_usuarios"] = f"Usuário {alvo_login} excluído."
                st.rerun()
