"""Aba "Apagar cadastros" da Solicitação de extratos: busca, marca e apaga linhas do cadastro de fundos e cotistas.

Nada é apagado sem confirmação, e cada linha apagada fica copiada em portal_tb_extratos_cadastro_excluido (quem e quando).
"""
import pandas as pd
import streamlit as st

from app.database.extratos import excluirCadastro, listarCadastroExistente
from app.paginas.extratos.importacao import normalizar
from app.seguranca.controle_acesso import usuarioAtual

LIMITE_BUSCA_SEM_FILTRO = 200  # sem busca, mostra só as primeiras linhas para a lista não ficar enorme


def _rotulo(linha):
    return f"#{linha['id_registro']} · {linha['nm_fundo']} — {linha['nm_cotista']} ({linha['nr_doc_cotista']})"


@st.dialog("Confirmar exclusão")
def _confirmarExclusao(lista_linhas):
    qt_linhas = len(lista_linhas)
    qt_fundos = len({linha["ds_chave_fundo"] for linha in lista_linhas})
    st.markdown(f"Você vai apagar **{qt_linhas}** cadastro(s) de **{qt_fundos}** fundo(s). Isso tira essas linhas dos próximos pedidos de extrato.")
    st.dataframe(
        pd.DataFrame([{"Fundo": l["nm_fundo"], "Cotista": l["nm_cotista"], "CPF/CNPJ": l["nr_doc_cotista"], "E-mails": l["ds_emails"]}
                      for l in lista_linhas]),
        hide_index=True, width="stretch")
    st.caption("As rodadas de extratos já abertas não mudam (elas guardam a própria cópia). "
               "As linhas apagadas ficam guardadas na tabela portal_tb_extratos_cadastro_excluido, caso precise recuperar.")
    col_apagar, col_cancelar = st.columns(2)
    if col_apagar.button("Apagar definitivamente", type="primary", width="stretch", key="exclusao_confirmar"):
        nm_usuario = (usuarioAtual() or {}).get("usuario", "")
        st.session_state["exclusao_resultado"] = excluirCadastro([l["id_registro"] for l in lista_linhas], nm_usuario)
        st.session_state["exclusao_n"] = st.session_state.get("exclusao_n", 0) + 1  # limpa a seleção
        st.rerun()
    if col_cancelar.button("Cancelar", width="stretch", key="exclusao_cancelar"):
        st.rerun()


def abaApagar():
    qt_apagadas = st.session_state.pop("exclusao_resultado", None)
    if qt_apagadas is not None:
        st.success(f"{qt_apagadas} cadastro(s) apagado(s).")

    nr_exclusao = st.session_state.setdefault("exclusao_n", 0)
    chave_busca, chave_selecao = f"exclusao_busca_{nr_exclusao}", f"exclusao_selecao_{nr_exclusao}"

    with st.container(border=True, key="card_lista"):
        st.markdown('<div class="card-title">Apagar cadastros</div>'
                    '<div class="card-hint">Busque pelo fundo, cotista ou CPF/CNPJ, marque o que quer apagar e confirme. '
                    "Nada é apagado antes da confirmação.</div>", unsafe_allow_html=True)
        tx_busca = st.text_input("Buscar", key=chave_busca, placeholder="Fundo, cotista ou CPF/CNPJ")

    try:
        lista_cadastro = listarCadastroExistente()
    except Exception as erro:  # noqa: BLE001
        st.error(f"Não foi possível ler o cadastro no banco de dados: {erro}")
        return
    if not lista_cadastro:
        st.info("O cadastro está vazio: não há nada para apagar.")
        return

    tx_busca_norm = normalizar(tx_busca)
    lista_filtrada = [linha for linha in lista_cadastro if not tx_busca_norm or tx_busca_norm in normalizar(
        f"{linha['nm_fundo']} {linha['nm_cotista']} {linha['nr_doc_cotista']} {linha['nr_cnpj']}")]
    ic_cortada = not tx_busca_norm and len(lista_filtrada) > LIMITE_BUSCA_SEM_FILTRO
    if ic_cortada:
        lista_filtrada = lista_filtrada[:LIMITE_BUSCA_SEM_FILTRO]

    dic_por_rotulo = {_rotulo(linha): linha for linha in lista_filtrada}
    lista_rotulos = list(dic_por_rotulo)

    with st.container(border=True, key="card_conf"):
        st.caption(f"{len(lista_cadastro)} cadastro(s) no total · {len(lista_filtrada)} exibido(s)"
                   + (f" (use a busca para ver os demais)" if ic_cortada else ""))
        col_todos, col_limpar, _ = st.columns([1.3, 1, 2.2])
        col_todos.button(f"Marcar os {len(lista_rotulos)} exibidos", disabled=not lista_rotulos, width="stretch", key=f"exclusao_todos_{nr_exclusao}",
                         on_click=lambda: st.session_state.update({chave_selecao: lista_rotulos}))
        col_limpar.button("Limpar marcação", width="stretch", key=f"exclusao_limpar_{nr_exclusao}",
                          on_click=lambda: st.session_state.update({chave_selecao: []}))
        lista_marcados = st.multiselect("Cadastros a apagar", lista_rotulos, key=chave_selecao,
                                        placeholder="Escolha um ou mais cadastros", label_visibility="collapsed")
        lista_linhas = [dic_por_rotulo[rotulo] for rotulo in lista_marcados if rotulo in dic_por_rotulo]
        if st.button(f"Apagar {len(lista_linhas)} selecionado(s)", type="primary", disabled=not lista_linhas, key=f"exclusao_apagar_{nr_exclusao}"):
            _confirmarExclusao(lista_linhas)
