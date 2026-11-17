"""Aba "Importar cadastro" da Solicitação de extratos: lê uma planilha de fundos e cotistas e cadastra no banco.

Regra de duplicidade: um cadastro é a combinação fundo (CNPJ) + cotista (CPF/CNPJ + nome do cotista). CNPJ e CPF/CNPJ são
comparados só por letras e números (pontos, traços e barras não contam); o nome ignora maiúsculas, acentos e espaços a mais.
O nome entra na chave porque cotistas diferentes podem usar o mesmo CPF/CNPJ (ex.: perfis Agressivo, Conservador e Moderado
de um mesmo grupo). O que já existe no banco, ou se repete na própria planilha, não é criado de novo.
"""
import html
import io
import re

import pandas as pd
import streamlit as st

from app.database.extratos import atualizarCadastro, chaveCadastro, incluirCadastro, listarCadastroExistente
from app.utilitarias.importacao_planilha import ErroImportacao, limpar, normalizar

EMAIL_RE = re.compile(r"^[^@\s;,]+@[^@\s;,]+\.[^@\s;,]+$")

# Colunas esperadas na planilha (os nomes aceitam maiúsculas, acentos e espaços diferentes)
COLUNAS_ESPERADAS = [
    {"campo": "fundo", "nome": "Nome do Fundo", "exemplo": "Fundo Exemplo FIA",
     "regra": "Nome do fundo, como deve aparecer nos e-mails.",
     "apelidos": {"nome do fundo", "fundo"}},
    {"campo": "cnpj", "nome": "CNPJ", "exemplo": "12.345.678/0001-95",
     "regra": "CNPJ do fundo, com 14 números (pontos, traço e barra são opcionais).",
     "apelidos": {"cnpj", "cnpj do fundo", "cnpj fundo"}},
    {"campo": "cotista", "nome": "COTISTAS", "exemplo": "COTISTA EXEMPLO LTDA",
     "regra": "Nome do cotista.",
     "apelidos": {"cotistas", "cotista", "nome do cotista"}},
    {"campo": "doc", "nome": "CPF/CNPJ COTISTAS", "exemplo": "123.456.789-09",
     "regra": "CPF (11 números) ou CNPJ (14 números) do cotista.",
     "apelidos": {"cpf/cnpj cotistas", "cpf/cnpj cotista", "cpf/cnpj", "cpf cnpj cotistas", "cpf/cnpj do cotista"}},
    {"campo": "emails", "nome": "emails", "exemplo": "operacoes@exemplo.com.br; backoffice@exemplo.com.br",
     "regra": "Um ou mais e-mails que recebem o pedido, separados por ponto e vírgula.",
     "apelidos": {"emails", "email", "e-mail", "e-mails"}},
]

STATUS_NOVA, STATUS_EXISTE, STATUS_REPETIDA, STATUS_ERRO = "nova", "ja_existe", "repetida", "erro"


def separarEmails(tx_emails):
    """Lista de e-mails sem repetição (ignora maiúsculas), aceitando ; , ou espaço como separador."""
    lista_emails, conjunto_vistos = [], set()
    for ds_email in re.split(r"[;,\s]+", tx_emails or ""):
        if ds_email and ds_email.lower() not in conjunto_vistos:
            conjunto_vistos.add(ds_email.lower())
            lista_emails.append(ds_email)
    return lista_emails


