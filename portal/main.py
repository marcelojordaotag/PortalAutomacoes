import json
import unicodedata
from datetime import date

import pandas as pd
import streamlit as st

from app.ambiente.config_ambiente import diretorio_base, diretorio_dados, inicializarAmbiente
from app.seguranca import controle_acesso
from app.seguranca.registro_acessos import registrarUsoPagina
from app.utilitarias.tema import COR, aplicarTema, topo
from app.utilitarias.versoes import rotulo

inicializarAmbiente()

LOGO = diretorio_base / "app" / "assets" / "logo_tag.png"
PLANILHA_EXTRATOS = diretorio_dados / "extratos" / "Template_Fundos_Ativos.xlsx"
ARQUIVO_SOLICITACOES = diretorio_dados / "solicitacoes" / "solicitacoes.json"
ARQUIVO_ERROS = diretorio_dados / "boletador" / "controle_erros.json"

st.set_page_config(
    page_title="Portal | TAG Investimentos",
    page_icon=str(LOGO),
    layout="wide",
    initial_sidebar_state="expanded",
)


def seloExtratos():
    try:
        qt_linhas = len(pd.read_excel(PLANILHA_EXTRATOS, dtype=str).dropna(how="all"))
    except (OSError, ValueError):
        return '<span class="badge warn">PLANILHA NÃO ENCONTRADA</span>'
    return f'<span class="badge ok">{qt_linhas} LINHAS NA PLANILHA</span>'


