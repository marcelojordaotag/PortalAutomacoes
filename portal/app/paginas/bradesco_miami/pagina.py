"""Transactions Offshore (Streamlit): Bradesco Miami, BTG US e Morgan Stanley (MS)

Tratamento dos arquivos Transactions_<banco> (mesmas regras para os dois bancos; só muda a pasta, o nome do
arquivo e o que a coluna Client mostra quando a conta não está no De-Para):
  1. apaga as linhas iniciais (1 a 6), e o cabeçalho passa a ser a linha 1;
  2. localiza "Date" e "Settlement Date" pelo nome (não pela posição) e as move para A e B;
  3. remove colunas vazias, sem deixar lacunas;
  4. apaga a coluna "Account Nickname";
  5. mantém só as linhas cuja "Activity Description" contém Buy ou Sell;
  6. mantém os Settlement Date de D-2 (dias úteis, sem feriados do Brasil) a partir da data do arquivo em diante, inclusive datas futuras; Settlement Date vazio também entra;
  7. descarta todas as colunas depois de "Details" (ela é mantida);
  8. cria a coluna "Client" (primeira coluna) buscando a Account na aba "De-Para Contas" do modelo
     (a mesma busca da planilha do modelo: Bradesco Miami escreve "erro" se a conta não existir; BTG US deixa vazio).

Morgan Stanley (MS e MS2) segue as mesmas regras, ajustadas ao layout do arquivo: Transaction Date e Activity Date
fazem o papel de Date e Settlement Date, o filtro é Sold/Bought na coluna "Activity", não há coluna Details (todas
ficam) e o Client busca os últimos 10 caracteres da Account no "Account Code" do De-Para (conta não achada: vazio).

Colunas de data saem como data abreviada (no Excel, o formato de data curta do sistema). Na aba Todos, o botão
"Montar e-mail no Gmail" cria o rascunho do Daily Report com uma tabela por banco (só os que têm linhas).
"""
import html
import io
import re
from datetime import date, datetime

import pandas as pd
from dateutil.easter import easter
import streamlit as st

from app.paginas.bradesco_miami import arquivos_drive
from app.utilitarias import email_gmail
from app.utilitarias.tema import aplicarTema, topo

ABA_DEPARA = "De-Para Contas"
COLUNA_DEPARA_CONTA, COLUNA_DEPARA_CLIENTE = "Number", "Account"  # colunas B e E da aba
# Por banco: pasta dentro de <ano>/<Mês>, início do nome do arquivo e o Client quando a conta não está no De-Para
FILTRO_MS = r"(?<![A-Za-z])(?:sold|bought)(?![A-Za-z])"  # palavra inteira: Sold ou Bought
BANCOS = {
    "Bradesco Miami": {"pasta": "Bradesco Miami", "prefixo": "Transactions_Bradesco_Miami", "sem_cliente": "erro"},
    "BTG US": {"pasta": "BTG US", "prefixo": "Transactions_BTG_US", "sem_cliente": ""},
    # As duas exportações do Morgan Stanley ficam na mesma pasta ("Transactions_MS - " e "Transactions_MS2 - ") e são
    # tratadas e exibidas juntas
    "MS": {"pasta": "MS", "prefixos": ["Transactions_MS", "Transactions_MS2"], "sem_cliente": "", "tipo": "ms",
           # layout do arquivo do MS: Transaction Date e Activity Date fazem o papel de Date e Settlement Date;
           # o filtro usa Sold/Bought na coluna Activity; não há coluna Details (todas as colunas ficam)
           "iniciais": ["Transaction Date", "Activity Date"], "filtro": ("Activity", FILTRO_MS), "ultima": None},
}
FORMATO_DATA_EXCEL = "mm-dd-yy"  # formato interno do Excel para "data abreviada": segue a configuração regional
CHARS_CONTA_MS = 10  # RIGHT(Account, 10) da fórmula do modelo
COLUNA_DEPARA_CODIGO = "Account Code"  # coluna D do De-Para, usada na busca do MS
MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro",
         "Novembro", "Dezembro"]
