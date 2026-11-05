"""Versão de cada ferramenta do portal. Cada app evolui sozinho: ao alterar um app, atualize só a linha dele.

Formato: MAIOR.MENOR.CORRECAO (ex.: 1.2.0) e a data da alteração (AAAA-MM-DD).
"""

VERSOES = {
    "portal":        {"versao": "2.2.6", "data": "2026-11-04"},  # home.py, tema.py, iniciar.py
    "extratos":      {"versao": "1.0.2", "data": "2026-11-03"},
    "boletas":       {"versao": "1.1.0", "data": "2026-11-05"},
    "rentabilidade": {"versao": "1.0.0", "data": "2026-10-22"},
    "caixa":         {"versao": "2.8.4", "data": "2026-11-03"},
    "solicitacoes":  {"versao": "2.0.5", "data": "2026-11-03"},
    "processos_externos": {"versao": "1.2.7", "data": "2026-11-03"},
    "crava_cotas":   {"versao": "0.7.3", "data": "2026-11-03"},
    "bradesco":      {"versao": "1.0.1", "data": "2026-10-27"},
}


def rotulo(chave):
    """Texto curto para exibir na tela, ex.: 'v1.0.0 · 22/10/2026'."""
    dict_versao = VERSOES.get(chave)
    if not dict_versao:
        return ""
    ano, mes, dia = dict_versao["data"].split("-")
    return f"v{dict_versao['versao']} · {dia}/{mes}/{ano}"
