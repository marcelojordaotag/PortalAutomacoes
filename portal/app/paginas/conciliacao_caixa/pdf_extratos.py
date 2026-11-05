"""Leitura de extratos de conta investimento em PDF (XP e BTG Pactual) para Excel.

Os dois PDFs têm texto de verdade, mas sem tabela desenhada: a leitura é feita por linha de texto.
  - XP: "Movimentação  Liquidação  Histórico  Valor  Saldo". O histórico às vezes quebra em duas linhas (a primeira
    fica sem data, em cima da linha com data) e a ordem é da mais nova para a mais antiga.
  - BTG: "Data  Descrição  Débito  Crédito  Saldo". O texto só traz um valor por linha, então débito ou crédito
    é decidido pela variação do saldo; ordem da mais antiga para a mais nova.
Cada leitor devolve as linhas, um resumo e as conferências feitas (saldos que fecham), para dar para confiar no resultado.
"""
import io
import logging
import re
from datetime import datetime

import pandas as pd

logging.getLogger("pdfminer").setLevel(logging.ERROR)
logging.getLogger("pdfplumber").setLevel(logging.ERROR)

NOMES = {"xp": "XP Investimentos", "btg": "BTG Pactual"}


def br(txt):
    """'R$ 1.019,58' -> 1019.58; '-R$ 30.000,00' -> -30000.0; '-59.276,91' -> -59276.91."""
    texto_limpo = txt.replace("R$", "").replace(" ", "").strip()
    negativo = texto_limpo.startswith("-")
    valor = float(texto_limpo.lstrip("-").replace(".", "").replace(",", "."))
    return -valor if negativo else valor


def dia(txt):
    return datetime.strptime(txt, "%d/%m/%Y").date()


def textosPaginas(dados):
    import pdfplumber

    with pdfplumber.open(io.BytesIO(dados)) as pdf:
        return [pg.extract_text() or "" for pg in pdf.pages]


def detectar(textos):
    texto_total = "\n".join(textos)
    if re.search(r"Movimentação\s+Liquidação\s+Histórico\s+Valor\s+Saldo", texto_total):
        return "xp"
    if re.search(r"Data\s+Descrição\s+Débito\s+Crédito\s+Saldo", texto_total):
        return "btg"
    return None


# ---------------------------------------------------------------- XP
LINHA_XP = re.compile(r"^(\d{2}/\d{2}/\d{4}) (\d{2}/\d{2}/\d{4}) (.*?) (-?R\$ [\d.]+,\d{2}) (-?R\$ [\d.]+,\d{2})$")


