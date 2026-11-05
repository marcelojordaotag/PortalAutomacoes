"""Limite de envio ao Slack (sem Streamlit): espaça as mensagens e respeita o 429 (Retry-After) em todos os apps."""
import threading
import time

import requests

INTERVALO_MINIMO = 1.5  # segundos entre duas mensagens, somando todos os apps do mesmo processo
TENTATIVAS_429 = 3
ESPERA_MAXIMA = 60

_trava = threading.Lock()
_ultimo_envio = 0.0


def postarComLimite(url, **argumentos):
    """requests.post com intervalo mínimo entre envios; se o Slack devolver 429, espera o Retry-After e tenta de novo."""
    global _ultimo_envio
    for tentativa in range(TENTATIVAS_429):
        with _trava:  # mantém a fila: quem chega depois espera a vez
            time.sleep(max(0.0, _ultimo_envio + INTERVALO_MINIMO - time.monotonic()))
            resposta = requests.post(url, **argumentos)
            _ultimo_envio = time.monotonic()
        if resposta.status_code != 429:
            return resposta
        espera = min(ESPERA_MAXIMA, float(resposta.headers.get("Retry-After", INTERVALO_MINIMO * 2)))
        if tentativa < TENTATIVAS_429 - 1:
            time.sleep(espera)
    return resposta


JANELA_REPETIDO = 120  # segundos em que o mesmo conteúdo não é enviado duas vezes
_enviados = {}


def segundosParaRepetir(conteudo):
    """0 se este conteúdo pode ser enviado agora (e já o marca como enviado); senão, quantos segundos faltam para poder repetir."""
    agora = time.monotonic()
    with _trava:
        for chave in [c for c, t in _enviados.items() if agora - t >= JANELA_REPETIDO]:
            del _enviados[chave]
        recente = _enviados.get(conteudo)
        if recente is not None:
            return int(JANELA_REPETIDO - (agora - recente)) + 1
        _enviados[conteudo] = agora
        return 0


def liberarConteudo(conteudo):
    """Desfaz a marca quando o envio falhou, para a pessoa poder tentar de novo na hora."""
    with _trava:
        _enviados.pop(conteudo, None)