LINHAS_INICIAIS = 6
COLUNAS_INICIAIS = ["Date", "Settlement Date"]
COLUNA_APAGAR = "Account Nickname"
COLUNA_FILTRO = "Activity Description"
ULTIMA_COLUNA = "Details"  # o que vier depois dela é ignorado
DIAS_UTEIS_ATRAS = 2  # janela do Settlement Date: da data mais recente até D-2


def feriadosBrasil(anos):
    """Feriados nacionais do Brasil (os mesmos do calendário ANBIMA): fixos e os que dependem da Páscoa."""
    datas = []
    for ano in anos:
        pascoa = pd.Timestamp(easter(ano))
        datas += [pd.Timestamp(ano, mes, dia) for mes, dia in
                  [(1, 1), (4, 21), (5, 1), (9, 7), (10, 12), (11, 2), (11, 15), (12, 25)]]
        if ano >= 2024:
            datas.append(pd.Timestamp(ano, 11, 20))  # Consciência Negra (nacional a partir de 2024)
        datas += [pascoa - pd.Timedelta(days=48), pascoa - pd.Timedelta(days=47),  # Carnaval (segunda e terça)
                  pascoa - pd.Timedelta(days=2),  # Sexta-feira Santa
                  pascoa + pd.Timedelta(days=60)]  # Corpus Christi
    return datas


DIA_UTIL = pd.offsets.CustomBusinessDay(holidays=feriadosBrasil(range(2020, 2036)))  # pula fds e feriados
FILTRO_TEXTO = r"(?<![A-Za-z])(?:buy|sell)(?![A-Za-z])"  # palavra inteira, sem diferenciar maiúsculas de minúsculas

# set_page_config fica no portal (home.py)
aplicarTema()


def _norm(nome):
    return " ".join(str(nome).lower().split())


def _contaDoTopo(topo_arq):
    """Conta do cabeçalho do arquivo ("Account: 3GM035855"); None se for ALL_ACCOUNTS ou não existir."""
    for valor_celula in topo_arq.to_numpy().ravel():
        achou = re.match(r"\s*Account:\s*(\S+)", str(valor_celula))
        if achou and achou.group(1).upper() != "ALL_ACCOUNTS":
            return achou.group(1)
    return None


def _acharColuna(colunas, nome):
    """Acha a coluna pelo nome, ignorando maiúsculas/minúsculas e espaços extras."""
    alvo = _norm(nome)
    for coluna in colunas:
        if _norm(coluna) == alvo:
            return coluna
    raise ValueError(f"Coluna '{nome}' não encontrada. Colunas: {[str(coluna) for coluna in colunas]}")


def _chaveConta(valor):
    """Número da conta como texto (no De-Para há contas em texto e em número)."""
    return str(valor).strip().casefold()


@st.cache_data(ttl=300, show_spinner=False)
def carregarDepara(login):
    """Lê a aba De-Para Contas do modelo e devolve dois mapas conta -> cliente:
    "numero" (coluna Number: Bradesco e BTG) e "codigo" (coluna Account Code: Morgan Stanley).
    Em chave repetida vale a primeira linha, como no XLOOKUP/VLOOKUP."""
    pasta_trabalho = arquivos_drive.abrirModelo(login)
    try:
        linhas = pasta_trabalho[ABA_DEPARA].iter_rows(values_only=True)
        cab = [_norm(coluna) for coluna in next(linhas)]
        i_cli = cab.index(_norm(COLUNA_DEPARA_CLIENTE))
        indices = {"numero": cab.index(_norm(COLUNA_DEPARA_CONTA)), "codigo": cab.index(_norm(COLUNA_DEPARA_CODIGO))}
        mapas = {nome: {} for nome in indices}
        for linha_depara in linhas:
            cliente = "" if linha_depara[i_cli] is None else str(linha_depara[i_cli])
            for nome, ordem_item in indices.items():
                if linha_depara[ordem_item] is not None and str(linha_depara[ordem_item]).strip():
                    mapas[nome].setdefault(_chaveConta(linha_depara[ordem_item]), cliente)
    finally:
        pasta_trabalho.close()
    return mapas


