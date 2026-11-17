"""Aba "Importar cadastro" do Crava Cotas: cadastra no banco o cadastro fixo (Grid 3 da Britech), por planilha ou, no futuro, pela API.

Regra de duplicidade: o cadastro é identificado pelo Id Cliente (número da carteira na Britech). Id Cliente que já existe no
banco, ou que se repete na própria planilha, não é criado de novo. O Id Pessoa não serve de chave: uma mesma pessoa pode ter
mais de uma carteira.
"""
import io
import re

import pandas as pd
import streamlit as st

from app.database.crava import CAMPOS_CADASTRO, atualizarCadastroCrava, incluirCadastroCrava, listarCadastroCrava
from app.paginas.crava_cotas.grids_britech import COLUNAS_TITLE, textoDoTitle
from app.utilitarias.importacao_planilha import ErroImportacao, limpar, lerPlanilhaBruta, normalizar

# (campo no banco, nome da coluna, obrigatória, exemplo, regra, apelidos aceitos). Mesma ordem de CAMPOS_CADASTRO.
COLUNAS_ESPERADAS = [
    ("ds_grupo_proc_paralelo", "Grupo Proc. Paralelo", False, "Fundo de Investimento", "Grupo de processamento paralelo.",
     {"grupo proc. paralelo", "grupo proc paralelo", "grupo proc.paralelo"}),
    ("id_cliente", "Id Cliente", True, "1234", "Número da carteira na Britech. É a chave: se já existe, o cadastro não é criado de novo.",
     {"id cliente", "idcliente", "id_cliente"}),
    ("nm_apelido", "Apelido", True, "FUNDO EXEMPLO FIA", "Nome da carteira. Aparece na conferência e no aviso do Slack.", {"apelido"}),
    ("id_pessoa", "Id Pessoa", False, "5678", "Pessoa dona da carteira (pode se repetir entre carteiras).", {"id pessoa", "idpessoa"}),
    ("ds_zera_caixa", "Zera Caixa", False, "N", "S ou N.", {"zera caixa"}),
    ("ds_tipo_cliente", "Tipo Cliente", False, "Fundos de Investimentos", "Tipo do cliente.", {"tipo cliente"}),
    ("ds_ativo", "Ativo", False, "Sim", "Sim ou Não.", {"ativo"}),
    ("ds_tipo_controle", "Tipo Controle", False, "Completo", "Tipo de controle (o HTML da exportação é limpo sozinho).", {"tipo controle"}),
    ("ds_implantacao", "Implantação", False, "2022-07-28", "Data de implantação.", {"implantacao", "data implantacao"}),
    ("ds_status", "Status", False, "Fechado", "Situação da carteira no dia.", {"status"}),
    ("ds_data_dia", "Data Dia", False, "2026-10-20", "Data do dia da carteira.", {"data dia"}),
    ("ds_data_atualizacao", "Data Atualização", False, "2024-01-04 10:03:29", "Última atualização na Britech.", {"data atualizacao"}),
    ("ds_ativo_cetip", "Ativo Cetip", False, "Não", "Sim ou Não.", {"ativo cetip"}),
]
assert [coluna[0] for coluna in COLUNAS_ESPERADAS] == CAMPOS_CADASTRO

STATUS_NOVA, STATUS_EXISTE, STATUS_REPETIDA, STATUS_ERRO = "nova", "ja_existe", "repetida", "erro"
DIC_NOME_POR_CAMPO = {coluna[0]: coluna[1] for coluna in COLUNAS_ESPERADAS}


def chaveId(valor):
    """Id Cliente só com números, sem zeros à esquerda ('0123' e '123.0' viram '123'). Vazio se não for número."""
    tx_valor = limpar(valor)
    return str(int(tx_valor)) if re.fullmatch(r"\d+", tx_valor) else ""


def valorLimpo(valor, nm_coluna):
    """Texto limpo; células exportadas com HTML ficam só com o texto (Tipo Controle pelo title=, como a página faz)."""
    return limpar(textoDoTitle(limpar(valor), nm_coluna in COLUNAS_TITLE))


