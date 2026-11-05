import re

import streamlit as st


def seletorIds(ds_rotulo, lista_opcoes, nm_chave, ds_ajuda=None):
    """Lista de seleção de IDs com campo ao lado para digitar um ID novo (o multiselect do Streamlit 1.43 não aceita valor novo)."""

    def adicionarNovos():
        ds_texto = st.session_state.get(f"{nm_chave}_novo", "")
        lista_novos = [ds_novo.strip() for ds_novo in re.split(r"[,;\s]+", ds_texto) if ds_novo.strip()]
        lista_atual = list(st.session_state.get(nm_chave, []))
        for ds_novo in lista_novos:
            if ds_novo not in lista_atual:
                lista_atual.append(ds_novo)
        st.session_state[nm_chave] = lista_atual
        st.session_state[f"{nm_chave}_novo"] = ""

    lista_total = list(dict.fromkeys(list(lista_opcoes) + list(st.session_state.get(nm_chave, []))))
    lista_selecionada = st.multiselect(ds_rotulo, options=lista_total, key=nm_chave, help=ds_ajuda)
    st.text_input("Adicionar ID novo", key=f"{nm_chave}_novo", on_change=adicionarNovos,
                  placeholder="Digite o ID e tecle Enter (vários: separe por vírgula)")
    return lista_selecionada
