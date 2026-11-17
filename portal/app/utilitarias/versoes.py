"""Versão de cada ferramenta do portal. Cada app evolui sozinho: ao alterar um app, atualize só a linha dele.

Formato: MAIOR.MENOR.CORRECAO (ex.: 1.2.0) e a data da alteração (AAAA-MM-DD).
"""

VERSOES = {
    "portal":        {"versao": "2.11.0", "data": "2026-11-17"},  # home.py, tema.py, iniciar.py
    "extratos":      {"versao": "1.9.1", "data": "2026-11-17"},
    "boletas":       {"versao": "1.1.2", "data": "2026-11-17"},
    "rentabilidade": {"versao": "1.1.1", "data": "2026-11-17"},
    "caixa":         {"versao": "3.0.1", "data": "2026-11-17"},
    "solicitacoes":  {"versao": "2.2.2", "data": "2026-11-17"},
    "processos_externos": {"versao": "1.3.3", "data": "2026-11-17"},
    "crava_cotas":   {"versao": "0.9.1", "data": "2026-11-17"},
    "bradesco":      {"versao": "1.2.1", "data": "2026-11-12"},
}


def rotulo(chave):
    """Texto curto para exibir na tela, ex.: 'v1.0.0 · 22/10/2026'."""
    dict_versao = VERSOES.get(chave)
    if not dict_versao:
        return ""
    ano, mes, dia = dict_versao["data"].split("-")
    return f"v{dict_versao['versao']} · {dia}/{mes}/{ano}"