def seloSolicitacoes():
    try:
        regs = json.loads(ARQUIVO_SOLICITACOES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return '<span class="badge neutro">SEM DADOS</span>'
    qt_pendentes = sum(1 for registro in regs if registro.get("status") != "Concluído")
    if qt_pendentes:
        return f'<span class="badge warn">{qt_pendentes} NÃO CONCLUÍDA(S)</span>'
    return '<span class="badge ok">SEM PENDÊNCIAS</span>'


def seloBoletas():
    try:
        cards = json.loads(ARQUIVO_ERROS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return '<span class="badge neutro">SEM DADOS</span>'
    abertos = [card for card in cards if card.get("coluna") != "Solucionados"]
    criticos = [card for card in abertos if str(card.get("prioridade", "")).startswith("Cr")]
    if criticos:
        return f'<span class="badge div">{len(criticos)} CRÍTICO(S) EM ABERTO</span>'
    if abertos:
        return f'<span class="badge warn">{len(abertos)} PROBLEMA(S) EM ABERTO</span>'
    return '<span class="badge ok">SEM PENDÊNCIAS</span>'


pg_home = st.Page(lambda: paginaHome(), title="Home", default=True)
pg_extratos = st.Page("app/paginas/extratos/pagina.py", title="Solicitação de extratos", url_path="extratos")
pg_boletador = st.Page("app/paginas/boletador/pagina.py", title="Mesa de Boletas", url_path="boletas")
pg_solicitacoes = st.Page("app/paginas/solicitacoes/pagina.py", title="Registro de Solicitações", url_path="solicitacoes")
pg_britech = st.Page("app/paginas/britech/pagina.py", title="Rentabilidade e Cotas", url_path="rentabilidade")
pg_bradesco = st.Page("app/paginas/bradesco_miami/pagina.py", title="Transactions Offshore", url_path="bradesco-miami")
pg_externos = st.Page("app/paginas/processos_externos/pagina.py", title="Registro Solicitações de Fechamento", url_path="processos-externos")
pg_caixa = st.Page("app/paginas/conciliacao_caixa/pagina.py", title="Conciliação de Caixa", url_path="caixa")
pg_crava = st.Page("app/paginas/crava_cotas/pagina.py", title="CRAVA COTAS", url_path="crava-cotas")

# Para incluir uma nova ferramenta: crie a st.Page acima e acrescente uma linha aqui e em st.navigation.
FERRAMENTAS = [
    {
        "chave": "extratos", "sigla": "SE", "titulo": "Solicitação de extratos", "pagina": pg_extratos,
        "descricao": "Envio de e-mails, acompanhamento e conciliação dos extratos de cotistas.", "selo": seloExtratos,
    },
    {
        "chave": "boletas", "sigla": "MB", "titulo": "Mesa de Boletas", "pagina": pg_boletador,
        "descricao": "Conciliação de boletas, controle de erros e importação da base.", "selo": seloBoletas,
    },
    {
        "chave": "solicitacoes", "sigla": "RS", "titulo": "Registro de Solicitações", "pagina": pg_solicitacoes,
        "descricao": "Conclusão das demandas, histórico e análise de prazos.", "selo": seloSolicitacoes,
    },
    {
        "chave": "processos_externos", "sigla": "PE", "titulo": "Registro Solicitações de Fechamento", "pagina": pg_externos,
        "descricao": "Para outras áreas: abra solicitações ao processamento e acompanhe o andamento.",
        "selo": lambda: '<span class="badge neutro">OUTRAS ÁREAS</span>',
    },
    {
        "chave": "rentabilidade", "sigla": "RC", "titulo": "Rentabilidade e Cotas", "pagina": pg_britech,
        "descricao": "Conferência do PL com a cota e monitor da rentabilidade diária (API Britech).",
        "selo": lambda: '<span class="badge neutro">API BRITECH</span>',
    },
    {
        "chave": "bradesco", "sigla": "BM", "titulo": "Transactions Offshore", "pagina": pg_bradesco,
        "descricao": "Tratamento dos arquivos de transações (Bradesco Miami e BTG US): filtros, janela D-2 e cliente.",
        "selo": lambda: '<span class="badge neutro">EXCEL</span>',
    },
    {
        "chave": "caixa", "sigla": "CC", "titulo": "Conciliação de Caixa", "pagina": pg_caixa,
        "descricao": "Diferenças de caixa TAG x administradora: OBS por categoria, status e alerta fora de ±1.",
        "selo": lambda: '<span class="badge neutro">EXCEL</span>',
    },
    {
        "chave": "crava_cotas", "sigla": "CR", "titulo": "CRAVA COTAS", "pagina": pg_crava,
        "descricao": "Busca de informações do backoffice (pré-processamento) via Playwright.",
        "selo": lambda: '<span class="badge neutro">BACKOFFICE</span>',
    },
]
COLUNAS = 3

# Apps desligados por enquanto: somem da home, do menu e da busca (para religar, tire a chave daqui).
APPS_DESATIVADOS = {"caixa"}
FERRAMENTAS[:] = [ferramenta for ferramenta in FERRAMENTAS if ferramenta["chave"] not in APPS_DESATIVADOS]


# Categoria e palavras-chave extras de cada ferramenta (chave de FERRAMENTAS -> (categoria, palavras para a busca)).
# Ferramenta nova sem entrada aqui aparece na categoria "Outros".
CATEGORIAS = {
    "extratos": ("Operações", "extrato cotista envio email conciliacao planilha"),
    "boletas": ("Operações", "boleta ordem mesa erro conciliacao importar"),
    "rentabilidade": ("Análise", "rentabilidade cota pl britech api monitor"),
    "bradesco": ("Operações", "transactions offshore miami btg us arquivo"),
    "solicitacoes": ("Processamento", "solicitacao demanda chamado ajuste fechamento duvida registro historico"),
    "processos_externos": ("Processamento", "processos externos solicitar demanda outras areas abrir chamado"),
    "caixa": ("Conciliação", "caixa conciliacao saldo"),
    "crava_cotas": ("Operações", "crava cotas backoffice pre-processamento playwright"),
}
DIAS_SEMANA = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]

CSS_HOME = f"""
<style>
.faixa-home {{ margin: .2rem 0 1rem; }}
[class*="st-key-busca_home"] input {{
    border: 1.5px solid {COR['borda']}; border-radius: 12px; padding: .85rem 1.1rem; font-size: 1rem;
    background: #fff; box-shadow: 0 2px 8px rgba(74, 10, 30, .06);
}}
[class*="st-key-busca_home"] input:focus {{ border-color: {COR['vinho']}; box-shadow: 0 0 0 3px {COR['vinho_claro']}; }}
[class*="st-key-cat_home"] label {{ font-size: .85rem; }}
.cartao-cat {{ font-size: .66rem; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; color: {COR['dourado']}; }}
.home-contagem {{ color: {COR['texto_suave']}; font-size: .82rem; margin: .1rem 0 .8rem; }}
.home-vazio {{
    background: #fff; border: 1px dashed {COR['borda']}; border-radius: 12px; padding: 2rem 1.5rem; text-align: center;
    color: {COR['texto_suave']};
}}
.home-vazio b {{ color: {COR['vinho']}; }}
</style>
"""


def _norm(txt):
    """Minúsculo e sem acento, para a busca não depender de maiúsculas ou acentuação."""
    return unicodedata.normalize("NFKD", txt or "").encode("ascii", "ignore").decode().lower()


def _categoria(ferramenta):
    return CATEGORIAS.get(ferramenta["chave"], ("Outros", ""))[0]


def _casaBusca(ferramenta, termos, categoria):
    cat, palavras = CATEGORIAS.get(ferramenta["chave"], ("Outros", ""))
    alvo = _norm(" ".join([ferramenta["titulo"], ferramenta["descricao"], cat, palavras]))
    return all(termo in alvo for termo in termos) and categoria in ("Todas", cat)


def paginaHome():
    primeiro_nome = ((st.session_state.get("auth") or {}).get("nome") or "").split(" ")[0]
    saudacao = f"Olá, {primeiro_nome}. " if primeiro_nome else ""
    topo("Portal TAG", f"{saudacao}Todas as ferramentas em um só lugar", app="portal")
    st.markdown(CSS_HOME, unsafe_allow_html=True)

    selos = {ferramenta["chave"]: ferramenta["selo"]() for ferramenta in FERRAMENTAS}
    hoje = date.today()
    dia = DIAS_SEMANA[hoje.weekday()]
    dia_txt = dia if dia in ("sábado", "domingo") else f"{dia}-feira"
    st.markdown(
        '<div class="kpis faixa-home">'
        f'<div class="kpi"><div class="kpi-label">Ferramentas</div><div class="kpi-valor">{len(FERRAMENTAS)}</div>'
        '<div class="kpi-sub">disponíveis no portal</div></div>'
        f'<div class="kpi"><div class="kpi-label">Hoje</div><div class="kpi-valor" style="font-size:1.5rem;line-height:1.7">'
        f'{hoje.strftime("%d/%m/%Y")}</div><div class="kpi-sub">{dia_txt}</div></div>'
        "</div>",
        unsafe_allow_html=True,
    )

    termo = st.text_input(
        "Buscar ferramenta", key="busca_home", label_visibility="collapsed",
        placeholder="Buscar ferramenta: extrato, boleta, cota, solicitação, caixa…",
    )
    categorias = ["Todas"] + sorted({_categoria(ferramenta) for ferramenta in FERRAMENTAS})
    categoria = st.radio("Categoria", categorias, horizontal=True, key="cat_home", label_visibility="collapsed")

    termos = _norm(termo).split()
    visiveis = [ferramenta for ferramenta in FERRAMENTAS if _casaBusca(ferramenta, termos, categoria)]
    st.markdown(
        f'<p class="home-contagem">Mostrando {len(visiveis)} de {len(FERRAMENTAS)} ferramentas</p>', unsafe_allow_html=True
    )

    if not visiveis:
        st.markdown(
            '<div class="home-vazio"><b>Nenhuma ferramenta encontrada.</b><br>'
            "Tente outra palavra ou escolha a categoria <b>Todas</b>.</div>",
            unsafe_allow_html=True,
        )
        return

    for ordem_item in range(0, len(visiveis), COLUNAS):
        colunas = st.columns(COLUNAS)
        for col, ferramenta in zip(colunas, visiveis[ordem_item : ordem_item + COLUNAS]):
            with col, st.container(key=f"cartao_{ferramenta['chave']}"):
                st.markdown(
                    f'<div class="cartao-sigla">{ferramenta["sigla"]}</div>'
                    f'<span class="cartao-cat">{_categoria(ferramenta)}</span>'
                    f'<p class="cartao-titulo">{ferramenta["titulo"]}</p>{selos[ferramenta["chave"]]}'
                    f'<span class="versao-cartao">{rotulo(ferramenta["chave"])}</span>'
                    f'<p class="cartao-desc">{ferramenta["descricao"]}</p>',
                    unsafe_allow_html=True,
                )
                st.page_link(ferramenta["pagina"], label="Abrir")


CSS_MENU_BASE = f"""
<style>
/* Itens do menu: selo com a sigla da ferramenta + nome */
[data-testid="stSidebarNavLink"] {{ display: flex !important; align-items: center; gap: .75rem; padding: .5rem .8rem !important; }}
[data-testid="stSidebarNavLink"]::before {{
    flex: none; width: 30px; height: 30px; border-radius: 9px; display: flex; align-items: center; justify-content: center;
    background: rgba(255, 255, 255, .13); border-bottom: 2px solid {COR['dourado']};
    color: #fff; font-size: .64rem; font-weight: 700; letter-spacing: .05em; font-family: 'Inter', system-ui, sans-serif;
    transition: background .15s ease, color .15s ease;
}}
[data-testid="stSidebarNavLink"]:hover::before {{ background: rgba(255, 255, 255, .24); }}
[data-testid="stSidebarNavLink"][aria-current="page"]::before {{ background: {COR['dourado']}; color: {COR['vinho_escuro']}; }}
[data-testid="stSidebarNavLink"] span {{ font-size: .93rem; line-height: 1.25; }}
[data-testid="stSidebarNavLink"][aria-current="page"] span {{ font-weight: 700; }}

/* Cabeçalho das seções, com linha dourada discreta */
[data-testid="stNavSectionHeader"] {{
    border-top: 1px solid rgba(184, 146, 74, .35); margin-top: .5rem; padding-top: .9rem !important;
}}
[data-testid="stSidebarNavItems"] > div:first-child [data-testid="stNavSectionHeader"] {{ border-top: none; margin-top: 0; }}

/* Botão de envio de formulário: texto branco sobre o vinho em qualquer página */
[data-testid="stFormSubmitButton"] button[kind="primaryFormSubmit"] p {{ color: #fff !important; font-weight: 600; }}
[data-testid="stFormSubmitButton"] button[kind="primaryFormSubmit"]:hover {{ background: {COR['vinho_medio']}; border-color: {COR['vinho_medio']}; }}

/* Rodapé */
.rodape-menu {{
    margin: 1.2rem 1.3rem 1rem; padding-top: .9rem; border-top: 1px solid rgba(184, 146, 74, .45);
    font-size: .74rem; line-height: 1.5; color: #E9CFD7; opacity: .9;
}}
.rodape-menu b {{ color: #fff; font-weight: 600; letter-spacing: .02em; }}
.rodape-menu span {{ color: {COR['dourado']}; letter-spacing: .04em; }}
</style>
"""


def cssMenu():
    """Base do menu + a sigla de cada ferramenta (lida de FERRAMENTAS, então ferramenta nova já entra sozinha)."""
    regras = ['[data-testid="stSidebarNavItems"] > div:first-child [data-testid="stSidebarNavLink"]::before { content: "\\2302"; font-size: .95rem; }']
    for ferramenta in FERRAMENTAS:
        regras.append(f'[data-testid="stSidebarNavLink"][href$="/{ferramenta["pagina"].url_path}"]::before {{ content: "{ferramenta["sigla"]}"; }}')
    regras.append('[data-testid="stSidebarNavLink"][href$="/conta"]::before { content: "MC"; }')
    regras.append('[data-testid="stSidebarNavLink"][href$="/usuarios"]::before { content: "US"; }')
    regras.append('[data-testid="stSidebarNavLink"][href$="/acessos"]::before { content: "AC"; }')
    return CSS_MENU_BASE + "<style>" + " ".join(regras) + "</style>"


aplicarTema()  # uma vez, vale para todas as páginas
usuario = controle_acesso.exigirLogin()  # sem sessão válida mostra o login e interrompe aqui
_liberados = controle_acesso.appsPermitidos(usuario, [ferramenta["chave"] for ferramenta in FERRAMENTAS])
FERRAMENTAS[:] = [ferramenta for ferramenta in FERRAMENTAS if ferramenta["chave"] in _liberados]  # cada pessoa só vê (e acessa) o que foi liberado
st.markdown(cssMenu(), unsafe_allow_html=True)
st.logo(str(LOGO), size="large")
grupos = {"Início": [pg_home]}
for _cat in sorted({_categoria(ferramenta) for ferramenta in FERRAMENTAS}):
    grupos[_cat] = [ferramenta["pagina"] for ferramenta in FERRAMENTAS if _categoria(ferramenta) == _cat]
paginas_conta = [st.Page(controle_acesso.paginaMinhaConta, title="Minha conta", url_path="conta")]
if usuario["perfil"] == "admin":
    paginas_conta.append(st.Page(controle_acesso.paginaUsuarios, title="Usuários", url_path="usuarios"))
    paginas_conta.append(st.Page("app/paginas/acessos/pagina.py", title="Acessos e uso", url_path="acessos"))
grupos["Conta"] = paginas_conta
pg = st.navigation(grupos)
st.markdown(controle_acesso.CSS_BLOCO_USUARIO, unsafe_allow_html=True)
controle_acesso.blocoUsuario(usuario)
st.sidebar.markdown(
    f'<div class="rodape-menu"><b>Portal TAG Investimentos</b><br><span>{rotulo("portal")}</span></div>',
    unsafe_allow_html=True,
)
controle_acesso.vigiaSessao()
registrarUsoPagina(usuario["usuario"], pg.title)
pg.run()
