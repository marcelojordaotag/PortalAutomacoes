"""CRAVA COTAS: aviso automático das posições pendentes no Slack, sem ninguém na tela.

Uso (agendado no Agendador de Tarefas do Windows):  python aviso_automatico.py D-2   (17h)
                                                    python aviso_automatico.py D-3   (10h)

Abre o backoffice com o login salvo no perfil, lê o dia pedido e posta no Slack só se houver posições
indisponíveis. Se a leitura falhar (login expirado, tela mudou), posta um alerta curto para o silêncio
não ser confundido com "sem pendências". Registra tudo em dados/crava_cotas/aviso_automatico.log.
"""
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

RAIZ_PORTAL = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ_PORTAL))  # para importar app.* quando rodado fora do portal
os.environ.setdefault("APP_ENV", "local")

import navegador  # noqa: E402
from app.paginas.crava_cotas import slack_crava  # noqa: E402

ARQUIVO_LOG = RAIZ_PORTAL / "dados" / "crava_cotas" / "aviso_automatico.log"


def registrar(texto):
    ARQUIVO_LOG.parent.mkdir(parents=True, exist_ok=True)
    linha = f"{datetime.now():%Y-%m-%d %H:%M:%S} {texto}"
    with ARQUIVO_LOG.open("a", encoding="utf-8") as arquivo:
        arquivo.write(linha + "\n")
    print(linha, flush=True)


def avisarFalha(rotulo, motivo):
    mensagem = {"texto": f"*CRAVA COTAS*: não foi possível ler as posições de {rotulo} automaticamente ({motivo}). Confira manualmente.",
                "tabela": None}
    ok, retorno = slack_crava.enviarSlack([mensagem])
    registrar(f"{rotulo}: alerta de falha enviado ao Slack: {retorno}" if ok else f"{rotulo}: não consegui nem enviar o alerta: {retorno}")


def main(rotulo):
    if rotulo not in navegador.DIAS:
        registrar(f"Dia inválido: {rotulo}. Use um de {navegador.DIAS}.")
        return 2
    registrar(f"{rotulo}: iniciando leitura automática")
    try:
        resultado = navegador.abrirPreProcessamento([rotulo], automatico=True)[rotulo]
    except Exception as erro:  # login expirado, site fora do ar, tela diferente...
        registrar(f"{rotulo}: falha na leitura: {traceback.format_exc().splitlines()[-1]}")
        avisarFalha(rotulo, str(erro).splitlines()[0][:120] if str(erro) else type(erro).__name__)
        return 1

    situacao = resultado["situacao"]
    if situacao == "erro":
        registrar(f"{rotulo}: erro na leitura: {resultado.get('diagnostico', '')}")
        avisarFalha(rotulo, "erro ao ler o card")
        return 1
    if situacao != "ok":  # sem card, 0% ou filtro sem itens: não há o que avisar
        registrar(f"{rotulo}: nada a avisar ({situacao})")
        return 0

    mensagens = slack_crava.mensagensSlack({rotulo: resultado}, navegador.COLUNAS_TABELA, [rotulo])
    ok, retorno = slack_crava.enviarSlack(mensagens)
    registrar(f"{rotulo}: {len(resultado['linhas'])} posição(ões) pendente(s); Slack: {retorno}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else ""))