# ---------------------------------------------------------------- leitura e análise (sem tela)
def lerPlanilhaImportacao(arquivo):
    """(DataFrame com uma coluna por campo do banco + linha, lista de avisos sobre colunas opcionais ausentes)."""
    df_bruto = lerPlanilhaBruta(arquivo)
    dic_colunas, lista_faltando, lista_avisos = {}, [], []
    for campo, nm_coluna, ic_obrigatoria, _exemplo, _regra, conjunto_apelidos in COLUNAS_ESPERADAS:
        nm_encontrada = next((nm_original for nm_original in df_bruto.columns if normalizar(nm_original) in conjunto_apelidos), None)
        if nm_encontrada is not None:
            dic_colunas[campo] = nm_encontrada
        elif ic_obrigatoria:
            lista_faltando.append(nm_coluna)
        else:
            lista_avisos.append(nm_coluna)
    if lista_faltando:
        raise ErroImportacao(
            f"Faltam colunas obrigatórias na planilha: {', '.join(lista_faltando)}. "
            f"Colunas encontradas: {', '.join(str(nm_coluna) for nm_coluna in df_bruto.columns)}.")
    df = pd.DataFrame({campo: (df_bruto[dic_colunas[campo]].map(lambda valor, nm=DIC_NOME_POR_CAMPO[campo]: valorLimpo(valor, nm))
                               if campo in dic_colunas else "") for campo in CAMPOS_CADASTRO})
    df["linha"] = df.index + 2  # linha 1 é o cabeçalho
    return df[(df[CAMPOS_CADASTRO] != "").any(axis=1)].reset_index(drop=True), lista_avisos


def analisarImportacao(df, lista_existentes):
    """Classifica cada linha: nova, ja_existe, repetida (na própria planilha) ou erro. Devolve lista de dicts."""
    dic_existentes = {}
    for existente in lista_existentes:
        dic_existentes.setdefault(chaveId(existente["id_cliente"]), existente)
    dic_vistas, lista_resultado = {}, []

    for linha in df.to_dict("records"):
        id_cliente = chaveId(linha["id_cliente"])
        dic_valores = {campo: linha[campo] for campo in CAMPOS_CADASTRO}
        dic_valores["id_cliente"] = id_cliente
        registro = {"linha": linha["linha"], "id_cliente": id_cliente or linha["id_cliente"], "apelido": linha["nm_apelido"],
                    "status": "", "motivo": "", "id_cadastro": None, "divergente": False, "valores": dic_valores}
        lista_erros = []
        if not linha["id_cliente"]:
            lista_erros.append("Id Cliente vazio")
        elif not id_cliente:
            lista_erros.append("Id Cliente deve ser um número")
        if not linha["nm_apelido"]:
            lista_erros.append("Apelido vazio")
        if lista_erros:
            registro["status"], registro["motivo"] = STATUS_ERRO, "; ".join(lista_erros)
        elif id_cliente in dic_vistas:
            registro["status"] = STATUS_REPETIDA
            registro["motivo"] = f"mesmo Id Cliente da linha {dic_vistas[id_cliente]['linha']} (ignorada)"
        elif id_cliente in dic_existentes:
            existente = dic_existentes[id_cliente]
            lista_diferentes = [DIC_NOME_POR_CAMPO[campo] for campo in CAMPOS_CADASTRO if campo != "id_cliente"
                                and valorLimpo(existente[campo], DIC_NOME_POR_CAMPO[campo]) != dic_valores[campo]]
            registro["status"], registro["id_cadastro"] = STATUS_EXISTE, existente["id_cadastro"]
            registro["divergente"] = bool(lista_diferentes)
            registro["motivo"] = ("já cadastrada, com dados diferentes: " + ", ".join(lista_diferentes)) if lista_diferentes else "já cadastrada"
        else:
            registro["status"] = STATUS_NOVA
        if registro["status"] != STATUS_ERRO:
            dic_vistas.setdefault(id_cliente, registro)
        lista_resultado.append(registro)
    return lista_resultado