def tratar(arquivo, depara, configuracao_item, mais_recente=None):
    sem_cliente = configuracao_item["sem_cliente"]
    ms = configuracao_item.get("tipo") == "ms"
    iniciais_cfg = configuracao_item.get("iniciais", COLUNAS_INICIAIS)
    col_filtro, regex_filtro = configuracao_item.get("filtro", (COLUNA_FILTRO, FILTRO_TEXTO))
    ultima_cfg = configuracao_item.get("ultima", ULTIMA_COLUNA)
    # openpyxl lê a grade exatamente como está no Excel (o pandas descarta linhas vazias do topo)
    planilha_aba = arquivos_drive.abrirPlanilha(arquivo).worksheets[0]
    grade = pd.DataFrame(list(planilha_aba.iter_rows(values_only=True)))
    conta_topo = _contaDoTopo(grade.iloc[:LINHAS_INICIAIS])
    bruto = grade.iloc[LINHAS_INICIAIS:].reset_index(drop=True)
    bruto.columns = bruto.iloc[0]  # a primeira linha restante é o cabeçalho
    df = bruto.iloc[1:].reset_index(drop=True)
    df.columns.name = None

    df = df.loc[:, df.columns.notna()]  # colunas sem título (ex.: coluna A vazia)
    df = df.dropna(axis=0, how="all").reset_index(drop=True)
    if not df.empty:  # arquivo só com cabeçalho (dia sem movimento): mantém as colunas
        df = df.dropna(axis=1, how="all")

    iniciais = [_acharColuna(df.columns, nome_coluna) for nome_coluna in iniciais_cfg]
    for coluna in iniciais:  # alguns arquivos trazem texto vazio ("") no lugar de célula vazia
        df[coluna] = pd.to_datetime(df[coluna].replace(r"^\s*$", None, regex=True), errors="coerce")
    df = df[iniciais + [coluna for coluna in df.columns if coluna not in iniciais]]

    df = df.drop(columns=[coluna for coluna in df.columns if _norm(coluna) == _norm(COLUNA_APAGAR)])

    # Arquivo de uma conta só não traz a coluna Account: usa a conta do cabeçalho ("Account: 3GM...")
    if not any(_norm(coluna) == "account" for coluna in df.columns) and conta_topo:
        df.insert(len(iniciais_cfg), "Account", conta_topo)

    # Janela do Settlement Date, a partir da data mais recente da planilha (antes do filtro Buy/Sell)
    liquidacao = pd.to_datetime(df[iniciais[1]], errors="coerce")
    if mais_recente is None:  # sem referência externa: a data mais recente deste arquivo
        mais_recente = liquidacao.max().normalize() if liquidacao.notna().any() else None
    if mais_recente is not None and pd.notna(mais_recente):
        limite = mais_recente - DIAS_UTEIS_ATRAS * DIA_UTIL
        dia = liquidacao.dt.normalize()
        # Settlement Date vazio e liquidações futuras (depois da data do arquivo) também entram
        df = df[liquidacao.isna() | (dia >= limite)]

    col = _acharColuna(df.columns, col_filtro)
    mantem = df[col].astype(str).str.contains(regex_filtro, case=False, regex=True, na=False)
    df = df[mantem].reset_index(drop=True)      

    if ultima_cfg:
        ultima = list(df.columns).index(_acharColuna(df.columns, ultima_cfg))
        df = df.iloc[:, : ultima + 1]

    # Client: a mesma busca da planilha (conta não encontrada -> sem_cliente: "erro" ou vazio, conforme o banco)
    conta = _acharColuna(df.columns, "Account")
    if ms:  # MS: os últimos 10 caracteres da Account contra o Account Code do De-Para
        busca = lambda valor_conta: depara["codigo"].get(_chaveConta(str(valor_conta).strip()[-CHARS_CONTA_MS:]), sem_cliente)
    else:
        busca = lambda valor_conta: depara["numero"].get(_chaveConta(valor_conta), sem_cliente)
    df.insert(0, "Client", df[conta].map(busca))
    return df