def lerXp(textos):
    linhas, pendentes = [], []
    for pagina in textos:
        no_bloco = False
        for linha_pagina in pagina.splitlines():
            linha_pagina = linha_pagina.strip()
            if linha_pagina.startswith("Movimentação Liquidação"):
                no_bloco = True
                continue
            if linha_pagina.startswith("XP INVESTIMENTOS CORRETORA") or linha_pagina.startswith("Estas informações são confidenciais"):
                no_bloco = False
            if not no_bloco or not linha_pagina:
                continue
            casamento = LINHA_XP.match(linha_pagina)
            if casamento:
                mov, liq, hist, valor, saldo = casamento.groups()
                # a 1ª parte do histórico fica numa linha sem data, logo acima (pode estar na página anterior)
                linhas.append({"Movimentação": dia(mov), "Liquidação": dia(liq),
                               "Histórico": " ".join(pendentes + [hist]).strip(), "Valor": br(valor), "Saldo": br(saldo)})
                pendentes = []
            else:
                pendentes.append(linha_pagina)

    texto = "\n".join(textos)
    resumo = {}
    if casamento := re.search(r"Data do extrato:\s*(\d{2}/\d{4})\s+(\d+)", texto):
        resumo["Mês do extrato"], resumo["Conta"] = casamento.group(1), casamento.group(2)
    if casamento := re.search(r"Saldo atual\((\d{2}/\d{2}/\d{4})\)\s*(-?R\$ [\d.]+,\d{2})", texto):
        resumo["Data do saldo atual"], resumo["Saldo atual"] = casamento.group(1), br(casamento.group(2))
    if casamento := re.search(r"Saldo anterior\((\d{2}/\d{2}/\d{4})\)\s*(-?R\$ [\d.]+,\d{2})", texto):
        resumo["Data do saldo anterior"], resumo["Saldo anterior"] = casamento.group(1), br(casamento.group(2))

    df = pd.DataFrame(linhas, columns=["Movimentação", "Liquidação", "Histórico", "Valor", "Saldo"])
    conferencias = []
    if len(df) > 1:
        # mais nova primeiro: o saldo da linha de baixo = saldo da linha de cima - valor da linha de cima
        ok = sum(abs(df["Saldo"].iloc[ordem_item + 1] - (df["Saldo"].iloc[ordem_item] - df["Valor"].iloc[ordem_item])) <= 0.01 for ordem_item in range(len(df) - 1))
        conferencias.append((f"Saldos encadeados ({ok} de {len(df) - 1} linhas)", ok == len(df) - 1))
    if len(df) and "Saldo atual" in resumo:
        conferencias.append(("Saldo da 1ª linha = saldo atual", abs(df["Saldo"].iloc[0] - resumo["Saldo atual"]) <= 0.01))
    if len(df) and "Saldo anterior" in resumo:
        antes = df["Saldo"].iloc[-1] - df["Valor"].iloc[-1]
        conferencias.append(("Saldo antes da última linha = saldo anterior", abs(antes - resumo["Saldo anterior"]) <= 0.01))
    return {"formato": "xp", "movimentos": df, "resumo": resumo, "conferencias": conferencias}


# ---------------------------------------------------------------- BTG
LINHA_BTG = re.compile(r"^(\d{2}/\d{2}/\d{4}) (.*?) ?(-?[\d.]+,\d{2}) (-?[\d.]+,\d{2})$")
SALDO_INICIAL = re.compile(r"^(\d{2}/\d{2}/\d{4}) Saldo Inicial (-?[\d.]+,\d{2})$")
SALDO_FINAL = re.compile(r"^(\d{2}/\d{2}/\d{4}) Saldo Final (-?[\d.]+,\d{2})$")
RODAPE = re.compile(r"^\d+ de \d+$")


