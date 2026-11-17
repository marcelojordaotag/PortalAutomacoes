"""Tela de teste do extratos (/extratos?teste): cadastro fictício e o resto de verdade, em recursos de teste.

O cadastro (fundos e cotistas) é inventado e não vem do banco. Os e-mails saem de verdade, só para o endereço de teste. A
conferência lê o Gmail de verdade (as respostas aos e-mails de teste) e salva os anexos numa pasta de teste do Drive.
"""
from datetime import datetime

import pandas as pd
import streamlit as st

EMAIL_DE_TESTE = "marcelo.jordao@taginvest.com.br"  # na tela de teste todo e-mail sai só para este endereço, sem cópia

CHAVES_DA_SESSAO = (
    "rodada", "conferencia", "disco", "disco_chave", "rodada_carregada", "rodadas_outras", "reenvio_ultima_checagem",
    "dlg_lista", "dlg_previa", "dlg_recentes", "aviso_envio", "falhas_envio",
    "teste_manifesto",
)

# (fundo, CNPJ, cotista, CPF/CNPJ do cotista, e-mails): tudo inventado; os domínios exemplo.com.br não existem
LINHAS_FICTICIAS = [
    ("FUNDO ALFA FIM CP DEMO", "00.000.001/0001-01", "COTISTA EXEMPLO UM LTDA", "11.111.111/0001-11", "gestao@alfa.exemplo.com.br; operacoes@alfa.exemplo.com.br"),
    ("FUNDO ALFA FIM CP DEMO", "00.000.001/0001-01", "COTISTA EXEMPLO DOIS S.A.", "22.222.222/0001-22", "gestao@alfa.exemplo.com.br; operacoes@alfa.exemplo.com.br"),
    ("FUNDO BETA FIA DEMO", "00.000.002/0001-02", "COTISTA EXEMPLO TRES", "33.333.333/0001-33", "controladoria@beta.exemplo.com.br"),
    ("FUNDO GAMA FIDC SUB DEMO", "00.000.003/0001-03", "FUNDACAO EXEMPLO PREV", "44.444.444/0001-44", "middle@gama.exemplo.com.br"),
    ("FUNDO GAMA FIDC SR DEMO", "00.000.004/0001-04", "FUNDACAO EXEMPLO PREV", "44.444.444/0001-44", "middle@gama.exemplo.com.br"),
    ("FUNDO DELTA MULTI DEMO", "00.000.005/0001-05", "COTISTA EXEMPLO QUATRO", "55.555.555/0001-55", "admin@delta.exemplo.com.br"),
    ("FUNDO EPSILON FII DEMO", "00.000.006/0001-06", "COTISTA EXEMPLO CINCO", "66.666.666/0001-66", ""),
    ("FUNDO ZETA FIP DEMO", "00.000.007/0001-07", "COTISTA EXEMPLO SEIS", "77.777.777/0001-77", "email-com-erro@exemplo"),
    ("FUNDO ETA FIC DEMO", "00.000.008/0001-08", "COTISTA EXEMPLO SETE", "88.888.888/0001-88", "backoffice@eta.exemplo.com.br"),
    ("FUNDO ETA FIC DEMO", "00.000.008/0001-08", "COTISTA EXEMPLO OITO", "99.999.999/0001-99", "backoffice@eta.exemplo.com.br"),
]


def cadastroFicticio():
    """Cadastro de fundos e cotistas inventado, com as mesmas colunas da tabela do banco."""
    return pd.DataFrame(LINHAS_FICTICIAS, columns=["Nome do Fundo", "CNPJ", "COTISTAS", "CPF/CNPJ COTISTAS", "emails"])


def alinharModo(ic_teste):
    """Ao passar da tela real para a de teste (ou ao contrário) na mesma sessão, limpa o que era do outro modo."""
    ds_modo = "teste" if ic_teste else "real"
    if st.session_state.get("_modo_extratos", ds_modo) != ds_modo:
        for ds_chave in list(st.session_state.keys()):
            if ds_chave in CHAVES_DA_SESSAO or str(ds_chave).startswith("vigia_"):
                st.session_state.pop(ds_chave, None)
    st.session_state["_modo_extratos"] = ds_modo


def mostrarFaixa(ds_link_pasta=""):
    ds_pasta = f" Os extratos recebidos são salvos numa **pasta de teste do Drive** ([abrir]({ds_link_pasta}))." if ds_link_pasta else ""
    st.warning(f"**TELA DE TESTE** com cadastro fictício. Os e-mails saem de verdade, mas **sempre e só para {EMAIL_DE_TESTE}**, sem cópia (CC) e com "
               "[TESTE] no assunto. Para testar o recebimento, **responda a um desses e-mails** (pode ser você mesmo, com um PDF anexo) e "
               f"clique em Conferir envios e respostas.{ds_pasta} Nada vai para o banco nem para o Drive da empresa. "
               "Para a tela real, abra o extratos sem `?teste`.")
