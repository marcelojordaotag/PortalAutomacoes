"""CRAVA COTAS, aba Britech: confere se tudo que está no Grid 4 (cotas) existe no Grid 3 (cadastro)."""
import re

import pandas as pd

COLUNA_GRID3 = "Id Cliente"
COLUNA_GRID4 = "ID Carteira"
COLUNA_VALOR = "Valor Cota"
COLUNAS_TITLE = ("Tipo Controle", "Tipo Bloqueio", "Fonte")  # ficam com o title=; as outras com HTML ficam com o texto visível


def textoDoTitle(valor, usarTitle=True):
    """"<div title='Completo'>Completo</div>" vira "Completo": usa o title=; sem title, tira as tags e fica com o texto."""
    if not isinstance(valor, str) or "<" not in valor:
        return valor
    titulo = re.search(r"title\s*=\s*(['\"])(.*?)\1", valor, flags=re.S)
    return (titulo.group(2) if titulo and usarTitle else re.sub(r"<[^>]+>", "", valor)).strip()


def tratarHtml(tabela):
    """Limpa as colunas de texto exportadas com HTML (Tipo Controle, Tipo Bloqueio e Fonte pelo title=; as demais pelo texto visível)."""
    tabela = tabela.copy()
    for coluna in tabela.select_dtypes(include="object").columns:
        tabela[coluna] = tabela[coluna].map(lambda valor: textoDoTitle(valor, coluna in COLUNAS_TITLE))
    return tabela


def lerGrid(arquivo, coluna_id):
    """Lê o Excel exportado e valida a coluna de ID. Levanta ValueError com mensagem amigável."""
    tabela = tratarHtml(pd.read_excel(arquivo))
    if coluna_id not in tabela.columns:
        raise ValueError(f"Não achei a coluna \"{coluna_id}\" neste arquivo. Colunas encontradas: {', '.join(map(str, tabela.columns))}.")
    tabela[coluna_id] = pd.to_numeric(tabela[coluna_id], errors="coerce")
    return tabela.dropna(subset=[coluna_id]).astype({coluna_id: "int64"})


def pendentesNoGrid3(grid3, grid4):
    """Linhas do Grid 4 cujo ID Carteira não aparece em Id Cliente do Grid 3."""
    return grid4[~grid4[COLUNA_GRID4].isin(grid3[COLUNA_GRID3])].reset_index(drop=True)


def somenteNoGrid3(grid3, grid4):
    """Linhas do Grid 3 cujo Id Cliente não aparece em ID Carteira do Grid 4 (sem cota no dia)."""
    return grid3[~grid3[COLUNA_GRID3].isin(grid4[COLUNA_GRID4])].reset_index(drop=True)


def valoresVazios(grid4, coluna_valor=COLUNA_VALOR):
    """Linhas do Grid 4 com a coluna de valor vazia ou sem valor (nulo, texto em branco ou zero)."""
    valor = grid4[coluna_valor]
    numero = pd.to_numeric(valor, errors="coerce")
    vazio = valor.isna() | valor.astype(str).str.strip().eq("") | numero.isna() | numero.eq(0)
    return grid4[vazio].reset_index(drop=True)


def pendencias(grid3, grid4):
    """Uma tabela só com tudo que precisa de atenção: ID, Carteira, Problema e Valor Cota."""
    colunas = ["ID", "Carteira", "Problema", COLUNA_VALOR]
    partes = []
    fora = pendentesNoGrid3(grid3, grid4)
    partes.append(pd.DataFrame({"ID": fora[COLUNA_GRID4], "Carteira": fora["Carteira"], "Problema": "Não está no Grid 3",
                                COLUNA_VALOR: fora[COLUNA_VALOR] if COLUNA_VALOR in fora.columns else None}))
    sem_cota = somenteNoGrid3(grid3, grid4)
    partes.append(pd.DataFrame({"ID": sem_cota[COLUNA_GRID3], "Carteira": sem_cota["Apelido"], "Problema": "Sem cota no Grid 4",
                                COLUNA_VALOR: None}))
    if COLUNA_VALOR in grid4.columns:
        vazios = valoresVazios(grid4)
        vazios = vazios[~vazios[COLUNA_GRID4].isin(fora[COLUNA_GRID4])]  # quem já está listado acima não repete
        partes.append(pd.DataFrame({"ID": vazios[COLUNA_GRID4], "Carteira": vazios["Carteira"], "Problema": "Valor Cota vazio",
                                    COLUNA_VALOR: vazios[COLUNA_VALOR]}))
    partes = [parte for parte in partes if not parte.empty]
    tabela = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=colunas)
    tabela["ID"] = tabela["ID"].astype(str)
    tabela[COLUNA_VALOR] = pd.to_numeric(tabela[COLUNA_VALOR], errors="coerce")
    return tabela[colunas]


def resumoProblemas(tabela):
    """"6 sem cota no Grid 4" / "2 não estão no Grid 3 · 1 com Valor Cota vazio": o que a tabela mostra sem coluna de problema."""
    nomes = {"Não está no Grid 3": "não estão no Grid 3", "Sem cota no Grid 4": "sem cota no Grid 4", "Valor Cota vazio": "com Valor Cota vazio"}
    contagem = tabela["Problema"].value_counts()
    return " · ".join(f"{contagem[problema]} {nome}" for problema, nome in nomes.items() if problema in contagem)


def mensagensSlackGrids(grid3, grid4, data):
    """Uma mensagem com a tabela de pendências (o Slack aceita uma tabela por mensagem; mais de 99 linhas viram mais mensagens)."""
    from app.paginas.crava_cotas.slack_crava import celulaSlack

    tabela = pendencias(grid3, grid4)
    cabecalho = f"*CRAVA COTAS: conferência Britech de {data:%d/%m/%Y}*"
    if tabela.empty:
        return [{"texto": f"{cabecalho}: tudo certo, nenhuma pendência.", "tabela": None}]
    tabela = tabela.drop(columns="Problema")
    tabela[COLUNA_VALOR] = tabela[COLUNA_VALOR].map(lambda valor: "-" if pd.isna(valor) else f"{valor:.8f}")
    linhas = [[celulaSlack(valor) for valor in linha] for linha in tabela.itertuples(index=False)]
    topo = [celulaSlack(coluna) for coluna in tabela.columns]
    return [{"texto": f"{cabecalho}: {resumoProblemas(pendencias(grid3, grid4))}",
             "tabela": {"type": "table", "rows": [topo] + linhas[inicio:inicio + 99]}}
            for inicio in range(0, len(linhas), 99)]