def tratarBanco(banco, arquivos, depara):
    """Trata os arquivos do banco (um, ou os dois do MS) e junta o resultado numa tabela só."""
    configuracao_item = BANCOS[banco]
    # Os arquivos trazem liquidações futuras (ex.: D+2), então a janela (D-2) parte da data do arquivo, não da maior
    # Settlement Date da planilha. Nome sem data: usa a data mais recente da própria planilha.
    achou = re.search(r"(\d{8})(?:_\w+)?\.xlsx$", arquivos[0].name)
    mais_recente = pd.Timestamp(datetime.strptime(achou.group(1), "%Y%m%d")) if achou else None
    tabelas = [tratar(arquivo, depara, configuracao_item, mais_recente) for arquivo in arquivos]
    if len(tabelas) == 1:
        return tabelas[0]
    tabelas = [tabela for tabela in tabelas if len(tabela)] or tabelas[:1]  # tabela vazia não entra na junção
    return pd.concat(tabelas, ignore_index=True).dropna(axis=1, how="all") if len(tabelas) > 1 else tabelas[0]


def paraExcel(abas):
    """Uma aba por banco (como no modelo)."""
    mem_arquivo = io.BytesIO()
    with pd.ExcelWriter(mem_arquivo, engine="openpyxl", datetime_format="yyyy-mm-dd") as escritor_planilha:
        for nome, df in abas.items():
            df.to_excel(escritor_planilha, sheet_name=nome, index=False)
            for coluna in escritor_planilha.sheets[nome].iter_cols(min_row=2):
                for celula in coluna:
                    if isinstance(celula.value, (datetime, pd.Timestamp)):
                        celula.number_format = FORMATO_DATA_EXCEL
    return mem_arquivo.getvalue()


def avisoPasta(data, banco=None):
    """Diz qual parte do caminho <histórico>/<ano>/<Mês>/<banco> não existe no Drive (None se está tudo no lugar)."""
    nm_mes = MESES[data.month - 1]
    try:
        dict_pastas = arquivos_drive.pastasDoMes(arquivos_drive.loginAtual(), data.year, nm_mes)
    except arquivos_drive.ERROS_DRIVE as excecao:
        return f"Não consegui acessar o Drive: {arquivos_drive.textoErro(excecao)}"
    if not dict_pastas["ano"]:
        return f"A pasta do ano {data.year} ainda não existe em {arquivos_drive.NOME_HISTORICO}."
    if not dict_pastas["mes"]:
        return f"A pasta {data.year}/{nm_mes} ainda não existe, então não há arquivos para {data:%d/%m/%Y}."
    if banco and BANCOS[banco]["pasta"] not in dict_pastas["bancos"]:
        return f"A pasta do {banco} não existe em {data.year}/{nm_mes}."
    return None


def _prefixos(banco):
    configuracao_item = BANCOS[banco] 
    return configuracao_item.get("prefixos") or [configuracao_item["prefixo"]]


def arquivosDaData(data, banco):
    """Arquivo da data no Drive (um por prefixo do banco; o id é None quando não existe)."""
    nm_mes = MESES[data.month - 1]
    dict_dia = arquivos_drive.arquivosDoDia(arquivos_drive.loginAtual(), data.year, nm_mes, f"{data:%Y%m%d}")
    dict_existentes = dict_dia.get(BANCOS[banco]["pasta"], {})
    ds_base = "/".join([arquivos_drive.NOME_HISTORICO, str(data.year), nm_mes, BANCOS[banco]["pasta"]])
    lista_arquivos = []
    for pref in _prefixos(banco):
        nm_arquivo = f"{pref} - {data:%Y%m%d}.xlsx"
        tupla_achada = dict_existentes.get(nm_arquivo.lower())
        lista_arquivos.append(arquivos_drive.ArquivoDrive(
            nm_arquivo, tupla_achada[0] if tupla_achada else None, f"{ds_base}/{nm_arquivo}", tupla_achada[2] if tupla_achada else ""))
    return lista_arquivos


@st.cache_data(ttl=300, show_spinner=False)
def tratarBancoEmCache(login, banco, lista_chaves):
    """tratarBanco com cache: a aba Todos e a aba do banco usam o mesmo resultado, e ele só é refeito se o arquivo mudar."""
    lista_arquivos = [arquivos_drive.ArquivoDrive(nm_arquivo, id_arquivo, "", ds_modificado) for nm_arquivo, id_arquivo, ds_modificado in lista_chaves]
    return tratarBanco(banco, lista_arquivos, carregarDepara(login))