# ---------------------------------------------------------------- leitura e análise (sem tela)
def lerPlanilhaImportacao(arquivo):
    """DataFrame com as colunas fundo, cnpj, cotista, doc, emails e linha (número da linha na planilha)."""
    nm_arquivo = arquivo.name.lower()
    try:
        if nm_arquivo.endswith(".csv"):
            bytes_arquivo = arquivo.getvalue()
            df_bruto = None
            for nm_codificacao in ("utf-8-sig", "latin-1"):
                try:
                    df_bruto = pd.read_csv(io.BytesIO(bytes_arquivo), sep=None, engine="python", dtype=str, encoding=nm_codificacao)
                    break
                except UnicodeDecodeError:
                    continue
            if df_bruto is None:
                raise ErroImportacao("Não consegui ler o CSV (codificação desconhecida). Salve como UTF-8 ou envie em .xlsx.")
        else:
            arquivo_excel = pd.ExcelFile(arquivo)
            lista_abas = arquivo_excel.sheet_names
            nm_aba = next((aba for aba in lista_abas if normalizar(aba) == "dados"), lista_abas[0])
            df_bruto = pd.read_excel(arquivo_excel, sheet_name=nm_aba, dtype=str)
    except ErroImportacao:
        raise
    except Exception as erro:  # noqa: BLE001  (arquivo corrompido, senha, formato errado...)
        raise ErroImportacao(f"Não consegui abrir a planilha: {erro}") from erro

    dic_colunas, lista_faltando = {}, []
    for coluna in COLUNAS_ESPERADAS:
        nm_encontrada = next((nm_coluna for nm_coluna in df_bruto.columns if normalizar(nm_coluna) in coluna["apelidos"]), None)
        if nm_encontrada is None:
            lista_faltando.append(coluna["nome"])
        else:
            dic_colunas[coluna["campo"]] = nm_encontrada
    if lista_faltando:
        raise ErroImportacao(
            f"Faltam colunas na planilha: {', '.join(lista_faltando)}. "
            f"Colunas encontradas: {', '.join(str(nm_coluna) for nm_coluna in df_bruto.columns)}."
        )
    df = pd.DataFrame({campo: df_bruto[nm_coluna].map(limpar) for campo, nm_coluna in dic_colunas.items()})
    df["linha"] = df.index + 2  # linha 1 é o cabeçalho
    return df[(df[["fundo", "cnpj", "cotista", "doc", "emails"]] != "").any(axis=1)].reset_index(drop=True)


def analisarImportacao(df, lista_existentes):
    """Classifica cada linha: nova, ja_existe, repetida (na própria planilha) ou erro. Devolve lista de dicts."""
    dic_existentes, dic_fundo_banco = {}, {}
    for existente in lista_existentes:
        dic_existentes.setdefault((existente["ds_chave_fundo"], existente["ds_chave_cotista"], normalizar(existente["nm_cotista"] or "")), existente)
        dic_fundo_banco.setdefault(existente["ds_chave_fundo"], existente["nm_fundo"])
    dic_fundo_planilha, dic_vistas, lista_resultado = {}, {}, []

    for linha in df.itertuples(index=False):
        lista_erros, lista_avisos = [], []
        nm_fundo, nr_cnpj, nm_cotista, nr_doc = linha.fundo, linha.cnpj, linha.cotista, linha.doc
        lista_emails = separarEmails(linha.emails)
        lista_validos = [ds_email for ds_email in lista_emails if EMAIL_RE.match(ds_email)]
        registro = {"linha": linha.linha, "fundo": nm_fundo, "cnpj": nr_cnpj, "cotista": nm_cotista, "doc": nr_doc,
                    "emails": "; ".join(lista_emails), "status": "", "motivo": "", "id_registro": None, "divergente": False}

        if not nm_fundo:
            lista_erros.append("nome do fundo vazio")
        if len(re.sub(r"\D", "", nr_cnpj)) != 14:
            lista_erros.append("CNPJ do fundo deve ter 14 números")
        if not nm_cotista:
            lista_erros.append("nome do cotista vazio")
        if not nr_doc:
            lista_erros.append("CPF/CNPJ do cotista vazio")
        elif len(re.sub(r"\D", "", nr_doc)) not in (11, 14):
            lista_avisos.append("CPF/CNPJ do cotista com quantidade de números fora do comum (11 ou 14)")
        if not lista_validos:
            lista_erros.append("nenhum e-mail válido")
        elif len(lista_validos) != len(lista_emails):
            lista_avisos.append("há e-mail com formato inválido: " + ", ".join(ds_email for ds_email in lista_emails if ds_email not in lista_validos))

        if lista_erros:
            registro["status"], registro["motivo"] = STATUS_ERRO, "; ".join(lista_erros)
            lista_resultado.append(registro)
            continue

        ds_chave = (chaveCadastro(nr_cnpj), chaveCadastro(nr_doc), normalizar(nm_cotista))
        if ds_chave in dic_vistas:
            registro["status"] = STATUS_REPETIDA
            registro["motivo"] = f"mesmo fundo, CPF/CNPJ e nome de cotista da linha {dic_vistas[ds_chave]['linha']} (ignorada)"
        elif ds_chave in dic_existentes:
            existente = dic_existentes[ds_chave]
            conjunto_banco = {ds_email.lower() for ds_email in separarEmails(existente["ds_emails"] or "")}
            registro["status"], registro["id_registro"] = STATUS_EXISTE, existente["id_registro"]
            registro["divergente"] = conjunto_banco != {ds_email.lower() for ds_email in lista_emails}
            registro["motivo"] = "já cadastrada, com e-mails diferentes" if registro["divergente"] else "já cadastrada"
        else:
            registro["status"] = STATUS_NOVA
            nm_canonico = dic_fundo_banco.get(ds_chave[0]) or dic_fundo_planilha.get(ds_chave[0])
            if nm_canonico and normalizar(nm_canonico) != normalizar(nm_fundo):
                registro["fundo"] = nm_canonico  # mesmo CNPJ já tem nome: mantém um só nome por fundo
                lista_avisos.append(f"nome do fundo ajustado para '{nm_canonico}' (já usado para este CNPJ)")
            dic_fundo_planilha.setdefault(ds_chave[0], registro["fundo"])
            registro["motivo"] = "; ".join(lista_avisos)
        if registro["status"] in (STATUS_EXISTE, STATUS_REPETIDA) and lista_avisos:
            registro["motivo"] += "; " + "; ".join(lista_avisos)
        dic_vistas.setdefault(ds_chave, registro)
        lista_resultado.append(registro)
    return lista_resultado


