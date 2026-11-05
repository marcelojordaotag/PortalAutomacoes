"""Importa o 'Registro Solicitações.xlsm' (aba Solicitacoes + aba Lista) para os JSONs do app.

Uso:
    python -m app.paginas.solicitacoes.importar_planilha "C:/caminho/Registro Solicitações.xlsm"   (na pasta do portal)

Gera solicitacoes.json e clientes.json em dados/solicitacoes. Se solicitacoes.json já existir, não sobrescreve
(use --forcar para substituir).
"""
import json
import sys
from datetime import datetime

import openpyxl

from app.ambiente.config_ambiente import obterDiretorioDados

PASTA = obterDiretorioDados("solicitacoes")
ARQ_SOLICITACOES = PASTA / "solicitacoes.json"
ARQ_CLIENTES = PASTA / "clientes.json"


def _data(valor_data):
    return valor_data.strftime("%Y-%m-%d") if isinstance(valor_data, datetime) else None


def importar(caminho, forcar=False):
    pasta_trabalho = openpyxl.load_workbook(caminho, read_only=True, data_only=True)

    clientes = [str(linha_lista[0]).strip() for linha_lista in pasta_trabalho["Lista"].iter_rows(min_row=2, values_only=True) if linha_lista[0]]
    ARQ_CLIENTES.write_text(json.dumps(clientes, ensure_ascii=False, indent=1), encoding="utf-8")

    if ARQ_SOLICITACOES.exists() and not forcar:
        raise FileExistsError(f"{ARQ_SOLICITACOES.name} já existe; use --forcar para substituir.")

    registros = []
    for linha in pasta_trabalho["Solicitacoes"].iter_rows(min_row=2, values_only=True):
        cliente, solicitante, data, tipo, descricao, status, data_status = linha[2], linha[3], linha[4], linha[5], linha[6], linha[7], linha[8]
        if not cliente:
            continue
        status = (status or "Em aberto").strip()
        registros.append({
            "id": len(registros) + 1,
            "cliente": str(cliente).strip(),
            "solicitante": (solicitante or "").strip(),
            "data": _data(data),
            "tipo": (tipo or "Ajuste Fechamento").strip(),
            "descricao": (descricao or "").strip(),
            "status": status,
            "data_conclusao": _data(data_status) if status == "Concluído" else None,
            "evidencia": "",
            "historico": [{"quando": datetime.now().strftime("%Y-%m-%d %H:%M"), "evento": "Importado da planilha",
                           "detalhe": f"Status na planilha: {status}"}],
        })
    ARQ_SOLICITACOES.write_text(json.dumps(registros, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(registros), len(clientes)


if __name__ == "__main__":
    args = [argumento for argumento in sys.argv[1:] if not argumento.startswith("--")]
    if not args:
        sys.exit(__doc__)
    qt_solicitacoes, qt_clientes = importar(args[0], forcar="--forcar" in sys.argv)
    print(f"{qt_solicitacoes} solicitações e {qt_clientes} clientes importados.")