def _nomes(arquivos):
    return ", ".join(arquivo.name for arquivo in arquivos)


def _chaveData(nome):
    achou = re.search(r"\d{8}", nome)  # alguns nomes variam (ex.: "_Off"); ordena pela data
    return (achou.group(0) if achou else "") + nome


def listarArquivos(banco):
    """Arquivos do banco em todos os meses e anos: texto da lista -> arquivos.
    Banco com mais de um arquivo por dia (MS) aparece uma vez por data, com todos os arquivos daquele dia."""
    prefixos = _prefixos(banco)
    achados = {}
    try:
        lista_drive = arquivos_drive.listarTodosDoBanco(arquivos_drive.loginAtual(), BANCOS[banco]["pasta"])
    except arquivos_drive.ERROS_DRIVE as excecao:
        st.error(f"Não consegui listar os arquivos do {banco}: {arquivos_drive.textoErro(excecao)}")
        return {}
    for dict_arquivo in lista_drive:
        arquivo = arquivos_drive.ArquivoDrive(dict_arquivo["nome"], dict_arquivo["id"], dict_arquivo["caminho"], dict_arquivo["modificado"])
        if len(prefixos) == 1:
            achados[arquivo.name] = [arquivo]
            continue
        achou = re.fullmatch(r"(%s) - (\d{8})\.xlsx" % "|".join(map(re.escape, prefixos)), arquivo.name)
        if achou:
            achados.setdefault(achou.group(2), []).append(arquivo)
    if len(prefixos) > 1:  # texto da lista: "20260930 [MS, MS2]"
        achados = {f"{dia} [{', '.join(arq.name.split(' - ')[0].removeprefix('Transactions_') for arq in sorted(cs, key=lambda arq: arq.name))}]":
                   sorted(cs, key=lambda arq: arq.name) for dia, cs in achados.items()}
    return dict(sorted(achados.items(), key=lambda kv: _chaveData(kv[0]), reverse=True))


def configDatas(df):
    """Mostra as colunas de data como data abreviada (dd/mm/aaaa) nas tabelas da tela."""
    return {coluna: st.column_config.DateColumn(format="DD/MM/YYYY") for coluna in df.columns
            if pd.api.types.is_datetime64_any_dtype(df[coluna])}


def telaBanco(banco, data_sel):
    try:
        arquivos = arquivosDaData(data_sel, banco)
    except arquivos_drive.ERROS_DRIVE as excecao:
        st.error(f"Não consegui acessar o Drive: {arquivos_drive.textoErro(excecao)}")
        return

    # Opção avançada, oculta por padrão: lista os arquivos de todos os meses e anos (a caixa aceita digitar para filtrar)
    with st.expander("Escolher outro arquivo da pasta"):
        existentes = {}
        if st.checkbox("Carregar a lista de arquivos de todas as datas", key=f"listar_{banco}"):
            existentes = listarArquivos(banco)
        escolhido = st.selectbox(
            "Arquivos da pasta (digite a data para filtrar, ex.: 20260930)", list(existentes), index=None,
            placeholder="Usar o arquivo da data selecionada", key=f"arquivo_{banco}",
        )
        if escolhido:
            arquivos = existentes[escolhido]

    st.caption("Arquivo: " + " | ".join(str(arquivo) for arquivo in arquivos))
    achados = [arquivo for arquivo in arquivos if arquivo.exists()]
    if not achados:
        st.warning(avisoPasta(data_sel, banco)
                   or "Arquivo não encontrado para essa data. Confira a data ou se a pasta está acessível.")
        return
    if len(achados) < len(arquivos):
        st.info("Não encontrado: " + _nomes([arquivo for arquivo in arquivos if arquivo not in achados]))
    try:
        df = tratarBancoEmCache(arquivos_drive.loginAtual(), banco, tuple(arquivo.chave() for arquivo in achados))
    except (KeyError, ValueError, StopIteration) as excecao:
        st.error(str(excecao))
    except (OSError, *arquivos_drive.ERROS_DRIVE) as excecao:
        st.error(f"Não foi possível abrir o arquivo ou o De-Para ({arquivos_drive.NOME_MODELO}): {arquivos_drive.textoErro(excecao)}")
    else:
        st.success(f"{len(df)} linhas e {len(df.columns)} colunas.")
        st.dataframe(df, use_container_width=True, hide_index=True, column_config=configDatas(df))
        st.download_button(
            "Baixar Excel tratado", paraExcel({banco: df}),
            file_name=(
                f"Tratado_{achados[0].name.replace('Transactions_', 'Transactions_Offshore_', 1)}" if len(achados) == 1
                else f"Tratado_Transactions_Offshore_{banco.replace(' ', '_')}_{_chaveData(achados[0].name)[:8]}.xlsx"
            ),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"baixar_{banco}",
        )


