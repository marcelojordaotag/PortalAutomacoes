"""CRAVA COTAS (Streamlit): confere o xlsx de cotas da Britech contra o cadastro fixo (dados/crava_cotas/cadastro.xlsx)."""
import streamlit as st
from pathlib import Path

from app.paginas.crava_cotas.grids_britech import COLUNA_GRID3, COLUNA_GRID4, COLUNA_VALOR, lerGrid, mensagensSlackGrids, pendencias, resumoProblemas
from app.paginas.crava_cotas.slack_crava import enviarSlack
from app.utilitarias.tema import aplicarTema, topo

ARQUIVO_CADASTRO = Path(__file__).resolve().parents[3] / "dados" / "crava_cotas" / "cadastro.xlsx"

aplicarTema()
topo("CRAVA COTAS", "Conferência de cotas da Britech", app="crava_cotas")

st.markdown('<p class="secao">Conferência das cotas</p>'
            '<p class="secao-sub">Envie o xlsx de cotas (Grid 4) exportado da Britech; '
            'mostra o que está nas cotas e falta no cadastro fixo</p>', unsafe_allow_html=True)
arquivo4 = st.file_uploader("Cotas (Grid 4)", type=["xlsx"], key="britech_grid4")
if arquivo4:
    try:
        if not ARQUIVO_CADASTRO.exists():
            raise ValueError(f"Cadastro fixo não encontrado em {ARQUIVO_CADASTRO}.")
        grid3, grid4 = lerGrid(ARQUIVO_CADASTRO, COLUNA_GRID3), lerGrid(arquivo4, COLUNA_GRID4)
    except ValueError as erro:
        st.error(str(erro))
    else:
        tabela = pendencias(grid3, grid4)
        st.caption(f"Cadastro: {len(grid3)} itens · Cotas: {len(grid4)} itens")
        if tabela.empty:
            st.success("Tudo certo: nenhuma pendência.")
        else:
            st.warning(f"{len(tabela)} pendência(s): {resumoProblemas(tabela)}.")
            st.dataframe(tabela.drop(columns="Problema"), use_container_width=True, hide_index=True,
                         column_config={COLUNA_VALOR: st.column_config.NumberColumn(format="%.8f")})

        st.divider()
        data = st.date_input("Data das cotas", value=None, format="DD/MM/YYYY", key="britech_data",
                             help="A data aparece na mensagem enviada ao Slack.")
        if st.button("Enviar resultado atual ao Slack", key="britech_slack", type="primary", disabled=data is None,
                     help="Envia a tabela de pendências acima." if data else "Selecione a data das cotas para enviar."):
            ok, mensagem = enviarSlack(mensagensSlackGrids(grid3, grid4, data))
            (st.success if ok else st.error)(mensagem)
