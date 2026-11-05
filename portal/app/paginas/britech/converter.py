#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Trata a planilha Relatorio_Rentabilidade.xlsx (aba "Ativo") para ficar com os mesmos
valores do PDF "Rentabilidade e Performance" da BRITech.

A aba Ativo tem UMA LINHA POR ATIVO POR DIA. O PDF tem UMA LINHA POR ATIVO no periodo.
As regras para passar de um para o outro sao:

    PL Inicial = ValorFinal do primeiro dia (dia-base)       -> pega 1 dia, NAO soma
    Entradas   = soma de ValorEntrada dos dias apos o dia-base
    Saidas     = soma de ValorSaida dos dias apos o dia-base
    Rendas     = soma de ValorRendas dos dias apos o dia-base
    Rendimento = soma de RendimentoLiquida dos dias apos o dia-base
    PL Final   = ValorFinal do ultimo dia                    -> pega 1 dia, NAO soma
    % Rent     = juros compostos: produto de (1 + retorno do dia) - 1,
                 com retorno do dia = Rendimento do dia / ValorInicial do dia
    % Rent dos totais (Estrategia, SubClasse, Classe) = a mesma conta, feita com as linhas do grupo
    % Rent do Total Geral = rentabilidade da carteira (cota): coluna RentabilidadeCotaBruta
                 da aba "Estrategia" (e o 1,1180% do cabecalho do PDF)

Agrupamentos: linhas com o mesmo nome viram um ativo so (NTN-B tem varios codigos,
Provisao tem varios). Acoes ("Bolsa") usam o CodigoAtivo (ex.: BOVA11). Conta Corrente
e Lancamento ficam de fora (zerados / nao aparecem no PDF).

Uso:
    python tratar_rentabilidade.py                                  (procura Relatorio_Rentabilidade.xlsx)
    python tratar_rentabilidade.py "C:\\caminho\\Relatorio_Rentabilidade.xlsx"
    python tratar_rentabilidade.py arquivo.xlsx -o saida.xlsx --inicio 2026-07-31 --fim 2026-08-31

Dentro de outro codigo (ex.: o app Streamlit):
    from tratar_rentabilidade import tratar
    ativos, layout, avisos = tratar(pd.read_excel("Relatorio_Rentabilidade.xlsx", sheet_name="Ativo"),
                                    rentab_carteira=1.118)   # ou ler_rentabilidade_carteira("Relatorio_Rentabilidade.xlsx")