def cartoesHtml(resultados, arquivos):
    """Cartões (padrão do portal) com as linhas de cada banco e quantas ficaram sem cliente no De-Para."""
    itens = []
    for banco, df in resultados.items():
        sem_cliente = int(df["Client"].isin(["", "erro"]).sum())
        if sem_cliente:
            cls, sub = "div", f"{sem_cliente} sem cliente no De-Para"
        elif len(df):
            cls, sub = "ok", "todos com cliente"
        else:
            cls, sub = "vazio", "nenhuma linha na janela"
        itens.append(
            f'<div class="kpi {cls}"><div class="kpi-label">{html.escape(banco)}</div>'
            f'<div class="kpi-valor">{len(df)}</div>'
            f'<div class="kpi-sub">{sub}</div>'
            f'<div class="kpi-sub">{html.escape(_nomes(arquivos[banco]))}</div></div>'
        )
    total = sum(len(df) for df in resultados.values())
    itens.insert(0, f'<div class="kpi"><div class="kpi-label">Total</div><div class="kpi-valor">{total}</div>'
                    f'<div class="kpi-sub">{len(resultados)} banco(s)</div></div>')
    return '<div class="kpis">' + "".join(itens) + "</div>"


# ---------------- E-mail do Daily Report ----------------
# Seções na ordem do modelo (aba E-mail): título -> bancos do app que entram nela. Seção sem linhas não vai no e-mail.
SECOES_EMAIL = [
    ("BTG Cayman", []),  # ainda fora do app
    ("BTG US", ["BTG US"]),
    ("Morgan Stanley", ["MS"]),
    ("Bradesco Miami", ["Bradesco Miami"]),
    ("Bradesco Europa", []),  # ainda fora do app
]
ABA_EMAIL = "E-mail"
ESTILO_TH = ("background:#6A0F2B;color:#fff;font-weight:bold;padding:4px 8px;border:1px solid #ccc;"
             "text-align:left;white-space:nowrap;")
ESTILO_TD = "padding:3px 8px;border:1px solid #ddd;vertical-align:top;"


@st.cache_data(ttl=300, show_spinner=False)
def carregarDestinatarios(login):
    """Para e CC, lidos da aba E-mail do modelo (linha 2, colunas A e B)."""
    pasta_trabalho = arquivos_drive.abrirModelo(login)
    try:
        linha = next(pasta_trabalho[ABA_EMAIL].iter_rows(min_row=2, max_row=2, values_only=True))
    finally:
        pasta_trabalho.close()
    return str(linha[0] or "").strip(), str(linha[1] or "").strip()


def _celulaEmail(valor):
    if valor is None or valor is pd.NaT or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    if isinstance(valor, (datetime, pd.Timestamp)):
        return valor.strftime("%d/%m/%Y")
    if isinstance(valor, float):
        texto = f"{valor:,.4f}".rstrip("0")
        inteiro, _, dec = texto.partition(".")
        return f"{inteiro}.{dec.ljust(2, '0')}"
    return html.escape(str(valor)).replace("\n", " ")


