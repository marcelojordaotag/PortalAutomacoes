"""Log breve de acessos e uso das ferramentas, com retenção de 7 dias (só administradores veem, na página Acessos e uso).

- Um evento por linha em dados/portal/acessos.jsonl (fora do git).
- Nunca grava senha. Login de quem não existe não é guardado, para não registrar uma senha digitada no campo errado.
- O log nunca derruba o portal: qualquer falha de gravação é ignorada.
"""
import json
import threading
from datetime import datetime, timedelta

import streamlit as st

from app.ambiente.config_ambiente import obterDiretorioDados

DIAS_RETENCAO = 7
arquivo_log = obterDiretorioDados("portal") / "acessos.jsonl"
trava_log = threading.Lock()
controle_poda = {"ultima": None}

ROTULOS_EVENTO = {
    "login": "Entrou",
    "login_falha": "Falha de login",
    "login_bloqueado": "Bloqueada por tentativas",
    "bloqueio_dispositivo": "Bloqueada: 2 contas no mesmo computador",
    "desbloqueio": "Conta desbloqueada",
    "logout": "Saiu",
    "sessao_expirada": "Sessão encerrada por inatividade",
    "sessao_renovada": "Confirmou presença",
    "pagina": "Abriu ferramenta",
    "usuario_criado": "Usuário criado",
    "usuario_alterado": "Usuário alterado",
    "usuario_excluido": "Usuário excluído",
    "senha_redefinida": "Senha redefinida",
}


def _agoraTexto():
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def _limiteRetencao():
    return (datetime.now() - timedelta(days=DIAS_RETENCAO)).isoformat(sep=" ", timespec="seconds")


def _lerLinhas():
    try:
        linhas = arquivo_log.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    lista_eventos = []
    for linha in linhas:
        try:
            lista_eventos.append(json.loads(linha))
        except ValueError:
            continue
    return lista_eventos


def _podar():
    """Apaga o que passou de 7 dias (no máximo uma vez por hora por processo)."""
    agora_poda = datetime.now()
    if controle_poda["ultima"] and agora_poda - controle_poda["ultima"] < timedelta(hours=1):
        return
    controle_poda["ultima"] = agora_poda
    limite = _limiteRetencao()
    lista_eventos = [evento for evento in _lerLinhas() if evento.get("quando", "") >= limite]
    arquivo_tmp = arquivo_log.with_suffix(".tmp")
    arquivo_tmp.write_text("".join(json.dumps(evento, ensure_ascii=False) + "\n" for evento in lista_eventos), encoding="utf-8")
    arquivo_tmp.replace(arquivo_log)


def registrarEvento(nm_evento, login="", ds_detalhe="", ds_ip="", nm_computador=""):
    registro = {"quando": _agoraTexto(), "evento": nm_evento, "usuario": login, "detalhe": ds_detalhe,
                "ip": ds_ip, "computador": nm_computador}
    try:
        with trava_log:
            with arquivo_log.open("a", encoding="utf-8") as arquivo:
                arquivo.write(json.dumps(registro, ensure_ascii=False) + "\n")
            _podar()
    except OSError:
        pass


def registrarUsoPagina(login, titulo_pagina):
    """Registra a ferramenta aberta, uma vez por vez que a pessoa troca de página nesta sessão."""
    if st.session_state.get("_ultima_pagina_log") != titulo_pagina:
        st.session_state["_ultima_pagina_log"] = titulo_pagina
        registrarEvento("pagina", login, titulo_pagina)


def carregarEventos():
    """Eventos dos últimos 7 dias, do mais recente para o mais antigo."""
    limite = _limiteRetencao()
    lista_eventos = [evento for evento in _lerLinhas() if evento.get("quando", "") >= limite]
    return sorted(lista_eventos, key=lambda evento: evento.get("quando", ""), reverse=True)
