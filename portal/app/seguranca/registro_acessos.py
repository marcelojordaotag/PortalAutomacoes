"""Log breve de acessos e uso das ferramentas, com retenção de 7 dias (só administradores veem, na página Acessos e uso).

- Um evento por linha na tabela tb_acesso_log (banco MySQL).
- Nunca grava senha. Login de quem não existe não é guardado, para não registrar uma senha digitada no campo errado.
- O log nunca derruba o portal: qualquer falha de gravação é ignorada.
"""
import threading
from datetime import datetime, timedelta

import streamlit as st

from app.database import seguranca as banco_seguranca

DIAS_RETENCAO = 7
controle_poda = {"ultima": None}
trava_poda = threading.Lock()

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


def _podar():
    """Apaga o que passou de 7 dias (no máximo uma vez por hora por processo)."""
    agora_poda = datetime.now()
    with trava_poda:
        if controle_poda["ultima"] and agora_poda - controle_poda["ultima"] < timedelta(hours=1):
            return
        controle_poda["ultima"] = agora_poda
    banco_seguranca.apagarAcessosAntigos(DIAS_RETENCAO)


def registrarEvento(nm_evento, login="", ds_detalhe="", ds_ip="", nm_computador=""):
    try:
        banco_seguranca.gravarAcesso(nm_evento, login, ds_detalhe, ds_ip, nm_computador)
        _podar()
    except Exception:  # noqa: BLE001  (o log nunca pode derrubar o portal, nem por falha de banco)
        pass


def registrarUsoPagina(login, titulo_pagina):
    """Registra a ferramenta aberta, uma vez por vez que a pessoa troca de página nesta sessão."""
    if st.session_state.get("_ultima_pagina_log") != titulo_pagina:
        st.session_state["_ultima_pagina_log"] = titulo_pagina
        registrarEvento("pagina", login, titulo_pagina)


def carregarEventos():
    """Eventos dos últimos 7 dias, do mais recente para o mais antigo."""
    try:
        return banco_seguranca.listarAcessos(DIAS_RETENCAO)
    except Exception:  # noqa: BLE001  (a página de acessos mostra "sem eventos" em vez de quebrar)
        return []