def tabelaEmailHtml(df):
    cab = "".join(f'<th style="{ESTILO_TH}">{html.escape(str(coluna))}</th>' for coluna in df.columns)
    linhas = ""
    for linha in df.itertuples(index=False, name=None):
        celulas = ""
        for valor in linha:
            numero = isinstance(valor, (int, float)) and not isinstance(valor, bool)
            celulas += f'<td style="{ESTILO_TD}{"text-align:right;" if numero else ""}">{_celulaEmail(valor)}</td>'
        linhas += f"<tr>{celulas}</tr>"
    return ('<table style="border-collapse:collapse;font-family:Calibri,Arial,sans-serif;font-size:10pt;">'
            f"<tr>{cab}</tr>{linhas}</table>")


def corpoEmailHtml(resultados):
    """Corpo do e-mail e os títulos das seções incluídas (só as que têm linhas)."""
    partes = ["<p>Bom dia!</p>", "<p>Liquidações em andamento:</p>"]
    incluidas = []
    for titulo, bancos in SECOES_EMAIL:
        tabelas = [resultados[nome_banco] for nome_banco in bancos if nome_banco in resultados and len(resultados[nome_banco])]
        if not tabelas:
            continue
        df = pd.concat(tabelas, ignore_index=True) if len(tabelas) > 1 else tabelas[0]
        partes.append(f"<p><b>&middot; {html.escape(titulo)}</b></p>{tabelaEmailHtml(df)}<br>")
        incluidas.append(titulo)
    partes += ["<p>Se precisarem de algo, estou à disposição!</p>", "<p>Abs,</p>"]
    return "".join(partes), incluidas


def _enderecos(lista):
    """Endereços de uma lista do tipo "Nome <a@b.com>; Outro <c@d.com>;" (só o e-mail de cada um)."""
    achados = []
    for parte in re.split(r"[;,]", lista):
        achado_email = re.search(r"[\w.+'-]+@[\w.-]+\.\w+", parte)
        if achado_email:
            achados.append(achado_email.group(0))
    return achados


def criarRascunhoGmail(assunto, para, cc, corpo):
    """Cria o rascunho no Gmail (não envia), com a assinatura do Gmail depois do corpo.
    Devolve (link para abrir o rascunho, endereços que não parecem válidos)."""
    servico = email_gmail.servicoDaSessao()
    invalidos = [endereco for endereco in _enderecos(para) + _enderecos(cc) if not re.fullmatch(r"[\w.+'-]+@[\w.-]+\.\w+", endereco)]
    ds_html = f"<div>{corpo}</div><br>{email_gmail.assinaturaHtml(servico)}"
    mensagem_email = email_gmail.montarMime(para, assunto, ds_html, cc)
    return email_gmail.criarRascunho(servico, mensagem_email), invalidos


def botaoEmail(resultados, data_sel):
    if st.button("Montar e-mail no Gmail", key="montar_email"):
        corpo, incluidas = corpoEmailHtml(resultados)
        if not incluidas:
            st.warning("Nenhum banco tem linhas para essa data: o e-mail não foi montado.")
            return
        try:
            para, cc = carregarDestinatarios(arquivos_drive.loginAtual())
            link, invalidos = criarRascunhoGmail(
                f"{data_sel:%d/%m/%Y} Daily Report | Offshore Transactions", para, cc, corpo)
        except email_gmail.GmailNaoConectadoErro:
            st.error("A conexão com a conta Google expirou. Conecte-se de novo.")
            st.rerun()
        except Exception as excecao:  # modelo inacessível ou falha na API
            st.error(f"Não foi possível montar o e-mail. Detalhe: {excecao}")
        else:
            st.success("Rascunho criado no Gmail (não enviado). Seções: " + ", ".join(incluidas) + ".")
            st.link_button("Abrir rascunho no Gmail", link)
            if invalidos:
                st.warning("Estes destinatários não parecem endereços válidos: " + ", ".join(invalidos))