def importarCadastro(lista_resultado, ic_atualizar):
    """Grava as novas e, se pedido, atualiza as já cadastradas que divergem. Devolve as contagens."""
    def linhaBanco(registro):
        return tuple(registro["valores"][campo] or None for campo in CAMPOS_CADASTRO)

    lista_novas = [linhaBanco(r) for r in lista_resultado if r["status"] == STATUS_NOVA]
    qt_incluidas = incluirCadastroCrava(lista_novas)
    lista_atualizar = [(*(r["valores"][campo] or None for campo in CAMPOS_CADASTRO if campo != "id_cliente"), r["id_cadastro"])
                       for r in lista_resultado if ic_atualizar and r["status"] == STATUS_EXISTE and r["divergente"]]
    atualizarCadastroCrava(lista_atualizar)
    return {"incluidas": qt_incluidas, "atualizadas": len(lista_atualizar), "ja_existiam_agora": len(lista_novas) - qt_incluidas}


def gerarModelo():
    """Planilha modelo: aba Dados (só o cabeçalho, é a que o app lê) e aba Exemplo (uma linha fictícia)."""
    lista_colunas = [coluna[1] for coluna in COLUNAS_ESPERADAS]
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as escritor:
        pd.DataFrame(columns=lista_colunas).to_excel(escritor, sheet_name="Dados", index=False)
        pd.DataFrame([[coluna[3] for coluna in COLUNAS_ESPERADAS]], columns=lista_colunas).to_excel(escritor, sheet_name="Exemplo", index=False)
        for planilha in escritor.book.worksheets:
            for nr_coluna in range(1, len(lista_colunas) + 1):
                planilha.column_dimensions[planilha.cell(row=1, column=nr_coluna).column_letter].width = 24
    return buffer.getvalue()


# ---------------------------------------------------------------- tela
def _tabela(lista_resultado, lista_status):
    return pd.DataFrame([{"Linha": r["linha"], "Id Cliente": r["id_cliente"], "Apelido": r["apelido"], "Observação": r["motivo"]}
                         for r in lista_resultado if r["status"] in lista_status])