Precisa de: pandas, numpy, openpyxl.
"""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# ----------------------------------------------------------------------------
# Configuracao
# ----------------------------------------------------------------------------
ABA_ATIVO = "Ativo"
ARQUIVO_PADRAO = "Relatorio_Rentabilidade.xlsx"
SAIDA_PADRAO = "Rentabilidade_Tratada.xlsx"
# Extrato de conta corrente (PDF convertido em xlsx). Fixo, ao lado deste script, ate puxarmos pela API.
EXTRATO_PADRAO = Path(__file__).resolve().parents[3] / "dados" / "britech" / "ReportExtratoContaCorrente.xlsx"
# Extratos por carteira, baixados pelo api_britech.py (ReportExtratoContaCorrente_<id>.xlsx)
EXTRATOS_PADRAO = Path(__file__).resolve().parents[3] / "dados" / "britech" / "extratos"
# Linhas do extrato que so movem dinheiro entre caixa e ativos (nao mudam o PL)
_INTERNO = re.compile(r"^(Resgate|Aplica|Compra|Venda|Pagamento Juros|Juros|Amortiza|Cupom|Vencimento)", re.I)
_CUPOM = re.compile(r"^(Pagamento Juros|Juros|Amortiza|Cupom)", re.I)
EXCLUIR_ESTRATEGIAS = {"Lançamento"}  # movimentos de caixa que nao aparecem no PDF

COLUNAS_NECESSARIAS = [
    "Data", "TipoAtivo", "CodigoAtivo", "Mnemonico", "Estrategia", "ClasseAtivo", "SubClasseAtivo",
    "ValorInicial", "ValorEntrada", "ValorSaida", "ValorRendas", "ValorFinal", "RendimentoLiquida",
]
COLUNAS_NUMERICAS = [
    "ValorInicial", "ValorEntrada", "ValorSaida", "ValorRendas", "ValorFinal", "RendimentoLiquida",
]
CHAVE = ["Classe", "SubClasse", "Estratégia", "Ativo"]
VALORES = ["PL Inicial", "Entradas", "Saídas", "Rendas", "PL Final", "Rendimento"]
COLUNAS_SAIDA = ["Classe", "SubClasse", "Estratégia", "Ativo"] + VALORES + ["% Rent"]

# Ordem de exibicao parecida com a do PDF (o que nao estiver aqui vai para o fim, em ordem alfabetica)
ORDEM_CLASSE = ["RENDA FIXA", "RENDA VARIÁVEL", "ESTRUTURADOS", "CAIXA"]
ORDEM_SUBCLASSE = {
    "RENDA FIXA": ["CAIXA", "RENDA FIXA PÓS", "RENDA FIXA CDI+", "RENDA FIXA INFLAÇÃO", "RENDA FIXA PÓS PREVIDÊNCIA"],
    "RENDA VARIÁVEL": ["RENDA VARIÁVEL", "RENDA VARIÁVEL PREVIDÊNCIA"],
    "ESTRUTURADOS": ["RENDA VARIÁVEL", "RENDA FIXA PÓS PREVIDÊNCIA", "MULTIMERCADO PREVIDÊNCIA"],
    "CAIXA": ["CAIXA"],
}
ORDEM_ESTRATEGIA = [
    "CAIXA TPF FUNDOS SIMPLES DI",
    "RF PRIVADO FUNDO DE CRÉDITO PRIVADO MID YIELD",
    "RF PRIVADO FUNDO DE CRÉDITO PRIVADO HIGH GRADE",
    "RF PRIVADO FUNDO DE CRÉDITO PRIVADO HIGH YIELD",
    "RF PRIVADO DEBÊNTURES COMUNS CDI +",
    "RF TPF NTNB OU TESOURO INFLAÇÃO",
    "RV ETFs INDEXADOS BOVESPA",
    "RV FUNDOS VALOR",
    "RV FUNDOS LONG BIAS",
    "MM MACRO",
    "MM ARBITRAGEM",
    "CAIXA",
]


# ----------------------------------------------------------------------------
# Tratamento dos dados
# ----------------------------------------------------------------------------
def _posicao(lista, valor):
    return lista.index(valor) if valor in lista else len(lista)


def _ordenar(resultado_calculo):
    resultado_calculo = resultado_calculo.copy()
    resultado_calculo["_c"] = resultado_calculo["Classe"].map(lambda valor: _posicao(ORDEM_CLASSE, valor))
    resultado_calculo["_s"] = [_posicao(ORDEM_SUBCLASSE.get(classe, []), subclasse) for classe, subclasse in zip(resultado_calculo["Classe"], resultado_calculo["SubClasse"])]
    resultado_calculo["_e"] = resultado_calculo["Estratégia"].map(lambda valor: _posicao(ORDEM_ESTRATEGIA, valor))
    resultado_calculo = resultado_calculo.sort_values(["_c", "Classe", "_s", "SubClasse", "_e", "Estratégia", "Ativo"])
    return resultado_calculo.drop(columns=["_c", "_s", "_e"]).reset_index(drop=True)


def _rentComposta(dados, chaves):
    """Rentabilidade composta por grupo: produto de (1 + rendimento do dia / valor inicial do dia) - 1."""
    dia = dados.groupby(chaves + ["Data"], as_index=False)[["ValorInicial", "RendimentoLiquida"]].sum()
    retorno = np.divide(dia["RendimentoLiquida"].to_numpy(), dia["ValorInicial"].to_numpy(),
                        out=np.zeros(len(dia)), where=dia["ValorInicial"].to_numpy() != 0)
    dia["fator"] = 1.0 + retorno
    return dia.groupby(chaves)["fator"].prod() - 1.0


def montarLayout(ativos, rent):
    """Monta a tabela no formato do PDF: ativos seguidos de Total Estrategia / SubClasse / Classe / Geral."""
    linhas = []

    def somar(df):
        return {coluna: round(float(df[coluna].sum()), 2) for coluna in VALORES}

    def total(nivel, classe, sub, est, df, pct):
        linhas.append({"Nível": nivel, "Classe": classe, "SubClasse": sub, "Estratégia": est,
                       "Ativo": nivel, **somar(df), "% Rent": pct})

    for classe, d_classe in ativos.groupby("Classe", sort=False):
        for sub, d_sub in d_classe.groupby("SubClasse", sort=False):
            for est, d_est in d_sub.groupby("Estratégia", sort=False):
                for _, registro in d_est.iterrows():
                    linhas.append({"Nível": "Ativo", "Classe": classe, "SubClasse": sub, "Estratégia": est,
                                   "Ativo": registro["Ativo"], **{coluna: registro[coluna] for coluna in VALORES}, "% Rent": registro["% Rent"]})
                total("Total Estratégia", classe, sub, est, d_est, rent["estrategia"].get((classe, sub, est), np.nan))
            total("Total SubClasse", classe, sub, "", d_sub, rent["subclasse"].get((classe, sub), np.nan))
        total("Total Classe", classe, "", "", d_classe, rent["classe"].get(classe, np.nan))
    total("Total Geral", "", "", "", ativos, rent["geral"])
    return pd.DataFrame(linhas)


def conferirCarteira(disposicao):
    """Conferencia: rentabilidade da carteira (cota) x rentabilidade simples dos ativos.

    1) simples   = Rendimento total / PL Inicial total
    2) diferenca = rentabilidade da carteira - simples          (negativo: carteira rendeu menos que os ativos)
    3) em reais  = diferenca * PL Inicial total
    Base: sempre o PL Inicial (nao usar PL medio nem PL final). Sem arredondar nos passos.
    """
    linha_geral = disposicao[disposicao["Nível"] == "Total Geral"].iloc[0]
    rendimento, pl_inicial, carteira = float(linha_geral["Rendimento"]), float(linha_geral["PL Inicial"]), float(linha_geral["% Rent"])
    simples = rendimento / pl_inicial if pl_inicial else float("nan")
    diferenca = carteira - simples
    return {"rendimento": rendimento, "pl_inicial": pl_inicial, "carteira": carteira,
            "simples": simples, "diferenca": diferenca, "diferenca_reais": diferenca * pl_inicial}


def _numBr(valor):
    """Numero do extrato: float direto (credito) ou texto brasileiro, com parenteses = negativo (debito)."""
    if valor is None or (isinstance(valor, float) and np.isnan(valor)):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip()
    if not re.fullmatch(r"[(-]?[\d.]+,\d+\)?", texto):
        return None
    numero = float(texto.strip("()-").replace(".", "").replace(",", "."))
    return -numero if texto[0] in "(-" else numero


def lerExtrato(caminho):
    """Le o Extrato de Conta Corrente (PDF em xlsx). Retorna Movimento, Descricao, Valor (+ entra, - sai) e Tipo.

    Tipo: 'Interno' (resgate/aplicacao/compra: so troca caixa por ativo), 'Cupom' (juros/amortizacao
    recebidos, que sao as Rendas do ativo) ou 'Externo' (taxas, despesas, rebate: mudam o PL).
    """
    valor_bruto = pd.read_excel(caminho, header=None)

    def achar(nome):
        for ordem_item in range(len(valor_bruto)):
            for ordem_aux, valor_celula in valor_bruto.iloc[ordem_item].items():
                if isinstance(valor_celula, str) and valor_celula.strip() == nome:
                    return ordem_item, ordem_aux
        raise ValueError(f"Nao achei a coluna '{nome}' no extrato {Path(caminho).name}.")

    linha, c_deb = achar("Débito")
    c_cred, c_mov, c_desc, c_saldo = achar("Crédito")[1], achar("Movimento")[1], achar("Descrição")[1], achar("Saldo")[1]
    regs = []
    for ordem_item in range(linha + 1, len(valor_bruto)):
        mov, desc = valor_bruto.iat[ordem_item, c_mov], valor_bruto.iat[ordem_item, c_desc]
        if pd.isna(mov) or pd.isna(desc) or isinstance(mov, str):
            continue  # o cabecalho se repete a cada pagina do extrato
        deb = next((numero for numero in (_numBr(valor_bruto.iat[ordem_item, ordem_aux]) for ordem_aux in range(c_deb, c_cred - 1)) if numero is not None), 0.0)
        cred = next((numero for numero in (_numBr(valor_bruto.iat[ordem_item, ordem_aux]) for ordem_aux in range(c_cred - 1, c_saldo)) if numero is not None), 0.0)
        desc = re.sub(r"\s+", " ", str(desc)).strip()
        tipo = "Cupom" if _CUPOM.match(desc) else "Interno" if _INTERNO.match(desc) else "Externo"
        regs.append({"Movimento": pd.Timestamp(mov), "Descricao": desc, "Valor": round(cred + deb, 2), "Tipo": tipo})
    return pd.DataFrame(regs, columns=["Movimento", "Descricao", "Valor", "Tipo"])


def montarPonte(df_ativo, ativos, extrato):
    """Explica a diferenca entre o PL e o rendimento dos ativos:

        PL Final = PL Inicial + Rendimento dos ativos
                 + caixa externo do extrato (taxas, despesas, rebate)
                 + variacao das provisoes (aba Ativo, linhas 'Provisao')
                 - (Rendas da planilha - cupom recebido em caixa)
    O residuo (PL Final da planilha - PL Final calculado) deve ser zero.
    """
    inicio, fim = ativos.attrs["inicio"], ativos.attrs["fim"]

    df = df_ativo.copy()
    df["Data"] = pd.to_datetime(df["Data"])
    df["ValorFinal"] = pd.to_numeric(df["ValorFinal"], errors="coerce").fillna(0.0)
    prov = df[df["Mnemonico"].astype(str).str.strip().eq("Provisão") & ~df["Estrategia"].isin(EXCLUIR_ESTRATEGIAS)].copy()
    descr = prov["DescricaoAtivo"] if "DescricaoAtivo" in prov.columns else pd.Series("Provisão", index=prov.index)
    prov["Nome"] = descr.fillna("Provisão").astype(str).str.replace(r"\s*\(.*?\)", "", regex=True).str.strip()
    ini = prov[prov["Data"] == inicio].groupby("Nome")["ValorFinal"].sum()
    fin = prov[prov["Data"] == fim].groupby("Nome")["ValorFinal"].sum()
    provisoes = [{"nome": nm_provisao, "ini": round(float(ini.get(nm_provisao, 0.0)), 2), "fim": round(float(fin.get(nm_provisao, 0.0)), 2)}
                 for nm_provisao in sorted(set(ini.index) | set(fin.index))]
    for provisao in provisoes:
        provisao["delta"] = round(provisao["fim"] - provisao["ini"], 2)
    linha_prov = ativos[ativos["Ativo"] == "Provisão"]
    delta_total = float((linha_prov["PL Final"] - linha_prov["PL Inicial"]).sum())
    outras = round(delta_total - sum(provisao["delta"] for provisao in provisoes), 2)
    if abs(outras) > 0.005:
        provisoes.append({"nome": "Outras provisões", "ini": None, "fim": None, "delta": outras})

    extensao = extrato[(extrato["Movimento"] > inicio) & (extrato["Movimento"] <= fim)]
    externos = [{"data": linha_extrato.Movimento, "descricao": linha_extrato.Descricao, "valor": linha_extrato.Valor} for linha_extrato in extensao[extensao["Tipo"] == "Externo"].itertuples()]
    cupom_caixa = round(float(extensao.loc[extensao["Tipo"] == "Cupom", "Valor"].sum()), 2)
    rendas = round(float(ativos["Rendas"].sum()), 2)

    ponte = {"pl_inicial": round(float(ativos["PL Inicial"].sum()), 2),
             "rendimento": round(float(ativos["Rendimento"].sum()), 2),
             "externos": externos, "provisoes": provisoes,
             "rendas": rendas, "cupom_caixa": cupom_caixa,
             "pl_final": round(float(ativos["PL Final"].sum()), 2)}
    explicado = (sum(externo["valor"] for externo in externos) + sum(provisao["delta"] for provisao in provisoes) - (rendas - cupom_caixa))
    ponte["explicado"] = round(explicado, 2)
    ponte["residuo"] = round(ponte["pl_final"] - (ponte["pl_inicial"] + ponte["rendimento"] + explicado), 2)
    return ponte


def textosPonte(ponte):
    def br(valor):
        return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    linhas = ["Ponte da diferença (PL Final − PL Inicial − Rendimento):"]
    linhas += [f"  Extrato {externo['data']:%d/%m} {externo['descricao']}: {br(externo['valor'])}" for externo in ponte["externos"]]
    linhas += [f"  Provisão {provisao['nome']}: {br(provisao['delta'])}" for provisao in ponte["provisoes"]]
    linhas.append(f"  Rendas da planilha − cupom recebido em caixa: {br(-(ponte['rendas'] - ponte['cupom_caixa']))}")
    linhas.append(f"  Total explicado: {br(ponte['explicado'])} | Resíduo: {br(ponte['residuo'])}")
    return linhas


def textosConferencia(conferencia):
    """Passo a passo da conferencia, em texto (formato brasileiro)."""
    def br(valor, casas=2):
        return f"{valor:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return [
        f"Rendimento total = {br(conferencia['rendimento'])} | PL Inicial total = {br(conferencia['pl_inicial'])} | "
        f"Rentabilidade da carteira = {br(conferencia['carteira'] * 100, 4)}%",
        f"1) Rentabilidade simples dos ativos = {br(conferencia['simples'], 9)} ({br(conferencia['simples'] * 100, 4)}%)",
        f"2) Diferenca = {br(conferencia['diferenca'], 9)} ({br(conferencia['diferenca'] * 100, 4)} p.p.)",
        f"3) Diferenca em reais = {br(conferencia['diferenca_reais'])}",
        f"Os ativos renderam R$ {br(abs(conferencia['diferenca_reais']))} {'a mais' if conferencia['diferenca_reais'] < 0 else 'a menos'} "
        f"do que a rentabilidade da carteira indica (normalmente custos e despesas da propria carteira).",
    ]


def tratar(df_ativo, inicio=None, fim=None, rentab_carteira=None):
    """Transforma a aba Ativo (1 linha por ativo por dia) na visao do PDF (1 linha por ativo).

    Retorna (ativos, layout, avisos):
      ativos  - uma linha por ativo, sem subtotais (bom para usar em outras telas)
      layout  - igual ao PDF, com Total Estrategia / SubClasse / Classe / Geral
      avisos  - lista de textos com o que merece atencao

    rentab_carteira: rentabilidade da carteira no periodo, em % (ex.: 1.118), vinda da coluna
    RentabilidadeCotaBruta da aba "Estrategia". Vira o % Rent do Total Geral. Se nao vier,
    o Total Geral usa a soma dos ativos (pode diferir um pouco da cota).
    """
    faltando = [coluna for coluna in COLUNAS_NECESSARIAS if coluna not in df_ativo.columns]
    if faltando:
        raise ValueError("Faltam colunas na aba Ativo: " + ", ".join(faltando))

    df = df_ativo.copy()
    df["Data"] = pd.to_datetime(df["Data"])
    for coluna in COLUNAS_NUMERICAS:
        df[coluna] = pd.to_numeric(df[coluna], errors="coerce").fillna(0.0)

    inicio = pd.Timestamp(inicio) if inicio else df["Data"].min()
    fim = pd.Timestamp(fim) if fim else df["Data"].max()
    df = df[(df["Data"] >= inicio) & (df["Data"] <= fim)]
    df = df[~df["Estrategia"].isin(EXCLUIR_ESTRATEGIAS)]
    if df.empty:
        raise ValueError("Nao ha linhas no periodo informado.")

    # Nome do ativo: acoes usam o codigo (BOVA11); o resto usa o mnemonico
    bolsa = df["TipoAtivo"].astype(str).str.strip().str.lower().eq("bolsa")
    df["Ativo"] = np.where(bolsa, df["CodigoAtivo"].astype(str), df["Mnemonico"].astype(str))
    df["Ativo"] = df["Ativo"].str.replace(r"\s+", " ", regex=True).str.strip()
    df = df.rename(columns={"ClasseAtivo": "Classe", "SubClasseAtivo": "SubClasse", "Estrategia": "Estratégia"})
    for coluna in ("Classe", "SubClasse", "Estratégia"):
        df[coluna] = df[coluna].fillna("Não definida").astype(str).str.strip()

    # PL Inicial e PL Final: valor de UM dia (nao soma)
    pl_inicial = df[df["Data"] == inicio].groupby(CHAVE)["ValorFinal"].sum().rename("PL Inicial")
    pl_final = df[df["Data"] == fim].groupby(CHAVE)["ValorFinal"].sum().rename("PL Final")

    # Fluxos e rendimento: SOMA dos dias depois do dia-base
    posteriores = df[df["Data"] > inicio]
    somas = posteriores.groupby(CHAVE).agg(
        Entradas=("ValorEntrada", "sum"),
        Saídas=("ValorSaida", "sum"),
        Rendas=("ValorRendas", "sum"),
        Rendimento=("RendimentoLiquida", "sum"),
    )

    # % Rent: juros compostos (retorno do dia = rendimento / valor inicial do dia)
    rentab = _rentComposta(posteriores, CHAVE).rename("% Rent")

    resultado_calculo = pd.concat([pl_inicial, somas, pl_final, rentab], axis=1).fillna(0.0).reset_index()
    resultado_calculo[VALORES] = resultado_calculo[VALORES].round(2)
    resultado_calculo = resultado_calculo[resultado_calculo[VALORES].abs().sum(axis=1) > 0.005]  # fora ativos zerados (ex.: Conta Corrente)
    ativos = _ordenar(resultado_calculo)[CHAVE + VALORES + ["% Rent"]]

    avisos = []
    fecha = (ativos["PL Inicial"] + ativos["Entradas"] - ativos["Saídas"] - ativos["Rendas"]
             + ativos["Rendimento"] - ativos["PL Final"]).round(2)
    for nome, dif in zip(ativos["Ativo"][fecha.abs() > 1.0], fecha[fecha.abs() > 1.0]):
        avisos.append(f"{nome}: PL Inicial + Entradas - Saidas - Rendas + Rendimento difere do PL Final em {dif:,.2f}")
    if df["Data"].max() < fim:
        avisos.append(f"A planilha termina em {df['Data'].max():%d/%m/%Y}, antes da data final pedida ({fim:%d/%m/%Y}).")

    # % Rent dos totais: mesma conta, feita com todas as linhas de cada grupo
    rent_grupos = {
        "estrategia": _rentComposta(posteriores, ["Classe", "SubClasse", "Estratégia"]).to_dict(),
        "subclasse": _rentComposta(posteriores, ["Classe", "SubClasse"]).to_dict(),
        "classe": _rentComposta(posteriores, ["Classe"]).to_dict(),
    }
    soma_ativos = float(_rentComposta(posteriores.assign(_t=1), ["_t"]).iloc[0])
    if rentab_carteira is not None and not pd.isna(rentab_carteira):
        rent_grupos["geral"] = float(rentab_carteira) / 100.0
    else:
        rent_grupos["geral"] = soma_ativos
        avisos.append("Total Geral: % Rent calculado pela soma dos ativos, porque nao achei RentabilidadeCotaBruta "
                      "na aba Estrategia. Pode diferir um pouco do % do PDF (que usa a cota da carteira).")

    ativos.attrs["inicio"], ativos.attrs["fim"] = inicio, fim
    ativos.attrs["rent_soma_ativos"] = soma_ativos
    disposicao = montarLayout(ativos, rent_grupos)
    ativos.attrs["conferencia"] = conferirCarteira(disposicao)
    return ativos, disposicao, avisos


# ----------------------------------------------------------------------------
# Excel de saida
# ----------------------------------------------------------------------------
FONTE = "Arial"
FMT_VALOR = '#,##0.00;[Red](#,##0.00)'
FMT_PCT = '0.00%;[Red](0.00%)'
COR_CAB, COR_ESTRAT, COR_SUB, COR_CLASSE, COR_GERAL = "C9453B", "FBE9E5", "F5D3CB", "E8B5AA", "C9453B"
_borda = Border(*(Side(style="thin", color="E0C9C3"),) * 4)


def _cabecalho(planilha_aba, colunas, linha=1):
    for ordem_aux, nome in enumerate(colunas, 1):
        celula = planilha_aba.cell(linha, ordem_aux, nome)
        celula.font = Font(name=FONTE, size=10, bold=True, color="FFFFFF")
        celula.fill = PatternFill("solid", fgColor=COR_CAB)
        celula.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        celula.border = _borda


def _escrever(planilha_aba, tabela, com_niveis):
    _cabecalho(planilha_aba, COLUNAS_SAIDA)
    cores = {"Total Estratégia": COR_ESTRAT, "Total SubClasse": COR_SUB, "Total Classe": COR_CLASSE, "Total Geral": COR_GERAL}
    for ordem_item, reg in enumerate(tabela.to_dict("records"), 2):
        nivel = reg.get("Nível", "Ativo") if com_niveis else "Ativo"
        for ordem_aux, col in enumerate(COLUNAS_SAIDA, 1):
            valor = reg[col]
            if isinstance(valor, float) and np.isnan(valor):
                valor = None
            celula = planilha_aba.cell(ordem_item, ordem_aux, valor)
            celula.border = _borda
            celula.font = Font(name=FONTE, size=10, bold=nivel != "Ativo",
                          color="FFFFFF" if nivel == "Total Geral" else "000000")
            if col in VALORES:
                celula.number_format = FMT_VALOR
            elif col == "% Rent":
                celula.number_format = FMT_PCT
            if nivel in cores:
                celula.fill = PatternFill("solid", fgColor=cores[nivel])
    larguras = [18, 30, 54, 54] + [17] * len(VALORES) + [11]
    for ordem_aux, largura in enumerate(larguras, 1):
        planilha_aba.column_dimensions[get_column_letter(ordem_aux)].width = largura
    planilha_aba.freeze_panes = "E2"
    planilha_aba.row_dimensions[1].height = 28


def _blocoPonte(planilha_aba, ponte, cel, linha):
    """Ponte PL Inicial -> PL Final. Subtotais e resultado em formulas; o residuo deve ser 0,00."""
    planilha_aba.cell(linha, 1, "Ponte: o que explica a diferença (PL Inicial → PL Final)").font = Font(name=FONTE, size=12, bold=True, color="8F2A22")
    linha += 1
    for col, nome in zip("ABC", ["Item", "R$", "Fonte"]):
        celula = cel(f"{col}{linha}", nome, negrito=True, cor="FFFFFF")
        celula.fill = PatternFill("solid", fgColor=COR_CAB)
        celula.alignment = Alignment(horizontal="center")
    linha += 1

    def item(texto, valor, fonte="", negrito=False, fmt=FMT_VALOR):
        nonlocal linha
        cel(f"A{linha}", texto, negrito=negrito)
        cel(f"B{linha}", valor, fmt, negrito=negrito)
        cel(f"C{linha}", fonte)
        linha += 1
        return linha - 1

    r_pl = item("PL Inicial", ponte["pl_inicial"], "Planilha (ValorFinal do dia-base)", True)
    r_rend = item("(+) Rendimento dos ativos", ponte["rendimento"], "Planilha (RendimentoLiquida)")

    item("Caixa externo (extrato de conta corrente)", None, "ReportExtratoContaCorrente.xlsx", True)
    linha_inicio = linha
    for externo in ponte["externos"]:
        item(f"   {externo['data']:%d/%m} {externo['descricao']}", externo["valor"], "Extrato")
    r_ext = item("   Subtotal caixa externo", f"=SUM(B{linha_inicio}:B{linha - 1})" if ponte["externos"] else 0, "", True)

    item("Variação das provisões (valores a liquidar)", None, "Planilha, linhas 'Provisão' da aba Ativo", True)
    linha_inicio = linha
    for provisao in ponte["provisoes"]:
        fonte = "" if provisao["ini"] is None else f"{provisao['ini']:,.2f} → {provisao['fim']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        item(f"   {provisao['nome']}", provisao["delta"], fonte)
    r_prov = item("   Subtotal provisões", f"=SUM(B{linha_inicio}:B{linha - 1})" if ponte["provisoes"] else 0, "", True)

    r_rendas = item("(−) Rendas da planilha − cupom recebido em caixa", -(ponte["rendas"] - ponte["cupom_caixa"]),
                    f"Rendas {ponte['rendas']:,.2f} − extrato {ponte['cupom_caixa']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

    r_calc = item("PL Final calculado", f"=B{r_pl}+B{r_rend}+B{r_ext}+B{r_prov}+B{r_rendas}", "", True)
    r_fim = item("PL Final (planilha / PDF)", ponte["pl_final"], "Planilha (ValorFinal do último dia)")
    item("Resíduo (deve ser 0,00)", f"=B{r_fim}-B{r_calc}", "Se não for zero, falta algum lançamento", True)
    linha += 1
    r_exp = item("Diferença explicada (caixa + provisões + rendas)", f"=B{r_ext}+B{r_prov}+B{r_rendas}", "= PL Final − PL Inicial − Rendimento", True)
    r_cota = item("Diferença pela cota (passo 3)", "=B11", "Rentabilidade da cota × PL Inicial")
    item("Arredondamento da cota", f"=B{r_cota}-B{r_exp}", "Cota vem com 6 casas; centavos de diferença")


def _abaConferencia(planilha_aba, conferencia, ponte=None):
    """Aba separada: rentabilidade da carteira (cota) x ativos. Resultados em formulas."""
    def cel(ref, valor, fmt=None, negrito=False, cor="000000"):
        celula = planilha_aba[ref]
        celula.value = valor
        celula.font = Font(name=FONTE, size=10, bold=negrito, color=cor)
        celula.border = _borda
        if fmt:
            celula.number_format = fmt
        return celula

    planilha_aba["A1"].value = "Conferência da rentabilidade: carteira (cota) x ativos"
    planilha_aba["A1"].font = Font(name=FONTE, size=12, bold=True, color="8F2A22")
    planilha_aba["A2"].value = "Base: sempre o PL Inicial, nas duas pontas. Sem arredondar nos passos intermediários."
    planilha_aba["A2"].font = Font(name=FONTE, size=9, italic=True)

    cel("A4", "Rendimento total (Total Geral)")
    cel("B4", conferencia["rendimento"], FMT_VALOR)
    cel("A5", "PL Inicial total (Total Geral)")
    cel("B5", conferencia["pl_inicial"], FMT_VALOR)
    cel("A6", "Rentabilidade da carteira (cota)")
    cel("B6", conferencia["carteira"], "0.0000%")

    for col, nome in zip("ABCD", ["Passo", "Decimal / R$", "Em %", "Conta"]):
        celula = cel(f"{col}8", nome, negrito=True, cor="FFFFFF")
        celula.fill = PatternFill("solid", fgColor=COR_CAB)
        celula.alignment = Alignment(horizontal="center")
    cel("A9", "1) Rentabilidade simples dos ativos")
    cel("B9", "=B4/B5", "0.000000000")
    cel("C9", "=B9", "0.0000%")
    cel("D9", "Rendimento total ÷ PL Inicial total")
    cel("A10", "2) Diferença (carteira − ativos)")
    cel("B10", "=B6-B9", "0.000000000")
    cel("C10", "=B10", "0.0000%")
    cel("D10", "Negativo: a carteira rendeu menos que a soma dos ativos")
    cel("A11", "3) Diferença em reais", negrito=True)
    cel("B11", "=B10*B5", FMT_VALOR, negrito=True)
    cel("C11", None)
    cel("D11", "Diferença (decimal) × PL Inicial total")

    planilha_aba["A13"].value = textosConferencia(conferencia)[-1]
    planilha_aba["A13"].font = Font(name=FONTE, size=10)
    if ponte:
        _blocoPonte(planilha_aba, ponte, cel, 15)
    planilha_aba.column_dimensions["A"].width = 62
    planilha_aba.column_dimensions["B"].width = 20
    planilha_aba.column_dimensions["C"].width = 40
    planilha_aba.column_dimensions["D"].width = 58


def salvarExcel(ativos, disposicao, avisos, caminho, ponte=None):
    pasta_trabalho = Workbook()
    planilha_aba = pasta_trabalho.active
    planilha_aba.title = "Rentabilidade"
    _escrever(planilha_aba, disposicao, com_niveis=True)

    wa = pasta_trabalho.create_sheet("Ativos")
    _escrever(wa, ativos, com_niveis=False)
    wa.auto_filter.ref = f"A1:{get_column_letter(len(COLUNAS_SAIDA))}{len(ativos) + 1}"

    _abaConferencia(pasta_trabalho.create_sheet("Conferencia"), ativos.attrs["conferencia"], ponte)

    wi = pasta_trabalho.create_sheet("Info")
    linhas = [
        ("Tratamento da aba Ativo (Relatorio_Rentabilidade.xlsx)", True),
        (f"Periodo: {ativos.attrs['inicio']:%d/%m/%Y} a {ativos.attrs['fim']:%d/%m/%Y}", False),
        (f"Gerado em {datetime.now():%d/%m/%Y %H:%M}", False),
        ("", False),
        ("PL Inicial = ValorFinal do dia-base (nao soma). PL Final = ValorFinal do ultimo dia (nao soma).", False),
        ("Entradas, Saidas, Rendas e Rendimento = soma dos dias depois do dia-base.", False),
        ("% Rent = juros compostos: produto de (1 + rendimento do dia / valor inicial do dia) - 1.", False),
        ("Linhas de total: os valores somam os ativos. % Rent de Estrategia, SubClasse e Classe = mesma conta composta do grupo.", False),
        ("% Rent do Total Geral = rentabilidade da carteira (RentabilidadeCotaBruta, aba Estrategia), igual ao cabecalho do PDF.", False),
        ("A ordem dos ativos dentro de cada estrategia e alfabetica (no PDF e outra).", False),
        ("", False),
        ("Avisos" if avisos else "Sem avisos: PL Inicial + Entradas - Saidas - Rendas + Rendimento = PL Final em todos os ativos.", True),
    ] + [(aviso, False) for aviso in avisos]
    for ordem_item, (texto, negrito) in enumerate(linhas, 1):
        celula = wi.cell(ordem_item, 1, texto)
        celula.font = Font(name=FONTE, size=11 if negrito else 10, bold=negrito, color="8F2A22" if negrito else "000000")
    wi.column_dimensions["A"].width = 120
    pasta_trabalho.save(caminho)


# ----------------------------------------------------------------------------
# Analise por carteira: cota x PL x movimentacao de cotistas
#
# Pergunta que esta secao responde:
#   "Se a carteira so tivesse rentabilidade, o PL Final seria igual ao PL Final real?"
#
#   1) PL Final esperado pela cota = PL Inicial x (1 + cota)
#   2) Diferenca                   = PL Final real - esperado
#   3) Se houve aplicacao/resgate de cotas, o PL muda sem passar pela rentabilidade:
#        efeito = soma(sinal x quantidade de cotas) x cota do ultimo dia
#   4) Residuo = PL Final real - (esperado + efeito)   -> o que sobra sem explicacao
#
# Usada pelo Excel (salvar_excel_multi) e pelo app Streamlit (app.py).
# ----------------------------------------------------------------------------
COL_ID = "id_cliente_consulta"
ABA_HIST_COTA = "HistCota"
ABA_OP_COTISTA = "OpCotista"
TOLERANCIA_REAIS = 1.00            # ate isso a diferenca e so arredondamento
TOLERANCIA_EXPLICADA_PCT = 0.0005  # 0,05% do PL Inicial: sobra aceitavel depois de descontar as cotas movimentadas

STATUS_OK = "Sem divergência"
STATUS_EXPLICADA = "Explicada por cotistas"
STATUS_DIVERGENTE = "Divergente"

COLUNAS_OPERACOES = ["Data", "Tipo", "Quantidade", "Valor bruto", "Valor líquido", "IR", "Sinal"]


def fmtBrl(valor, casas=2):
    """R$ no formato brasileiro, com sinal de menos tipografico."""
    if valor is None or (isinstance(valor, float) and np.isnan(valor)):
        return "—"
    if round(valor, casas) == 0:
        valor = 0.0
    texto = f"{abs(valor):,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"−R$ {texto}" if valor < 0 else f"R$ {texto}"


def fmtPct(valor, casas=4):
    if valor is None or (isinstance(valor, float) and np.isnan(valor)):
        return "—"
    return f"{valor * 100:.{casas}f}%".replace(".", ",")


def _sinalOperacao(tipo):
    """+1 aplicacao (entra cota), -1 resgate/come-cotas (sai cota), 0 desconhecido."""
    texto_tipo = str(tipo).strip().lower()
    if texto_tipo.startswith("aplic"):
        return 1
    if texto_tipo.startswith("resgate") or "come cota" in texto_tipo or "comecota" in texto_tipo:
        return -1
    return 0


def resumoCotistas(ops, hist, inicio, fim):
    """Movimentacao de cotas da carteira no periodo.

    ops  - aba OpCotista (API OperacaoCotistaAnalitico_PorCarteiraPeriodo), pode ser vazia
    hist - aba HistCota (API BuscaHistoricoCotaDia): cota, PL e quantidade de cotas por dia
    """
    cot = {"disponivel": False, "n_operacoes": 0, "aplicacoes": 0.0, "resgates": 0.0, "fluxo_valor": 0.0,
           "fluxo_qtd": 0.0, "qtd_ini": None, "qtd_fim": None, "cota_ini": None, "cota_fim": None,
           "pl_cota_ini": None, "pl_cota_fim": None, "qtd_confere": None, "desconhecidas": [],
           "operacoes": pd.DataFrame(columns=COLUNAS_OPERACOES), "historico": None}

    if hist is not None and not hist.empty:
        tb_hist = hist.copy()
        tb_hist["Data"] = pd.to_datetime(tb_hist["Data"])
        tb_hist = tb_hist.sort_values("Data").reset_index(drop=True)
        cot["historico"] = tb_hist
        hist_inicio, hist_fim = tb_hist[tb_hist["Data"] == inicio], tb_hist[tb_hist["Data"] == fim]
        if not hist_inicio.empty and not hist_fim.empty:
            cot.update(disponivel=True,
                       qtd_ini=float(hist_inicio.iloc[0]["QuantidadeFechamento"]), qtd_fim=float(hist_fim.iloc[0]["QuantidadeFechamento"]),
                       cota_ini=float(hist_inicio.iloc[0]["CotaFechamento"]), cota_fim=float(hist_fim.iloc[0]["CotaFechamento"]),
                       pl_cota_ini=float(hist_inicio.iloc[0]["PLFechamento"]), pl_cota_fim=float(hist_fim.iloc[0]["PLFechamento"]))

    if ops is not None and not ops.empty:
        tb_ops = ops.copy()
        tb_ops["DataConversao"] = pd.to_datetime(tb_ops["DataConversao"])
        tb_ops = tb_ops[(tb_ops["DataConversao"] > inicio) & (tb_ops["DataConversao"] <= fim)].copy()
        for coluna in ("Quantidade", "ValorBruto", "ValorLiquido", "ValorIR"):
            tb_ops[coluna] = pd.to_numeric(tb_ops[coluna], errors="coerce").fillna(0.0) if coluna in tb_ops.columns else 0.0
        tb_ops["Sinal"] = tb_ops["TipoOperacao"].map(_sinalOperacao)
        cot["desconhecidas"] = sorted(set(tb_ops.loc[tb_ops["Sinal"] == 0, "TipoOperacao"].astype(str)))
        cot["aplicacoes"] = float(tb_ops.loc[tb_ops["Sinal"] > 0, "ValorBruto"].sum())
        cot["resgates"] = float(tb_ops.loc[tb_ops["Sinal"] < 0, "ValorBruto"].sum())
        cot["fluxo_valor"] = cot["aplicacoes"] - cot["resgates"]
        cot["fluxo_qtd"] = float((tb_ops["Sinal"] * tb_ops["Quantidade"]).sum())
        cot["n_operacoes"] = int(len(tb_ops))
        cot["operacoes"] = (tb_ops.sort_values("DataConversao")
                            .rename(columns={"DataConversao": "Data", "TipoOperacao": "Tipo", "ValorBruto": "Valor bruto",
                                             "ValorLiquido": "Valor líquido", "ValorIR": "IR"})[COLUNAS_OPERACOES]
                            .reset_index(drop=True))

    if cot["disponivel"]:
        dif_qtd = (cot["qtd_fim"] - cot["qtd_ini"]) - cot["fluxo_qtd"]
        cot["qtd_confere"] = abs(dif_qtd) <= max(1.0, 1e-6 * abs(cot["qtd_ini"]))
    return cot


def resumoDivergencia(ativos, cot=None):
    """Confere cota x ativos e o PL Final que a cota implica x PL Final da planilha (com ou sem cotistas)."""
    conferencia = ativos.attrs["conferencia"]
    pl_final = float(ativos["PL Final"].sum())
    pl_cota = conferencia["pl_inicial"] * (1 + conferencia["carteira"])
    resumo = {**conferencia, "pl_final": pl_final, "pl_final_cota": pl_cota, "dif_pl": pl_final - pl_cota,
         "efeito_cotas": None, "pl_final_ajustado": None, "residuo_cotistas": None}
    if cot and cot["disponivel"]:
        efeito = cot["fluxo_qtd"] * cot["cota_fim"]
        resumo.update(efeito_cotas=efeito, pl_final_ajustado=pl_cota + efeito,
                 residuo_cotistas=pl_final - (pl_cota + efeito))
    return resumo


def classificar(resumo, cot):
    """(status, mensagem em portugues) para a carteira."""
    dif = resumo["dif_pl"]
    if abs(dif) <= TOLERANCIA_REAIS:
        return STATUS_OK, ("O PL final fechou com a rentabilidade da cota (diferença de "
                           f"{fmtBrl(dif)}). Não houve movimentação relevante de cotas no período.")
    sentido = "saiu" if dif < 0 else "entrou"
    if resumo["residuo_cotistas"] is None:
        return STATUS_DIVERGENTE, (f"O PL final difere do esperado pela cota em {fmtBrl(dif)} ({sentido} dinheiro por fora da "
                                   "rentabilidade) e não foi possível buscar o histórico de cotas para explicar.")
    limite = max(TOLERANCIA_REAIS, TOLERANCIA_EXPLICADA_PCT * resumo["pl_inicial"])
    if cot["n_operacoes"] and abs(resumo["residuo_cotistas"]) <= limite:
        return STATUS_EXPLICADA, (
            f"O PL final difere do esperado pela cota em {fmtBrl(dif)} porque {sentido} dinheiro por movimentação de cotas: "
            f"{cot['n_operacoes']} operações (aplicações {fmtBrl(cot['aplicacoes'])}, resgates {fmtBrl(cot['resgates'])}). "
            f"Depois de descontá-las, sobra {fmtBrl(resumo['residuo_cotistas'])} "
            f"({fmtPct(abs(resumo['residuo_cotistas']) / resumo['pl_inicial'])} do PL inicial), efeito de datas e tributos.")
    if not cot["n_operacoes"]:
        return STATUS_DIVERGENTE, (f"O PL final difere do esperado pela cota em {fmtBrl(dif)} e não há aplicação nem resgate "
                                   "de cotas no período que explique. Precisa de investigação.")
    return STATUS_DIVERGENTE, (f"Mesmo descontando a movimentação de cotas, sobram {fmtBrl(resumo['residuo_cotistas'])} "
                               f"({fmtPct(abs(resumo['residuo_cotistas']) / resumo['pl_inicial'])} do PL inicial) sem explicação.")


def montarPonteCotistas(ativos, cot):
    """Ponte para carteiras com movimentacao de cotas: PL Inicial + Rendimento + cotistas + outros = PL Final."""
    pl_i, rend = float(ativos["PL Inicial"].sum()), float(ativos["Rendimento"].sum())
    pl_f = float(ativos["PL Final"].sum())
    return {"pl_inicial": pl_i, "rendimento": rend, "pl_final": pl_f, "fluxo_valor": cot["fluxo_valor"],
            "operacoes": cot["operacoes"], "outros": pl_f - (pl_i + rend + cot["fluxo_valor"])}


def explicarDiferenca(dif):
    """Texto do passo 'Diferenca' (PL real - PL esperado pela cota), conforme o valor."""
    if abs(dif) <= TOLERANCIA_REAIS:
        return (f"Praticamente zero ({fmtBrl(dif)} é arredondamento): o PL real é igual ao que a rentabilidade explica. "
                "Não saiu nem entrou dinheiro por fora da cota.")
    if dif < 0:
        return (f"O PL real ficou {fmtBrl(abs(dif))} ABAIXO do que a rentabilidade explica. Ou seja, saiu esse valor da carteira "
                "sem passar pela cota (por exemplo, resgate de cotas). Os próximos passos verificam se foi isso.")
    return (f"O PL real ficou {fmtBrl(dif)} ACIMA do que a rentabilidade explica. Ou seja, entrou esse valor na carteira "
            "sem passar pela cota (por exemplo, aplicação de cotas). Os próximos passos verificam se foi isso.")


COLUNAS_CONTRIBUICAO = ["Classe", "SubClasse", "Estratégia", "Ativo", "PL Inicial", "Rendimento", "% Rent", "Contribuição"]


def contribuicaoAtivos(ativos):
    """Quanto cada ativo contribuiu para a rentabilidade da carteira (do maior para o menor).

    Contribuição = Rendimento do ativo ÷ PL Inicial TOTAL da carteira (em fração; 0,0021 = 0,21 p.p.).
    A soma de todas as contribuições é a rentabilidade simples dos ativos (Rendimento total ÷ PL Inicial total).
    Ativos sem rendimento (provisão, caixa) ficam de fora.
    """
    pl_total = float(ativos["PL Inicial"].sum())
    tb_contribuicao = ativos.loc[ativos["Rendimento"].abs() > 0.005, COLUNAS_CONTRIBUICAO[:-1]].copy()
    tb_contribuicao["Contribuição"] = tb_contribuicao["Rendimento"] / pl_total if pl_total else 0.0
    return tb_contribuicao.sort_values("Contribuição", ascending=False).reset_index(drop=True)


def montarPassos(resumo, cot):
    """Passo a passo em dados (para o app): grupo, rotulo, valor, tipo, explicacao, destaque."""
    lista_passos = []

    def adicionarLinha(grupo, rotulo, valor, tipo, expl, destaque=False):
        lista_passos.append({"grupo": grupo, "rotulo": rotulo, "valor": valor, "tipo": tipo, "explicacao": expl, "destaque": destaque})

    g1 = "A cota explica o PL?"
    adicionarLinha(g1, "PL inicial", resumo["pl_inicial"], "brl", "Valor da carteira no dia-base.")
    adicionarLinha(g1, "Rentabilidade da cota", resumo["carteira"], "pct", "Quanto a carteira rendeu no período, segundo a cota.")
    adicionarLinha(g1, "PL final esperado pela cota", resumo["pl_final_cota"], "brl",
        "PL inicial × (1 + cota). É o PL final se não houvesse aplicação nem resgate.")
    adicionarLinha(g1, "PL final real", resumo["pl_final"], "brl", "Valor da carteira no último dia, direto da planilha.")
    adicionarLinha(g1, "Diferença (PL real − PL esperado)", resumo["dif_pl"], "brl", explicarDiferenca(resumo["dif_pl"]), True)

    g2 = "Movimentação de cotistas"
    if not cot["disponivel"]:
        adicionarLinha(g2, "Dados de cotistas", None, "txt", "Histórico de cotas não encontrado. Rode o teste.py de novo.")
        return lista_passos
    adicionarLinha(g2, "Aplicações de cotas", cot["aplicacoes"], "brl", "Soma do valor bruto das aplicações no período.")
    adicionarLinha(g2, "Resgates de cotas", cot["resgates"], "brl", "Soma do valor bruto dos resgates no período.")
    adicionarLinha(g2, "Movimento líquido", cot["fluxo_valor"], "brl", "Aplicações − resgates.")
    adicionarLinha(g2, "Cotas no início", cot["qtd_ini"], "qtd", "Quantidade de cotas no dia-base (histórico de cotas).")
    adicionarLinha(g2, "Cotas no fim", cot["qtd_fim"], "qtd", "Quantidade de cotas no último dia.")
    adicionarLinha(g2, "Variação de cotas", cot["qtd_fim"] - cot["qtd_ini"], "qtd", "Quantas cotas entraram (+) ou saíram (−): cotas no fim − cotas no início.")
    adicionarLinha(g2, "Soma das operações em cotas", cot["fluxo_qtd"], "qtd",
        "Deve ser igual à variação da quantidade de cotas: confirma que a variação veio das operações."
        + ("" if cot["qtd_confere"] else " ATENÇÃO: não bate."))
    adicionarLinha(g2, "Cota no último dia", cot["cota_fim"], "cota", "Cota de fechamento do último dia.")
    adicionarLinha(g2, "Efeito dos movimentos no PL", resumo["efeito_cotas"], "brl",
        "Soma das operações em cotas × cota do último dia.")

    g3 = "Conclusão"
    adicionarLinha(g3, "PL final esperado com cotistas", resumo["pl_final_ajustado"], "brl", "Esperado pela cota + efeito dos movimentos.")
    adicionarLinha(g3, "Resíduo (o que sobra sem explicação)", resumo["residuo_cotistas"], "brl",
        "PL final real − esperado com cotistas. Perto de zero = explicado.", True)
    return lista_passos


def rentEncadeada(d_ativo, inicio, fim):
    """Rentabilidade dos ativos encadeada dia a dia: produto de (1 + rendimento do dia / valor inicial do dia) - 1."""
    df = d_ativo[~d_ativo["Estrategia"].isin(EXCLUIR_ESTRATEGIAS)].copy()
    df["Data"] = pd.to_datetime(df["Data"])
    df = df[(df["Data"] > inicio) & (df["Data"] <= fim)]
    for coluna in ("ValorInicial", "RendimentoLiquida"):
        df[coluna] = pd.to_numeric(df[coluna], errors="coerce").fillna(0.0)
    dia = df.groupby("Data")[["ValorInicial", "RendimentoLiquida"]].sum()
    dia = dia[dia["ValorInicial"] != 0]
    return float((1 + dia["RendimentoLiquida"] / dia["ValorInicial"]).prod() - 1)


def lerNomeExtrato(caminho):
    """Nome do cliente no cabecalho do extrato de conta corrente ('Cliente: ...')."""
    try:
        valor_bruto = pd.read_excel(caminho, header=None)
    except Exception:
        return None
    for ordem_item in range(min(len(valor_bruto), 30)):
        vals = valor_bruto.iloc[ordem_item].tolist()
        for ordem_aux, valor in enumerate(vals):
            if isinstance(valor, str) and valor.strip().rstrip(":").lower() == "cliente":
                for proximo in vals[ordem_aux + 1:]:
                    if isinstance(proximo, str) and proximo.strip():
                        return re.sub(r"\s+", " ", proximo).strip()
    return None


def analisarCarteira(id_cliente, d_ativo, hist, ops, rentab, inicio=None, fim=None, arq_extrato=None):
    """Analise completa de uma carteira. Levanta ValueError se a aba Ativo nao der para tratar."""
    ativos, disposicao, avisos = tratar(d_ativo, inicio, fim, rentab)
    cot = resumoCotistas(ops, hist, ativos.attrs["inicio"], ativos.attrs["fim"])
    if not cot["disponivel"]:
        avisos.append("Histórico de cotas (aba HistCota) não encontrado: não dá para explicar divergências por cotistas.")
    elif cot["qtd_confere"] is False:
        avisos.append("A variação da quantidade de cotas não bate com a soma das operações de cotistas.")
    if cot["desconhecidas"]:
        avisos.append("Tipo(s) de operação de cotista não classificados (ignorados): " + ", ".join(cot["desconhecidas"]))

    resumo = resumoDivergencia(ativos, cot)
    status, mensagem = classificar(resumo, cot)

    nome, ponte, ponte_cot = None, None, None
    arq = Path(arq_extrato) if arq_extrato else None
    extrato_ok = bool(arq and arq.exists())
    if extrato_ok:
        nome = lerNomeExtrato(arq)
    if cot["n_operacoes"]:
        # Com movimentacao de cotas, o extrato e as provisoes nao fecham sozinhos: usa a ponte de cotistas
        ponte_cot = montarPonteCotistas(ativos, cot)
    elif extrato_ok:
        try:
            ponte = montarPonte(d_ativo, ativos, lerExtrato(arq))
            if abs(ponte["residuo"]) > 0.05:
                avisos.append(f"Ponte: resíduo de {fmtBrl(ponte['residuo'])}. Falta algum lançamento (extrato ou provisão).")
        except ValueError as erro:
            avisos.append(f"Ponte não gerada: {erro}")
    else:
        avisos.append("Ponte não gerada: extrato de conta corrente não encontrado.")

    # Despesas do extrato (so para a planilha); com cotistas a ponte nao usa o extrato, entao le aqui
    externos = None
    if ponte:
        externos = ponte["externos"]
    elif extrato_ok:
        try:
            extensao = lerExtrato(arq)
            extensao = extensao[(extensao["Movimento"] > ativos.attrs["inicio"]) & (extensao["Movimento"] <= ativos.attrs["fim"]) & (extensao["Tipo"] == "Externo")]
            externos = [{"data": externo.Movimento, "descricao": externo.Descricao, "valor": externo.Valor} for externo in extensao.itertuples()]
        except ValueError:
            pass
    try:
        encadeada = rentEncadeada(d_ativo, ativos.attrs["inicio"], ativos.attrs["fim"])
    except (KeyError, ValueError):
        encadeada = None

    return {"id": str(id_cliente), "nome": nome or f"Carteira {id_cliente}", "ativos": ativos, "layout": disposicao,
            "encadeada": encadeada, "externos_extrato": externos,
            "avisos": avisos, "resumo": resumo, "cot": cot, "status": status, "mensagem": mensagem,
            "passos": montarPassos(resumo, cot), "ponte": ponte, "ponte_cotistas": ponte_cot,
            "contribuicoes": contribuicaoAtivos(ativos)}


def _lerAba(entrada, aba):
    try:
        return pd.read_excel(entrada, sheet_name=aba)
    except ValueError:
        return None


def _doId(df, id_cliente):
    if df is None:
        return None
    if COL_ID not in df.columns:
        return df.iloc[0:0]
    return df[df[COL_ID].astype(str) == str(id_cliente)]


def analisarTodas(entrada, inicio=None, fim=None, pasta_extratos=None):
    """Analisa todas as carteiras do Relatorio_Rentabilidade.xlsx. Retorna ({id: analise}, {id: erro})."""
    df = pd.read_excel(entrada, sheet_name=ABA_ATIVO)
    if COL_ID not in df.columns:
        raise ValueError(f"A aba '{ABA_ATIVO}' não tem a coluna '{COL_ID}'. Rode o teste.py para gerar o arquivo.")
    hist, ops = _lerAba(entrada, ABA_HIST_COTA), _lerAba(entrada, ABA_OP_COTISTA)
    pasta = Path(pasta_extratos) if pasta_extratos else EXTRATOS_PADRAO
    analises, erros = {}, {}
    for id_cliente, d_id in df.groupby(df[COL_ID].astype(str), sort=False):
        try:
            analises[id_cliente] = analisarCarteira(
                id_cliente, d_id, _doId(hist, id_cliente), _doId(ops, id_cliente),
                lerRentabilidadeCarteira(entrada, id_cliente), inicio, fim,
                pasta / f"ReportExtratoContaCorrente_{id_cliente}.xlsx")
        except ValueError as erro:
            erros[id_cliente] = str(erro)
    return analises, erros


# ----------------------------------------------------------------------------
# Excel com varias carteiras
# ----------------------------------------------------------------------------
FMT_QTD = '#,##0.000000;[Red](#,##0.000000)'
FMT_COTA = '0.00000000'
COR_STATUS = {STATUS_OK: ("E2F0D9", "375623"), STATUS_EXPLICADA: ("FFF2CC", "7F6000"), STATUS_DIVERGENTE: ("F8CBAD", "C00000")}


def _nota(planilha_aba, ref, texto, negrito=False, cor="595959", tamanho=9):
    celula = planilha_aba[ref]
    celula.value = texto
    celula.font = Font(name=FONTE, size=tamanho, italic=not negrito, bold=negrito, color=cor)
    return celula


def _abaDivergencias(planilha_aba, analises):
    """Tabela-resumo (com formulas e a conta de cada coluna) + passo a passo por carteira."""
    cols = ["Carteira", "Nome", "PL Inicial", "Rendimento ativos", "% Ativos (simples)", "% Cota", "Dif. p.p.",
            "Dif. R$ (cota x ativos)", "PL Final planilha", "PL Final pela cota", "Dif. PL Final R$",
            "Aplicações cotistas R$", "Resgates cotistas R$", "Efeito das cotas no PL R$", "PL Final esperado c/ cotistas",
            "Resíduo R$", "Status"]
    contas = ["ID da carteira", "Cabeçalho do extrato de C/C", "Planilha: ValorFinal no dia-base",
              "Planilha: soma do RendimentoLiquida", "= Rendimento ÷ PL Inicial", "Aba Estrategia: RentabilidadeCotaBruta",
              "= % Cota − % Ativos", "= Dif. p.p. × PL Inicial", "Planilha: ValorFinal no último dia",
              "= PL Inicial × (1 + % Cota)", "= PL Final planilha − PL Final pela cota",
              "API: operações de cotista (valor bruto)", "API: operações de cotista (valor bruto)",
              "= Σ(sinal × cotas) × cota do último dia", "= PL Final pela cota + Efeito das cotas",
              "= PL Final planilha − esperado c/ cotistas",
              f"Sem divergência se |Dif. PL Final| ≤ R$ {TOLERANCIA_REAIS:.2f}; Explicada se há operações e |Resíduo| ≤ "
              f"{TOLERANCIA_EXPLICADA_PCT * 100:.2f}% do PL Inicial"]
    _cabecalho(planilha_aba, cols)
    for ordem_aux, descricao_conta in enumerate(contas, 1):
        celula = planilha_aba.cell(2, ordem_aux, descricao_conta)
        celula.font = Font(name=FONTE, size=8, italic=True, color="595959")
        celula.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        celula.border = _borda
    planilha_aba.row_dimensions[1].height = 32
    planilha_aba.row_dimensions[2].height = 60

    qt_carteiras = len(analises)
    for ordem_item, (id_cliente, analise) in enumerate(analises.items(), 3):
        resumo, cot = analise["resumo"], analise["cot"]
        tem_cot = cot["disponivel"]
        vals = [id_cliente, analise["nome"], resumo["pl_inicial"], resumo["rendimento"], f"=D{ordem_item}/C{ordem_item}", resumo["carteira"], f"=F{ordem_item}-E{ordem_item}",
                f"=G{ordem_item}*C{ordem_item}", resumo["pl_final"], f"=C{ordem_item}*(1+F{ordem_item})", f"=I{ordem_item}-J{ordem_item}",
                cot["aplicacoes"] if tem_cot else None, cot["resgates"] if tem_cot else None,
                resumo["efeito_cotas"] if tem_cot else None, f"=J{ordem_item}+N{ordem_item}" if tem_cot else None,
                f"=I{ordem_item}-O{ordem_item}" if tem_cot else None,
                (f'=IF(ABS(K{ordem_item})<={TOLERANCIA_REAIS},"{STATUS_OK}",'
                 f'IF(AND(L{ordem_item}+M{ordem_item}>0,ABS(P{ordem_item})<=MAX({TOLERANCIA_REAIS},{TOLERANCIA_EXPLICADA_PCT}*C{ordem_item})),"{STATUS_EXPLICADA}","{STATUS_DIVERGENTE}"))'
                 if tem_cot else f'=IF(ABS(K{ordem_item})<={TOLERANCIA_REAIS},"{STATUS_OK}","{STATUS_DIVERGENTE}")')]
        fmts = [None, None, FMT_VALOR, FMT_VALOR, "0.0000%", "0.0000%", "0.0000%", FMT_VALOR, FMT_VALOR, FMT_VALOR,
                FMT_VALOR, FMT_VALOR, FMT_VALOR, FMT_VALOR, FMT_VALOR, FMT_VALOR, None]
        for ordem_aux, (valor, formato) in enumerate(zip(vals, fmts), 1):
            celula = planilha_aba.cell(ordem_item, ordem_aux, valor)
            celula.border = _borda
            celula.font = Font(name=FONTE, size=10, bold=ordem_aux == len(vals))
            if formato:
                celula.number_format = formato
    ult = qt_carteiras + 2
    for status, (fundo, fonte) in COR_STATUS.items():
        planilha_aba.conditional_formatting.add(f"Q3:Q{ult}", CellIsRule(
            operator="equal", formula=[f'"{status}"'], font=Font(name=FONTE, bold=True, color=fonte),
            fill=PatternFill("solid", bgColor=fundo, fgColor=fundo)))
    planilha_aba.freeze_panes = "C3"

    # ---- Passo a passo por carteira ----
    linha = qt_carteiras + 5
    planilha_aba.cell(linha, 1, "Passo a passo por carteira").font = Font(name=FONTE, size=12, bold=True, color="8F2A22")
    linha += 1
    _nota(planilha_aba, f"A{linha}", "Pergunta: se a carteira só tivesse rentabilidade (sem aporte nem resgate de cotas), "
                           "o PL Final seria igual ao PL Final real?")
    linha += 2

    for id_cliente, analise in analises.items():
        resumo, cot, ativos = analise["resumo"], analise["cot"], analise["ativos"]
        for col in "ABC":
            planilha_aba[f"{col}{linha}"].fill = PatternFill("solid", fgColor=COR_CAB)
        planilha_aba.cell(linha, 1, f"Carteira {id_cliente} · {analise['nome']}").font = Font(name=FONTE, size=10, bold=True, color="FFFFFF")
        linha += 1

        def item(rotulo, valor, fmt, expl, negrito=False):
            nonlocal linha
            planilha_aba.cell(linha, 1, rotulo).font = Font(name=FONTE, size=10, bold=negrito)
            celula = planilha_aba.cell(linha, 2, valor)
            celula.number_format = fmt
            celula.font = Font(name=FONTE, size=10, bold=negrito)
            _nota(planilha_aba, f"C{linha}", expl)
            linha += 1
            return linha - 1

        def sub(texto):
            nonlocal linha
            _nota(planilha_aba, f"A{linha}", texto, negrito=True, cor="8F2A22", tamanho=10)
            linha += 1

        sub("A cota explica o PL?")
        l_pl = item("1) PL Inicial (dia-base)", resumo["pl_inicial"], FMT_VALOR, "Valor da carteira no dia-base.")
        l_cota = item("2) Rentabilidade da cota", resumo["carteira"], "0.0000%", "Quanto a carteira rendeu no período, segundo a cota.")
        l_esp = item("3) PL Final esperado pela cota", f"=B{l_pl}*(1+B{l_cota})", FMT_VALOR,
                     "= (1) × (1 + (2)). O PL Final se NÃO houvesse aporte nem resgate.")
        l_real = item("4) PL Final real (último dia)", resumo["pl_final"], FMT_VALOR, "Valor da carteira no último dia, direto da planilha.")
        item("5) Diferença = (4) − (3)", f"=B{l_real}-B{l_esp}", FMT_VALOR, explicarDiferenca(resumo["dif_pl"]), True)

        if cot["disponivel"]:
            sub("Movimentação de cotistas (API: OperacaoCotistaAnalitico_PorCarteiraPeriodo + BuscaHistoricoCotaDia)")
            l_ap = item("6) Aplicações de cotas (R$)", cot["aplicacoes"], FMT_VALOR, "Soma do valor bruto das aplicações no período.")
            l_rg = item("7) Resgates de cotas (R$)", cot["resgates"], FMT_VALOR, "Soma do valor bruto dos resgates no período.")
            item("8) Movimento líquido = (6) − (7)", f"=B{l_ap}-B{l_rg}", FMT_VALOR, "Negativo: saiu dinheiro dos cotistas.")
            l_qi = item("9) Cotas no início", cot["qtd_ini"], FMT_QTD, "Quantidade de cotas no dia-base (BuscaHistoricoCotaDia).")
            l_qf = item("10) Cotas no fim", cot["qtd_fim"], FMT_QTD, "Quantidade de cotas no último dia.")
            l_dq = item("11) Variação de cotas = (10) − (9)", f"=B{l_qf}-B{l_qi}", FMT_QTD, "Quantas cotas entraram (+) ou saíram (−).")
            l_sq = item("12) Soma das operações em cotas", cot["fluxo_qtd"], FMT_QTD,
                        "Deve ser igual a (11): confirma que a variação de cotas veio das operações listadas." +
                        ("" if cot["qtd_confere"] else " ATENÇÃO: não bate."))
            l_ct = item("13) Cota no último dia", cot["cota_fim"], FMT_COTA, "Cota de fechamento do último dia.")
            l_ef = item("14) Efeito dos movimentos no PL = (12) × (13)", f"=B{l_sq}*B{l_ct}", FMT_VALOR,
                        "Quanto as cotas movimentadas pesam no PL final.")
            l_ae = item("15) PL Final esperado c/ cotistas = (3) + (14)", f"=B{l_esp}+B{l_ef}", FMT_VALOR,
                        "O PL final se a carteira só rendesse E só houvesse as operações de cotistas listadas.")
            item("16) Resíduo = (4) − (15)", f"=B{l_real}-B{l_ae}", FMT_VALOR,
                 "O que sobra sem explicação. Perto de zero: divergência explicada (efeito de datas e tributos).", True)
        else:
            sub("Movimentação de cotistas: sem dados (aba HistCota ausente). Rode o teste.py novamente.")

        fundo, fonte = COR_STATUS[analise["status"]]
        celula = planilha_aba.cell(linha, 1, f"Conclusão: {analise['status']}. {analise['mensagem']}")
        celula.font = Font(name=FONTE, size=10, bold=True, color=fonte)
        celula.fill = PatternFill("solid", fgColor=fundo)
        for col in "BC":
            planilha_aba[f"{col}{linha}"].fill = PatternFill("solid", fgColor=fundo)
        linha += 1
        entradas, saidas = float(ativos["Entradas"].sum()), float(ativos["Saídas"].sum())
        planilha_aba.cell(linha, 1, "Referência: Entradas − Saídas dos ativos").font = Font(name=FONTE, size=10)
        planilha_aba.cell(linha, 2, entradas - saidas).number_format = FMT_VALOR
        _nota(planilha_aba, f"C{linha}", f"Entradas {fmtBrl(entradas)} − Saídas {fmtBrl(saidas)}. Só referência: movimento entre caixa e "
                               "ativos não mexe no PL.")
        linha += 2

    planilha_aba.column_dimensions["A"].width = 46
    planilha_aba.column_dimensions["B"].width = 34
    for ordem_aux in range(3, len(cols) + 1):
        planilha_aba.column_dimensions[get_column_letter(ordem_aux)].width = 20
    planilha_aba.column_dimensions["Q"].width = 26


def _abaOpCotistas(planilha_aba, analises):
    """Todas as operacoes de cotistas das carteiras (aplicacoes e resgates de cotas)."""
    cols = ["Carteira", "Nome", "Data", "Tipo", "Quantidade de cotas", "Valor bruto", "Valor líquido", "IR", "Efeito (+/−)"]
    _cabecalho(planilha_aba, cols)
    ordem_item = 2
    for id_cliente, analise in analises.items():
        for _, operacao in analise["cot"]["operacoes"].iterrows():
            vals = [id_cliente, analise["nome"], operacao["Data"].to_pydatetime(), operacao["Tipo"], float(operacao["Quantidade"]),
                    float(operacao["Valor bruto"]), float(operacao["Valor líquido"]), float(operacao["IR"]),
                    "Entra" if operacao["Sinal"] > 0 else "Sai" if operacao["Sinal"] < 0 else "Não classificado"]
            for ordem_aux, valor in enumerate(vals, 1):
                celula = planilha_aba.cell(ordem_item, ordem_aux, valor)
                celula.border = _borda
                celula.font = Font(name=FONTE, size=10)
                if ordem_aux == 3:
                    celula.number_format = "dd/mm/yyyy"
                elif ordem_aux == 5:
                    celula.number_format = FMT_QTD
                elif ordem_aux in (6, 7, 8):
                    celula.number_format = FMT_VALOR
            ordem_item += 1
    if ordem_item == 2:
        planilha_aba.cell(2, 1, "Nenhuma aplicação ou resgate de cotas no período.").font = Font(name=FONTE, size=10, italic=True)
    for ordem_aux, largura in enumerate([12, 50, 12, 24, 22, 18, 18, 12, 18], 1):
        planilha_aba.column_dimensions[get_column_letter(ordem_aux)].width = largura
    planilha_aba.freeze_panes = "A2"
    if ordem_item > 2:
        planilha_aba.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{ordem_item - 1}"


def degrausContribuicao(analise):
    """Do somatorio das contribuicoes ate a cota, em degraus: [(descricao, tipo, valor R$, fracao do PL inicial)]."""
    pl_i = float(analise["resumo"]["pl_inicial"])
    cota = float(analise["resumo"]["carteira"])
    soma_ativos = float(analise["contribuicoes"]["Contribuição"].sum())
    enc = analise.get("encadeada")
    enc = soma_ativos if enc is None else enc
    linhas = [("Soma das contribuições (rentabilidade simples dos ativos)", "Subtotal", soma_ativos * pl_i, soma_ativos),
              ("Diferença de ponderação (o PL variou no período por resgates/aplicações; R$ = bps × PL inicial, não é caixa)", "Ponderação",
               (enc - soma_ativos) * pl_i, enc - soma_ativos),
              ("Rentabilidade dos ativos encadeada dia a dia", "Subtotal", enc * pl_i, enc)]
    # 'Rendimento s/ <ativo>' no extrato e o provento que ja esta no rendimento do ativo: nao conta de novo
    itens = [(f"Extrato {externo['data']:%d/%m} {externo['descricao']}", "Caixa / despesas", externo["valor"])
             for externo in (analise.get("externos_extrato") or []) if not re.match(r"Rendimento s/", externo["descricao"], re.I)]
    ponte = analise.get("ponte")
    if not ponte:
        lp = analise["ativos"][analise["ativos"]["Ativo"] == "Provisão"]
        dprov = float((lp["PL Final"] - lp["PL Inicial"]).sum())
        if abs(dprov) > 0.005:
            itens.append(("Variação das provisões (taxas provisionadas e pagas)", "Provisões", dprov))
    if ponte:
        itens += [(f"Provisão {provisao['nome']}", "Provisões", provisao["delta"]) for provisao in ponte["provisoes"] if abs(provisao["delta"]) > 0.005]
        dif_rendas = -(ponte["rendas"] - ponte["cupom_caixa"])
        if abs(dif_rendas) > 0.005:
            itens.append(("Rendas da planilha − cupom recebido em caixa", "Caixa / despesas", dif_rendas))
    extra = [(descricao, cl, valor, valor / pl_i if pl_i else 0.0) for descricao, cl, valor in itens]
    linhas += extra
    fecha = cota - enc - sum(degrau[3] for degrau in extra)
    linhas.append(("Outros até a cota (tributos, taxas não listadas no extrato, defasagem de datas)", "Outros", fecha * pl_i, fecha))
    linhas.append(("Rentabilidade da cota", "Total", cota * pl_i, cota))
    return linhas


def _abaContribuicoes(planilha_aba, analises):
    """Ranking de contribuicao de cada ativo, por carteira (maior alta primeiro, maior baixa por ultimo)."""
    cols = ["Carteira", "Posição", "Ativo", "Classe", "Estratégia", "PL Inicial", "Rendimento", "% Rent do ativo",
            "Contribuição (bps)", "Contribuição (%)"]
    _cabecalho(planilha_aba, cols)
    ordem_item = 2
    for id_cliente, analise in analises.items():
        for pos, (_, operacao) in enumerate(analise["contribuicoes"].iterrows(), 1):
            vals = [id_cliente, pos, operacao["Ativo"], operacao["Classe"], operacao["Estratégia"], float(operacao["PL Inicial"]), float(operacao["Rendimento"]),
                    float(operacao["% Rent"]), float(operacao["Contribuição"]) * 10000, float(operacao["Contribuição"])]
            fmts = [None, "0", None, None, None, FMT_VALOR, FMT_VALOR, "0.0000%;[Red]-0.0000%", "0.00;[Red]-0.00",
                    "0.0000%;[Red]-0.0000%"]
            for ordem_aux, (valor, formato) in enumerate(zip(vals, fmts), 1):
                celula = planilha_aba.cell(ordem_item, ordem_aux, valor)
                celula.border = _borda
                celula.font = Font(name=FONTE, size=10)
                if formato:
                    celula.number_format = formato
            ordem_item += 1
        # Secao so da planilha: do somatorio dos ativos ate a cota, em degraus
        linhas = degrausContribuicao(analise)
        for descricao, cl, valor, ctb in linhas:
            vals = [id_cliente, "—", descricao, cl, "Caixa, despesas e outros", None, valor, None, ctb * 10000, ctb]
            fmts = [None, None, None, None, None, FMT_VALOR, FMT_VALOR, None, "0.00;[Red]-0.00", "0.0000%;[Red]-0.0000%"]
            for ordem_aux, (val, formato) in enumerate(zip(vals, fmts), 1):
                celula = planilha_aba.cell(ordem_item, ordem_aux, val)
                celula.border = _borda
                celula.font = Font(name=FONTE, size=10, bold=(cl in ("Total", "Subtotal")), italic=(cl not in ("Total", "Subtotal")))
                if formato:
                    celula.number_format = formato
            ordem_item += 1
    _nota(planilha_aba, f"A{ordem_item + 1}", "Contribuição = Rendimento do ativo ÷ PL Inicial total da carteira, em bps (1 bps = 0,01%). A soma das "
                           "contribuições de uma carteira é a rentabilidade simples dos ativos (Rendimento total ÷ PL Inicial total). "
                           "As linhas em itálico 'Caixa, despesas e outros' (só nesta planilha) mostram o que leva da soma dos ativos até a "
                           "rentabilidade da cota; a última linha de cada carteira é a cota.")
    for ordem_aux, largura in enumerate([12, 9, 48, 22, 44, 18, 18, 16, 20, 18], 1):
        planilha_aba.column_dimensions[get_column_letter(ordem_aux)].width = largura
    planilha_aba.freeze_panes = "A2"
    planilha_aba.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{max(ordem_item - 1, 2)}"


def _blocoPonteCotistas(planilha_aba, ponte, cel, linha):
    """Ponte com movimentacao de cotas: PL Inicial + Rendimento + cotistas + outros efeitos = PL Final."""
    planilha_aba.cell(linha, 1, "Ponte: PL Inicial → PL Final (com movimentação de cotistas)").font = Font(name=FONTE, size=12, bold=True, color="8F2A22")
    linha += 1
    for col, nome in zip("ABC", ["Item", "R$", "Fonte"]):
        celula = cel(f"{col}{linha}", nome, negrito=True, cor="FFFFFF")
        celula.fill = PatternFill("solid", fgColor=COR_CAB)
        celula.alignment = Alignment(horizontal="center")
    linha += 1

    def item(texto, valor, fonte="", negrito=False):
        nonlocal linha
        cel(f"A{linha}", texto, negrito=negrito)
        cel(f"B{linha}", valor, FMT_VALOR, negrito=negrito)
        cel(f"C{linha}", fonte)
        linha += 1
        return linha - 1

    r_pl = item("PL Inicial", ponte["pl_inicial"], "Planilha (ValorFinal do dia-base)", True)
    r_rend = item("(+) Rendimento dos ativos", ponte["rendimento"], "Planilha (RendimentoLiquida)")
    item("Movimentação de cotistas (valor bruto)", None, "API OperacaoCotistaAnalitico_PorCarteiraPeriodo", True)
    linha_inicio = linha
    for _, operacao in ponte["operacoes"].iterrows():
        item(f"   {operacao['Data']:%d/%m} {operacao['Tipo']}", float(operacao["Valor bruto"]) * (1 if operacao["Sinal"] >= 0 else -1), "Operação de cotista")
    r_mov = item("   Subtotal cotistas", f"=SUM(B{linha_inicio}:B{linha - 1})" if len(ponte["operacoes"]) else 0, "", True)
    r_fim = item("PL Final (planilha)", ponte["pl_final"], "Planilha (ValorFinal do último dia)", True)
    item("Outros efeitos (tributos, taxas, provisões e defasagem de datas)",
         f"=B{r_fim}-(B{r_pl}+B{r_rend}+B{r_mov})", "O que sobra depois de rendimento e cotistas", True)


def _abaConferenciaMulti(planilha_aba, analise):
    """Aba <id>_Conf: conferencia da rentabilidade + ponte (extrato/provisoes ou cotistas)."""
    ponte, ponte_cot = analise["ponte"], analise["ponte_cotistas"]
    _abaConferencia(planilha_aba, analise["ativos"].attrs["conferencia"], ponte)
    if ponte_cot:
        def cel(ref, valor, fmt=None, negrito=False, cor="000000"):
            celula = planilha_aba[ref]
            celula.value = valor
            celula.font = Font(name=FONTE, size=10, bold=negrito, color=cor)
            celula.border = _borda
            if fmt:
                celula.number_format = fmt
            return celula
        _blocoPonteCotistas(planilha_aba, ponte_cot, cel, 15)


def salvarExcelMulti(analises, caminho):
    """Excel com: Divergencias (resumo + passo a passo), OpCotistas, uma aba por carteira, <id>_Conf e Info."""
    pasta_trabalho = Workbook()
    pasta_trabalho.remove(pasta_trabalho.active)
    _abaDivergencias(pasta_trabalho.create_sheet("Divergencias"), analises)
    _abaOpCotistas(pasta_trabalho.create_sheet("OpCotistas"), analises)
    _abaContribuicoes(pasta_trabalho.create_sheet("Contribuicoes"), analises)
    for id_cliente, analise in analises.items():
        _escrever(pasta_trabalho.create_sheet(str(id_cliente)[:31]), analise["layout"], com_niveis=True)
        if analise["ponte"] or analise["ponte_cotistas"]:
            _abaConferenciaMulti(pasta_trabalho.create_sheet(f"{id_cliente}_Conf"[:31]), analise)

    wi = pasta_trabalho.create_sheet("Info")
    primeiro = next(iter(analises.values()))["ativos"]
    linhas = [
        ("Tratamento da aba Ativo (Relatorio_Rentabilidade.xlsx), uma aba por carteira", True),
        (f"Periodo: {primeiro.attrs['inicio']:%d/%m/%Y} a {primeiro.attrs['fim']:%d/%m/%Y}", False),
        (f"Gerado em {datetime.now():%d/%m/%Y %H:%M}", False),
        ("", False),
        ("Como ler a aba Divergencias", True),
        ("PL Final pela cota = PL Inicial × (1 + cota): o PL se a carteira só tivesse rentabilidade.", False),
        ("Dif. PL Final = PL Final real − PL Final pela cota. Perto de zero: a cota explica o PL.", False),
        ("Se houve aplicação ou resgate de cotas, o PL muda por fora da rentabilidade. Efeito = Σ(sinal × cotas) × cota do último dia.", False),
        ("Resíduo = PL Final real − (PL Final pela cota + Efeito). Perto de zero: a divergência é explicada pelos cotistas.", False),
        (f"Status: {STATUS_OK} (|Dif.| ≤ R$ {TOLERANCIA_REAIS:.2f}); {STATUS_EXPLICADA} (há operações e |Resíduo| ≤ "
         f"{TOLERANCIA_EXPLICADA_PCT * 100:.2f}% do PL Inicial); {STATUS_DIVERGENTE} (demais casos).", False),
        ("", False),
        ("Fontes (API Britech)", True),
        ("Ativos, rentabilidade e cota: BuscaRentabAtivo_Dia e BuscaRentabEstrategia_PeriodoNaoExplodida.", False),
        ("Cotas e PL por dia: Fundo/BuscaHistoricoCotaDia. Aplicações e resgates: Fundo/OperacaoCotistaAnalitico_PorCarteiraPeriodo.", False),
        ("Extrato de conta corrente: Relatorio/RelatorioExtratoContaCorrente (usado na ponte das carteiras sem movimentação de cotas).", False),
        ("", False),
        ("Avisos por carteira", True),
    ]
    for id_cliente, analise in analises.items():
        linhas += [(f"{id_cliente}: {aviso}", False) for aviso in analise["avisos"]]
        if not analise["avisos"]:
            linhas.append((f"{id_cliente}: sem avisos", False))
    for ordem_item, (texto, negrito) in enumerate(linhas, 1):
        celula = wi.cell(ordem_item, 1, texto)
        celula.font = Font(name=FONTE, size=11 if negrito else 10, bold=negrito, color="8F2A22" if negrito else "000000")
    wi.column_dimensions["A"].width = 130
    pasta_trabalho.save(caminho)


# ----------------------------------------------------------------------------
# Linha de comando
# ----------------------------------------------------------------------------
def lerRentabilidadeCarteira(entrada, id_cliente=None):
    """Rentabilidade da carteira no periodo (em %), da coluna RentabilidadeCotaBruta da aba Estrategia."""
    try:
        tb_estrategia = pd.read_excel(entrada, sheet_name="Estrategia")
    except ValueError:
        return None
    if "RentabilidadeCotaBruta" not in tb_estrategia.columns:
        return None
    if id_cliente is not None and COL_ID in tb_estrategia.columns:
        tb_estrategia = tb_estrategia[tb_estrategia[COL_ID].astype(str) == str(id_cliente)]
    valores = pd.to_numeric(tb_estrategia["RentabilidadeCotaBruta"], errors="coerce").dropna().unique()
    return float(valores[0]) if len(valores) else None


def _acharEntrada(arg):
    if arg:
        return Path(arg)
    for pasta in (Path.cwd(), Path(__file__).resolve().parents[3] / "dados" / "britech"):
        if (pasta / ARQUIVO_PADRAO).exists():
            return pasta / ARQUIVO_PADRAO
    raise FileNotFoundError(f"Nao achei {ARQUIVO_PADRAO}. Passe o caminho do arquivo como argumento.")


def main(argv=None):
    analisador = argparse.ArgumentParser(description="Trata a planilha de rentabilidade para ficar igual ao PDF da BRITech.")
    analisador.add_argument("entrada", nargs="?", help=f"planilha de entrada (padrao: {ARQUIVO_PADRAO})")
    analisador.add_argument("-o", "--saida", help=f"arquivo de saida (padrao: {SAIDA_PADRAO} ao lado da entrada)")
    analisador.add_argument("--inicio", help="data-base, AAAA-MM-DD (padrao: primeira data da planilha)")
    analisador.add_argument("--fim", help="data final, AAAA-MM-DD (padrao: ultima data da planilha)")
    analisador.add_argument("--extratos", help=f"pasta com ReportExtratoContaCorrente_<id>.xlsx (padrao: {EXTRATOS_PADRAO.name}/ ao lado do script)")
    analisador.add_argument("--extrato", help=f"extrato de conta corrente em xlsx (padrao: {EXTRATO_PADRAO.name} ao lado do script)")
    args = analisador.parse_args(argv)

    try:
        entrada = _acharEntrada(args.entrada)
        df = pd.read_excel(entrada, sheet_name=ABA_ATIVO)
    except FileNotFoundError as erro:
        print(erro)
        return 1
    except ValueError as erro:
        print(f"Nao consegui ler a aba '{ABA_ATIVO}' de {args.entrada or ARQUIVO_PADRAO}: {erro}")
        return 1

    if COL_ID in df.columns:
        analises, erros = analisarTodas(entrada, args.inicio, args.fim, args.extratos)
        for id_cliente, texto_mensagem in erros.items():
            print(f"Carteira {id_cliente}: {texto_mensagem}")
        if not analises:
            print("Nenhuma carteira pôde ser tratada.")
            return 1
        saida = Path(args.saida) if args.saida else entrada.with_name(SAIDA_PADRAO)
        salvarExcelMulti(analises, saida)
        for id_cliente, analise in analises.items():
            resumo = analise["resumo"]
            geral = analise["layout"][analise["layout"]["Nível"] == "Total Geral"].iloc[0]
            print(f"{id_cliente} ({analise['nome']}): {len(analise['ativos'])} ativos | PL Final {fmtBrl(geral['PL Final'])} "
                  f"| % Rent {geral['% Rent'] * 100:.4f}% | [{analise['status']}]")
            print(f"  dif cota x ativos {fmtBrl(resumo['diferenca_reais'])} | dif PL Final {fmtBrl(resumo['dif_pl'])}"
                  + (f" | efeito cotistas {fmtBrl(resumo['efeito_cotas'])} | resíduo {fmtBrl(resumo['residuo_cotistas'])}"
                     if resumo["residuo_cotistas"] is not None else ""))
            if analise["ponte"]:
                print(f"  ponte: explicado {fmtBrl(analise['ponte']['explicado'])} | resíduo {fmtBrl(analise['ponte']['residuo'])}")
            for aviso in analise["avisos"]:
                print("  ATENCAO:", aviso)
        print(f"Arquivo gerado: {saida}")
        return 0

    try:
        ativos, disposicao, avisos = tratar(df, args.inicio, args.fim, lerRentabilidadeCarteira(entrada))
    except ValueError as erro:
        print(f"Erro: {erro}")
        return 1

    ponte = None
    caminho_extrato = Path(args.extrato) if args.extrato else EXTRATO_PADRAO
    if caminho_extrato.exists():
        try:
            ponte = montarPonte(df, ativos, lerExtrato(caminho_extrato))
        except ValueError as erro:
            avisos.append(f"Ponte da diferenca nao gerada: {erro}")
        else:
            if abs(ponte["residuo"]) > 0.05:
                avisos.append(f"Ponte da diferenca: residuo de {ponte['residuo']:,.2f}. Falta algum lancamento (extrato ou provisao).")
    else:
        avisos.append(f"Ponte da diferenca nao gerada: nao achei o extrato {caminho_extrato}.")

    saida = Path(args.saida) if args.saida else entrada.with_name(SAIDA_PADRAO)
    salvarExcel(ativos, disposicao, avisos, saida, ponte)

    geral = disposicao[disposicao["Nível"] == "Total Geral"].iloc[0]
    print(f"Periodo: {ativos.attrs['inicio']:%d/%m/%Y} a {ativos.attrs['fim']:%d/%m/%Y} | {len(ativos)} ativos")
    print(f"Total Geral  PL Inicial {geral['PL Inicial']:,.2f} | PL Final {geral['PL Final']:,.2f} | Rendimento {geral['Rendimento']:,.2f} | % Rent {geral['% Rent'] * 100:.4f}%")
    print("\nConferencia da rentabilidade:")
    for aviso in textosConferencia(ativos.attrs["conferencia"]):
        print("  " + aviso)
    if ponte:
        print()
        for aviso in textosPonte(ponte):
            print(aviso)
    for analise in avisos:
        print("ATENCAO:", analise)
    print(f"Arquivo gerado: {saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