def telaTodos(data_sel):
    """Trata todos os bancos da data de uma vez e junta num Excel, uma aba por banco."""
    try:
        arquivos = {banco: arquivosDaData(data_sel, banco) for banco in BANCOS}
        # baixa de uma vez (em paralelo) todos os arquivos do dia e o modelo; depois o resto da tela usa o cache
        login = arquivos_drive.loginAtual()
        arquivos_drive.baixarVarios(login, [(arquivo.id, arquivo.modificado) for lista_banco in arquivos.values()
                                            for arquivo in lista_banco if arquivo.exists()] + [(arquivos_drive.idModelo(), "")])
    except arquivos_drive.ERROS_DRIVE as excecao:
        st.error(f"Não consegui acessar o Drive: {arquivos_drive.textoErro(excecao)}")
        return
    depara = carregarDeparaSeguro()
    if depara is None:
        return
    # Opção avançada, oculta por padrão: escolher outro arquivo (de qualquer data) para cada banco
    with st.expander("Escolher outros arquivos da pasta"):
        ic_listar = st.checkbox("Carregar a lista de arquivos de todas as datas", key="listar_todos")
        for col, banco in zip(st.columns(len(BANCOS)), BANCOS):
            with col:
                existentes = listarArquivos(banco) if ic_listar else {}
                escolhido = st.selectbox(
                    f"{banco} (digite a data para filtrar)", list(existentes), index=None,
                    placeholder="Usar o arquivo da data selecionada", key=f"arquivo_todos_{banco}",
                )
                if escolhido:
                    arquivos[banco] = existentes[escolhido]

    resultados = {}
    aviso_mes = avisoPasta(data_sel)  # raiz, ano ou mês inexistente vale para todos os bancos: avisa uma vez só
    pasta_mes_ausente = aviso_mes is not None
    if aviso_mes:
        st.warning(aviso_mes)
    for banco in BANCOS:
        achados = [arquivo for arquivo in arquivos[banco] if arquivo.exists()]
        if not achados:
            motivo = avisoPasta(data_sel, banco)
            if motivo and not pasta_mes_ausente:
                st.warning(f"{banco}: {motivo}")
            elif not motivo:
                st.warning(f"{banco}: arquivo não encontrado ({_nomes(arquivos[banco])}).")
            continue
        if len(achados) < len(arquivos[banco]):
            st.info(f"{banco}: não encontrado " + _nomes([arquivo for arquivo in arquivos[banco] if arquivo not in achados]))
        arquivos[banco] = achados  # o cartão mostra só o que foi usado
        try:
            resultados[banco] = tratarBancoEmCache(login, banco, tuple(arquivo.chave() for arquivo in achados))
        except (KeyError, ValueError, StopIteration, OSError, *arquivos_drive.ERROS_DRIVE) as excecao:
            st.error(f"{banco}: {arquivos_drive.textoErro(excecao)}")

    if not resultados:
        return
    st.markdown(cartoesHtml(resultados, arquivos), unsafe_allow_html=True)
    for banco, df in resultados.items():
        with st.expander(f"{banco} ({len(df)} linhas)", expanded=bool(len(df))):
            st.dataframe(df, use_container_width=True, hide_index=True, column_config=configDatas(df))
    st.download_button(
        "Baixar Excel", paraExcel(resultados), file_name=f"Tratado_Transactions_{data_sel:%Y%m%d}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="baixar_todos",
    )
    botaoEmail(resultados, data_sel)


def carregarDeparaSeguro():
    try:
        return carregarDepara(arquivos_drive.loginAtual())
    except (OSError, KeyError, ValueError, StopIteration, *arquivos_drive.ERROS_DRIVE) as excecao:
        st.error(f"Não foi possível abrir o De-Para ({arquivos_drive.NOME_MODELO}): {arquivos_drive.textoErro(excecao)}")
        return None


topo("Transactions Offshore", "Tratamento dos arquivos de transações por banco", app="bradesco")
if not email_gmail.emailDaSessao():
    st.warning("Os arquivos do Offshore ficam no Google Drive. Conecte a sua conta Google (\"Conectar ao Google\" na lateral) para continuar.")
    st.stop()

data_sel = st.date_input("Data do arquivo", value=date.today(), format="DD/MM/YYYY")
nomes_abas = ["Todos"] + list(BANCOS)
for aba, nome in zip(st.tabs(nomes_abas), nomes_abas):
    with aba:
        if nome == "Todos":
            telaTodos(data_sel)
        else:
            telaBanco(nome, data_sel)