def abaImportar():
    ds_resultado = st.session_state.pop("crava_importacao_resultado", None)
    if ds_resultado:
        lista_partes = [f"{ds_resultado['incluidas']} cadastro(s) novo(s) incluído(s)"]
        if ds_resultado["atualizadas"]:
            lista_partes.append(f"{ds_resultado['atualizadas']} atualizado(s)")
        if ds_resultado["ja_existiam_agora"]:
            lista_partes.append(f"{ds_resultado['ja_existiam_agora']} já tinham sido cadastrado(s) por outra pessoa e foram ignorados")
        st.success("Importação concluída: " + "; ".join(lista_partes) + ".")

    st.markdown('<p class="secao">Importar modelo de cadastro</p>'
                '<p class="secao-sub">Cadastra as carteiras (Grid 3 da Britech) no banco, por planilha ou pela API. '
                "Antes de gravar, o portal mostra o que vai entrar.</p>", unsafe_allow_html=True)

    with st.container(border=True):
        st.markdown("**Colunas esperadas**")
        st.dataframe(pd.DataFrame([{"Coluna": coluna[1], "Obrigatória": "Sim" if coluna[2] else "Não", "Exemplo": coluna[3], "Regra": coluna[4]}
                                   for coluna in COLUNAS_ESPERADAS]), hide_index=True, width="stretch")
        st.markdown(
            "**Como evita duplicados**\n"
            "- O cadastro é identificado pelo **Id Cliente** (número da carteira na Britech). Se o Id Cliente **já está cadastrado**, "
            "ele **não é criado de novo**. Se outros dados forem diferentes (status, datas...), você escolhe se quer atualizá-los "
            "(por padrão, não mexe).\n"
            "- Se o mesmo Id Cliente **se repete dentro da própria planilha**, só a primeira linha vale.\n"
            "- O **Id Pessoa não identifica** o cadastro: uma mesma pessoa pode ter mais de uma carteira.\n"
            "- Linhas sem Id Cliente numérico ou sem Apelido **não são importadas**. Colunas com HTML na exportação "
            "(como Tipo Controle) são limpas sozinhas."
        )
        st.download_button("Baixar planilha modelo", gerarModelo(), file_name="modelo_cadastro_crava.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", icon=":material/download:")

    with st.container(border=True):
        st.markdown("**Buscar pela API da Britech**")
        if st.button("Buscar cadastro na API da Britech", key="crava_importar_api", icon=":material/cloud_download:"):
            st.info("A busca pela API da Britech ainda não está disponível. Por enquanto, importe pela planilha abaixo.")
        st.caption("Em breve: puxar o cadastro direto da Britech, sem precisar exportar a planilha.")

    with st.container(border=True):
        nr_upload = st.session_state.setdefault("crava_importacao_n", 0)
        arquivo = st.file_uploader("Planilha de cadastro", type=["xlsx", "xls", "csv"], key=f"crava_upload_cadastro_{nr_upload}")
        if arquivo is None:
            st.caption("Escolha a planilha para ver a conferência antes de importar.")
            return
        try:
            df, lista_avisos_colunas = lerPlanilhaImportacao(arquivo)
            lista_existentes = listarCadastroCrava()
        except ErroImportacao as erro:
            st.error(str(erro))
            return
        if df.empty:
            st.warning("A planilha não tem nenhuma linha com dados.")
            return
        if lista_avisos_colunas:
            st.warning("Colunas opcionais que não vieram na planilha (ficam em branco nas linhas novas): " + ", ".join(lista_avisos_colunas) + ".")

        lista_resultado = analisarImportacao(df, lista_existentes)
        qt_novas = sum(r["status"] == STATUS_NOVA for r in lista_resultado)
        qt_existem = sum(r["status"] == STATUS_EXISTE for r in lista_resultado)
        qt_diverge = sum(r["status"] == STATUS_EXISTE and r["divergente"] for r in lista_resultado)
        qt_repetidas = sum(r["status"] == STATUS_REPETIDA for r in lista_resultado)
        qt_erros = sum(r["status"] == STATUS_ERRO for r in lista_resultado)

        colunas_kpi = st.columns(5)
        for coluna_kpi, (nm_rotulo, qt_valor) in zip(colunas_kpi, (("Linhas lidas", len(lista_resultado)), ("Novas", qt_novas),
                                                                  ("Já cadastradas", qt_existem), ("Repetidas", qt_repetidas),
                                                                  ("Com erro", qt_erros))):
            coluna_kpi.metric(nm_rotulo, qt_valor)

        for nm_titulo, lista_status, ic_aberto in (
            ("Com erro (não serão importadas)", (STATUS_ERRO,), True),
            ("Novas (serão cadastradas)", (STATUS_NOVA,), True),
            ("Já cadastradas (serão ignoradas)", (STATUS_EXISTE,), False),
            ("Repetidas na planilha (serão ignoradas)", (STATUS_REPETIDA,), False),
        ):
            df_tabela = _tabela(lista_resultado, lista_status)
            if not df_tabela.empty:
                with st.expander(f"{nm_titulo}: {len(df_tabela)}", expanded=ic_aberto):
                    st.dataframe(df_tabela, hide_index=True, width="stretch")

        ic_atualizar = False
        if qt_diverge:
            ic_atualizar = st.checkbox(
                f"Atualizar os dados de {qt_diverge} cadastro(s) já existente(s) que estão diferentes na planilha",
                key=f"crava_importacao_atualizar_{nr_upload}",
                help="Desmarcado, os cadastros que já existem ficam como estão. Marcado, os dados (exceto o Id Cliente) passam a ser os da planilha.")
        if qt_erros:
            st.caption("As linhas com erro não entram. Corrija na planilha e envie de novo se quiser incluí-las; as demais não são duplicadas.")

        qt_atualizar = qt_diverge if ic_atualizar else 0
        nm_botao = f"Importar {qt_novas} nova(s)" + (f" e atualizar {qt_atualizar}" if qt_atualizar else "")
        if st.button(nm_botao, type="primary", disabled=(qt_novas + qt_atualizar) == 0, key=f"crava_importacao_confirmar_{nr_upload}"):
            st.session_state["crava_importacao_resultado"] = importarCadastro(lista_resultado, ic_atualizar)
            st.session_state["crava_importacao_n"] = nr_upload + 1  # troca a chave do upload: limpa o arquivo
            st.rerun()
