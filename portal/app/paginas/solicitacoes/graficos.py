"""Gráficos do painel de Solicitações, com cache pelo CONTEÚDO dos dados.

Montar um gráfico com plotly express leva ~25 ms e o Streamlit refaz isso a cada clique. Aqui a figura fica em cache e a chave
é: tipo do gráfico + conteúdo da tabela + título + parâmetros. Qualquer mudança nos dados (nova solicitação, conclusão, filtro de
período ou tipo, passagem do dia) muda a chave e a figura é refeita na hora. Não há prazo de validade (TTL).
"""
import plotly.express as px
import streamlit as st

from app.utilitarias.tema import estilizarFigura


@st.cache_data(show_spinner=False, max_entries=64)
def figuraEmCache(tipo, dados, titulo, ajustes, parametros):
    """tipo: 'bar' | 'pie' | 'line'. ajustes: tupla de (método, argumentos, opções) aplicados à figura antes do estilo."""
    figura = getattr(px, tipo)(dados, **parametros)
    for nm_metodo, tp_argumentos, dic_opcoes in ajustes:
        getattr(figura, nm_metodo)(*tp_argumentos, **dic_opcoes)
    estilizarFigura(figura, titulo)
    return figura


def grafico(tipo, dados, titulo, ajustes=(), **parametros):
    figura = figuraEmCache(tipo, dados, titulo, tuple(ajustes), parametros)
    st.plotly_chart(figura, use_container_width=True, config={"displayModeBar": False})
