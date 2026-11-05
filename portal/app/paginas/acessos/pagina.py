from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from app.seguranca import controle_acesso
from app.seguranca.registro_acessos import DIAS_RETENCAO, ROTULOS_EVENTO, carregarEventos
from app.utilitarias.tema import aplicarTema, topo

aplicarTema()
topo("Acessos e uso", f"Log dos últimos {DIAS_RETENCAO} dias, visível só para administradores", app="portal")

usuario_atual = controle_acesso.usuarioAtual()
if not usuario_atual or usuario_atual["perfil"] != "admin":
    st.error("Apenas administradores podem acessar esta página.")
    st.stop()

lista_eventos = carregarEventos()
if not lista_eventos:
    st.info("Ainda não há eventos registrados.")
    st.stop()

tb_eventos = pd.DataFrame(lista_eventos)
tb_eventos["dt_evento"] = pd.to_datetime(tb_eventos["quando"])
tb_eventos["ds_evento"] = tb_eventos["evento"].map(ROTULOS_EVENTO).fillna(tb_eventos["evento"])
tb_eventos["usuario"] = tb_eventos["usuario"].replace("", "(não identificado)")

dict_periodos = {"Hoje": 0, "Últimos 3 dias": 2, "Últimos 7 dias": 6}
col_periodo, col_usuario, col_evento = st.columns([1, 2, 2])
nm_periodo = col_periodo.selectbox("Período", list(dict_periodos), index=2)
lista_usuarios = col_usuario.multiselect("Usuário", sorted(tb_eventos["usuario"].unique()))
lista_ds_eventos = col_evento.multiselect("Evento", sorted(tb_eventos["ds_evento"].unique()))

dt_inicio = datetime.combine(datetime.now().date() - timedelta(days=dict_periodos[nm_periodo]), datetime.min.time())
tb_filtrada = tb_eventos[tb_eventos["dt_evento"] >= dt_inicio]
if lista_usuarios:
    tb_filtrada = tb_filtrada[tb_filtrada["usuario"].isin(lista_usuarios)]
if lista_ds_eventos:
    tb_filtrada = tb_filtrada[tb_filtrada["ds_evento"].isin(lista_ds_eventos)]


def contar(nm_evento):
    return int((tb_filtrada["evento"] == nm_evento).sum())


qt_logins = contar("login")
qt_usuarios = tb_filtrada.loc[tb_filtrada["evento"] == "login", "usuario"].nunique()
qt_falhas = contar("login_falha")
qt_bloqueios = contar("login_bloqueado") + contar("bloqueio_dispositivo")
qt_paginas = contar("pagina")


def cartao(nm_rotulo, vl_valor, ds_sub, nm_classe=""):
    return (f'<div class="kpi {nm_classe}"><div class="kpi-label">{nm_rotulo}</div>'
            f'<div class="kpi-valor">{vl_valor}</div><div class="kpi-sub">{ds_sub}</div></div>')


st.markdown(
    '<div class="kpis">'
    + cartao("Logins", qt_logins, f"{qt_usuarios} usuário(s) diferentes", "ok")
    + cartao("Falhas de login", qt_falhas, "senha errada ou usuário inexistente", "div" if qt_falhas else "ok")
    + cartao("Bloqueios", qt_bloqueios, "por tentativas ou 2 contas no mesmo computador", "div" if qt_bloqueios else "ok")
    + cartao("Ferramentas abertas", qt_paginas, "aberturas de página no período")
    + "</div>",
    unsafe_allow_html=True,
)

tb_paginas = tb_filtrada[tb_filtrada["evento"] == "pagina"]
col_uso, col_pessoas = st.columns(2)
with col_uso:
    st.markdown('<p class="secao">Uso das ferramentas</p>', unsafe_allow_html=True)
    if tb_paginas.empty:
        st.caption("Nenhuma ferramenta aberta no período.")
    else:
        st.bar_chart(tb_paginas["detalhe"].value_counts().rename("Aberturas"), color="#6A0F2B")
with col_pessoas:
    st.markdown('<p class="secao">Por usuário</p>', unsafe_allow_html=True)
    tb_logins = tb_filtrada[tb_filtrada["evento"] == "login"].groupby("usuario").agg(
        Logins=("evento", "count"), UltimoAcesso=("quando", "max"))
    tb_aberturas = tb_paginas.groupby("usuario").size().rename("Ferramentas abertas")
    tb_usuarios = tb_logins.join(tb_aberturas, how="outer").fillna(0)
    if tb_usuarios.empty:
        st.caption("Nenhum acesso no período.")
    else:
        tb_usuarios = tb_usuarios.rename(columns={"UltimoAcesso": "Último acesso"})
        tb_usuarios["Último acesso"] = tb_usuarios["Último acesso"].replace(0, "–")
        st.dataframe(tb_usuarios.sort_values("Logins", ascending=False), use_container_width=True)

st.markdown('<p class="secao">Eventos</p>'
            f'<p class="secao-sub">{len(tb_filtrada)} evento(s), do mais recente para o mais antigo. '
            f'Eventos com mais de {DIAS_RETENCAO} dias são apagados automaticamente.</p>', unsafe_allow_html=True)
st.dataframe(
    tb_filtrada[["quando", "usuario", "ds_evento", "detalhe", "ip", "computador"]].rename(columns={
        "quando": "Quando", "usuario": "Usuário", "ds_evento": "Evento", "detalhe": "Detalhe", "ip": "IP",
        "computador": "Computador"}),
    hide_index=True, use_container_width=True, height=420,
)
