"""Apoio comum às telas de "Importar cadastro" (leitura de planilha e limpeza de texto), usado por mais de uma ferramenta."""
import io
import re
import unicodedata

import pandas as pd


class ErroImportacao(Exception):
    """Planilha que não dá para ler (formato, aba ou colunas)."""


def normalizar(tx_texto):
    """Sem acentos, sem espaços a mais e em minúsculas: para comparar nomes."""
    tx_texto = unicodedata.normalize("NFKD", str(tx_texto))
    tx_texto = "".join(caractere for caractere in tx_texto if not unicodedata.combining(caractere))
    return re.sub(r"\s+", " ", tx_texto).strip().casefold()


def limpar(valor):
    """Texto sem espaços sobrando; vazio (ou NaN) vira ''. Número vindo do Excel como '123.0' vira '123'."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    tx_valor = re.sub(r"\s+", " ", str(valor)).strip()
    if tx_valor.lower() == "nan":
        return ""
    return tx_valor[:-2] if re.fullmatch(r"\d+\.0", tx_valor) else tx_valor


def lerPlanilhaBruta(arquivo, nm_aba_preferida="dados"):
    """Lê o arquivo enviado (.xlsx, .xls ou .csv) como DataFrame de texto. Em Excel, usa a aba com o nome preferido ou a primeira."""
    nm_arquivo = arquivo.name.lower()
    try:
        if nm_arquivo.endswith(".csv"):
            bytes_arquivo = arquivo.getvalue()
            for nm_codificacao in ("utf-8-sig", "latin-1"):
                try:
                    return pd.read_csv(io.BytesIO(bytes_arquivo), sep=None, engine="python", dtype=str, encoding=nm_codificacao)
                except UnicodeDecodeError:
                    continue
            raise ErroImportacao("Não consegui ler o CSV (codificação desconhecida). Salve como UTF-8 ou envie em .xlsx.")
        arquivo_excel = pd.ExcelFile(arquivo)
        lista_abas = arquivo_excel.sheet_names
        nm_aba = next((aba for aba in lista_abas if normalizar(aba) == nm_aba_preferida), lista_abas[0])
        return pd.read_excel(arquivo_excel, sheet_name=nm_aba, dtype=str)
    except ErroImportacao:
        raise
    except Exception as erro:  # noqa: BLE001  (arquivo corrompido, senha, formato errado...)
        raise ErroImportacao(f"Não consegui abrir a planilha: {erro}") from erro