def lerBtg(textos):
    texto = "\n".join(textos)
    brutas, saldo_inicial, saldo_final, tot_cred, tot_deb = [], None, None, None, None
    no_bloco = False  # o cabeçalho só aparece na 1ª página da tabela: o bloco continua nas páginas seguintes
    for pagina in textos:
        for linha_pagina in pagina.splitlines():
            linha_pagina = linha_pagina.strip()
            if re.match(r"^Data\s+Descrição\s+Débito\s+Crédito\s+Saldo$", linha_pagina):
                no_bloco = True
                continue
            if not no_bloco or not linha_pagina or RODAPE.match(linha_pagina) or linha_pagina.startswith("Movimentação - Conta"):
                continue
            if casamento := SALDO_INICIAL.match(linha_pagina):
                saldo_inicial = br(casamento.group(2))
            elif casamento := SALDO_FINAL.match(linha_pagina):
                saldo_final = br(casamento.group(2))
            elif casamento := re.match(r"^Total de Créditos (-?[\d.]+,\d{2})$", linha_pagina):
                tot_cred = br(casamento.group(1))
            elif casamento := re.match(r"^Total de Débitos (-?[\d.]+,\d{2})$", linha_pagina):
                tot_deb = br(casamento.group(1))
            elif casamento := LINHA_BTG.match(linha_pagina):
                brutas.append([casamento.group(1), casamento.group(2).strip(), br(casamento.group(3)), br(casamento.group(4))])
            elif brutas:  # descrição que quebrou em outra linha
                brutas[-1][1] += " " + linha_pagina

    linhas, anterior = [], saldo_inicial
    for data_, desc, valor, saldo in brutas:
        variacao = round(saldo - anterior, 2) if anterior is not None else None
        confere = variacao is not None and abs(abs(variacao) - abs(valor)) <= 0.01
        debito = abs(valor) if (variacao or 0) < 0 else None
        credito = abs(valor) if (variacao or 0) >= 0 else None
        linhas.append({"Data": dia(data_), "Descrição": desc, "Débito": debito, "Crédito": credito, "Saldo": saldo,
                       "Alerta": "" if confere else "conferir"})
        anterior = saldo
    df = pd.DataFrame(linhas, columns=["Data", "Descrição", "Débito", "Crédito", "Saldo", "Alerta"])

    resumo = {}
    for campo, rx in (("Banco", r"Banco:\s*(.+)"), ("Agência", r"Agência:\s*(\S+)"),
                      ("Conta investimento", r"Conta Investimento:\s*(\S+)")):
        if casamento := re.search(rx, texto):
            resumo[campo] = casamento.group(1).strip()
    if casamento := re.search(r"Período de (\d{2}/\d{2}/\d{4}) a (\d{2}/\d{2}/\d{4})", texto):
        resumo["Período"] = f"{casamento.group(1)} a {casamento.group(2)}"
    for campo, valor_campo in (("Saldo inicial", saldo_inicial), ("Saldo final", saldo_final),
                     ("Total de créditos", tot_cred), ("Total de débitos", tot_deb)):
        if valor_campo is not None:
            resumo[campo] = valor_campo

    conferencias = []
    if len(df):
        conferencias.append((f"Débito/crédito batem com a variação do saldo ({int((df['Alerta'] == '').sum())} de {len(df)} linhas)",
                             bool((df["Alerta"] == "").all())))
        if saldo_final is not None:
            conferencias.append(("Último saldo = saldo final", abs(df["Saldo"].iloc[-1] - saldo_final) <= 0.01))
        if tot_cred is not None:
            conferencias.append(("Soma dos créditos = total de créditos", abs(df["Crédito"].sum() - tot_cred) <= 0.01))
        if tot_deb is not None:
            conferencias.append(("Soma dos débitos = total de débitos", abs(df["Débito"].sum() - tot_deb) <= 0.01))
    return {"formato": "btg", "movimentos": df, "resumo": resumo, "conferencias": conferencias}


LEITORES = {"xp": lerXp, "btg": lerBtg}


def excelExtrato(resultado_calculo):
    """Excel com a aba Movimentação (datas e números de verdade) e a aba Resumo (dados do extrato e conferências)."""
    resumo = pd.DataFrame([{"Campo": chave_item, "Valor": valor_resumo} for chave_item, valor_resumo in resultado_calculo["resumo"].items()]
                          + [{"Campo": "Conferência: " + nome, "Valor": "ok" if ok else "NÃO CONFERE"}
                             for nome, ok in resultado_calculo["conferencias"]])
    saida = io.BytesIO()
    with pd.ExcelWriter(saida, engine="openpyxl", date_format="DD/MM/YYYY") as escritor_planilha:
        resultado_calculo["movimentos"].to_excel(escritor_planilha, sheet_name="Movimentação", index=False)
        resumo.to_excel(escritor_planilha, sheet_name="Resumo", index=False)
        for planilha_aba in escritor_planilha.book.worksheets:
            for col in planilha_aba.columns:
                largura = max(len(str(celula.value)) if celula.value is not None else 0 for celula in col)
                planilha_aba.column_dimensions[col[0].column_letter].width = min(max(12, largura + 2), 70)
            for linha in planilha_aba.iter_rows(min_row=2):
                for celula in linha:
                    if isinstance(celula.value, float):
                        celula.number_format = "#,##0.00"
    return saida.getvalue()