def importarCadastro(lista_resultado, ic_atualizar):
    """Grava as novas e, se pedido, atualiza as já cadastradas que divergem. Devolve as contagens."""
    lista_novas = [(r["fundo"], r["cnpj"], r["cotista"], r["doc"], r["emails"]) for r in lista_resultado if r["status"] == STATUS_NOVA]
    qt_incluidas = incluirCadastro(lista_novas)
    lista_atualizar = [(r["emails"], r["id_registro"]) for r in lista_resultado
                       if ic_atualizar and r["status"] == STATUS_EXISTE and r["divergente"]]
    atualizarCadastro(lista_atualizar)
    return {"incluidas": qt_incluidas, "atualizadas": len(lista_atualizar), "ja_existiam_agora": len(lista_novas) - qt_incluidas}


def gerarModelo():
    """Planilha modelo: aba Dados (só o cabeçalho, é a que o app lê) e aba Exemplo (linhas fictícias)."""
    lista_colunas = [coluna["nome"] for coluna in COLUNAS_ESPERADAS]
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as escritor:
        pd.DataFrame(columns=lista_colunas).to_excel(escritor, sheet_name="Dados", index=False)
        pd.DataFrame([[coluna["exemplo"] for coluna in COLUNAS_ESPERADAS]], columns=lista_colunas).to_excel(
            escritor, sheet_name="Exemplo", index=False)
        for planilha in escritor.book.worksheets:
            for letra, largura in zip("ABCDE", (28, 22, 30, 24, 50)):
                planilha.column_dimensions[letra].width = largura
    return buffer.getvalue()


# ---------------------------------------------------------------- tela
def _kpi(tx_rotulo, valor, tipo=""):
    return f'<div class="kpi {tipo}"><div class="kpi-val">{valor}</div><div class="kpi-lbl">{html.escape(tx_rotulo)}</div></div>'


def _tabela(lista_resultado, lista_status):
    lista_linhas = [{"Linha": r["linha"], "Fundo": r["fundo"], "CNPJ": r["cnpj"], "Cotista": r["cotista"], "CPF/CNPJ": r["doc"],
                     "E-mails": r["emails"], "Observação": r["motivo"]} for r in lista_resultado if r["status"] in lista_status]
    return pd.DataFrame(lista_linhas)


def abaImportar():
    ds_resultado = st.session_state.pop("importacao_resultado", None)
    if ds_resultado:
        lista_partes = [f"{ds_resultado['incluidas']} cadastro(s) novo(s) incluído(s)"]
        if ds_resultado["atualizadas"]:
            lista_partes.append(f"{ds_resultado['atualizadas']} atualizado(s)")
        if ds_resultado["ja_existiam_agora"]:
            lista_partes.append(f"{ds_resultado['ja_existiam_agora']} já tinham sido cadastrado(s) por outra pessoa e foram ignorados")
        st.success("Importação concluída: " + "; ".join(lista_partes) + ".")

    with st.container(border=True, key="card_lista"):
        st.markdown('<div class="card-title">Importar cadastro de fundos e cotistas</div>'
                    '<div class="card-hint">Envie uma planilha (.xlsx, .xls ou .csv) com uma linha por fundo + cotista. '
                    "Antes de gravar, o portal mostra o que vai entrar.</div>", unsafe_allow_html=True)
        lista_linhas_html = "".join(
            f"<tr><td class='fundo'>{html.escape(coluna['nome'])}</td><td>Sim</td><td>{html.escape(coluna['exemplo'])}</td>"
            f"<td>{html.escape(coluna['regra'])}</td></tr>" for coluna in COLUNAS_ESPERADAS)
        st.markdown('<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Coluna</th><th>Obrigatória</th><th>Exemplo</th><th>Regra</th></tr></thead>'
                    f"<tbody>{lista_linhas_html}</tbody></table></div>", unsafe_allow_html=True)
        st.markdown(
            "**Como evita duplicados**\n"
            "- Um cadastro é a combinação **fundo (CNPJ) + cotista (CPF/CNPJ + nome do cotista)**. Cotistas com nomes diferentes "
            "são cadastros diferentes, mesmo usando o mesmo CPF/CNPJ (por exemplo, os perfis Agressivo, Conservador e Moderado).\n"
            "- Pontos, traços e barras não contam: `48.307.294/0001-25` e `48307294000125` são o mesmo CNPJ. "
            "No nome, maiúsculas, acentos e espaços a mais também não contam.\n"
            "- Se a combinação **já está cadastrada**, ela **não é criada de novo**. Se só os e-mails forem diferentes, "
            "você escolhe se quer atualizá-los (por padrão, não mexe).\n"
            "- Se a combinação **se repete dentro da própria planilha** (mesmo fundo, CPF/CNPJ e nome), só a primeira linha vale.\n"
            "- Fundo com o mesmo CNPJ de um já cadastrado usa o nome que já existe.\n"
            "- Linhas com campo obrigatório vazio, CNPJ do fundo inválido ou sem nenhum e-mail válido **não são importadas**."
        )
        st.download_button("Baixar planilha modelo", gerarModelo(), file_name="modelo_cadastro_fundos_cotistas.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", icon=":material/download:")

    with st.container(border=True, key="card_conf"):
        nr_upload = st.session_state.setdefault("importacao_n", 0)
        arquivo = st.file_uploader("Planilha de cadastro", type=["xlsx", "xls", "csv"], key=f"upload_cadastro_{nr_upload}")
        if arquivo is None:
            st.caption("Escolha a planilha para ver a conferência antes de importar.")
            return
        try:
            df = lerPlanilhaImportacao(arquivo)
            lista_existentes = listarCadastroExistente()
        except ErroImportacao as erro:
            st.error(str(erro))
            return
        if df.empty:
            st.warning("A planilha não tem nenhuma linha com dados.")
            return

        lista_resultado = analisarImportacao(df, lista_existentes)
        qt_novas = sum(r["status"] == STATUS_NOVA for r in lista_resultado)
        qt_existem = sum(r["status"] == STATUS_EXISTE for r in lista_resultado)
        qt_diverge = sum(r["status"] == STATUS_EXISTE and r["divergente"] for r in lista_resultado)
        qt_repetidas = sum(r["status"] == STATUS_REPETIDA for r in lista_resultado)
        qt_erros = sum(r["status"] == STATUS_ERRO for r in lista_resultado)

        colunas_kpi = st.columns(5)
        colunas_kpi[0].markdown(_kpi("Linhas lidas", len(lista_resultado)), unsafe_allow_html=True)
        colunas_kpi[1].markdown(_kpi("Novas", qt_novas, "ok"), unsafe_allow_html=True)
        colunas_kpi[2].markdown(_kpi("Já cadastradas", qt_existem), unsafe_allow_html=True)
        colunas_kpi[3].markdown(_kpi("Repetidas", qt_repetidas), unsafe_allow_html=True)
        colunas_kpi[4].markdown(_kpi("Com erro", qt_erros, "warn" if qt_erros else ""), unsafe_allow_html=True)
        st.write("")

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
                f"Atualizar os e-mails de {qt_diverge} cadastro(s) já existente(s) que estão diferentes na planilha",
                key=f"importacao_atualizar_{nr_upload}",
                help="Desmarcado, os cadastros que já existem ficam como estão. Marcado, os e-mails passam a ser os da planilha.")
        if qt_erros:
            st.caption("As linhas com erro não entram. Corrija na planilha e envie de novo se quiser incluí-las; as demais não são duplicadas.")

        qt_atualizar = qt_diverge if ic_atualizar else 0
        nm_botao = f"Importar {qt_novas} nova(s)" + (f" e atualizar {qt_atualizar}" if qt_atualizar else "")
        if st.button(nm_botao, type="primary", disabled=(qt_novas + qt_atualizar) == 0, key=f"importacao_confirmar_{nr_upload}"):
            st.session_state["importacao_resultado"] = importarCadastro(lista_resultado, ic_atualizar)
            st.session_state["importacao_n"] = nr_upload + 1  # troca a chave do upload: limpa o arquivo
            st.rerun()
