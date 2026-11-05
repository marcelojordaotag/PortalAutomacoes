"""CRAVA COTAS: tabela do dia e envio ao Slack (sem Streamlit; usado pela página e pelo aviso automático)."""
import json

import pandas as pd

from app.ambiente.config_ambiente import obterVariavel
from app.utilitarias.limite_slack import liberarConteudo, postarComLimite, segundosParaRepetir


def tabelaDoDia(resultado, colunas):
    """DataFrame do dia: separa o código do nome do fundo e converte o valor da cota em número."""
    if not resultado["linhas"]:
        return pd.DataFrame(columns=["ID Exec.", "Código", "Fundo", "CNPJ", "Valor da Cota", "Status"])
    df = pd.DataFrame(resultado["linhas"], columns=colunas)
    partes = df["Fundo"].astype(str).str.partition(" - ")  # sempre 3 colunas, mesmo sem " - " na linha
    df["Código"], df["Fundo"] = partes[0], partes[2]
    df["Valor da Cota"] = pd.to_numeric(df["Valor da Cota"].str.replace(".", "", regex=False).str.replace(",", ".", regex=False),
                                        errors="coerce")  # "-" vira vazio
    return df[["ID Exec.", "Código", "Fundo", "CNPJ", "Valor da Cota", "Status"]]


def celulaSlack(valor):
    texto = str(valor).strip()
    return {"type": "raw_text", "text": texto or "-"}  # o Slack recusa célula vazia


def mensagensSlack(dias, colunas, rotulos):
    """Uma mensagem por dia (o Slack aceita uma tabela por mensagem). Mais de 99 fundos viram mais de uma mensagem."""
    mensagens = []
    for rotulo in rotulos:
        resultado = dias[rotulo]
        cabecalho = f"*CRAVA COTAS: posição indisponível*\n*{rotulo}*" + (f" ({resultado['data']})" if resultado.get("data") else "")
        situacao = resultado["situacao"]
        avisos = {"sem_card": "o card ainda não existe neste dia.", "sem_valores": "progresso em 0%, sem valores para buscar.",
                  "sem_posicao_indisponivel": "nenhum fundo com posição indisponível.", "erro": "não foi possível ler este dia."}
        if situacao in avisos:
            mensagens.append({"texto": f"{cabecalho}: {avisos[situacao]}", "tabela": None})
            continue
        tabela = tabelaDoDia(resultado, colunas)[["Código", "Fundo", "Status"]]
        linhas = [[celulaSlack(valor) for valor in linha] for linha in tabela.itertuples(index=False)]
        topo = [celulaSlack(coluna) for coluna in tabela.columns]
        for inicio in range(0, len(linhas), 99):  # limite do bloco: 100 linhas, com o cabeçalho
            parte = linhas[inicio:inicio + 99]
            texto = f"{cabecalho}: {len(linhas)} fundo(s) com posição indisponível"
            mensagens.append({"texto": texto, "tabela": {"type": "table", "rows": [topo] + parte}})
    return mensagens


def postarSlack(token, payload):
    resposta = postarComLimite("https://slack.com/api/chat.postMessage", headers={"Authorization": f"Bearer {token}"},
                             json=payload, timeout=30)
    resposta.raise_for_status()
    return resposta.json()


def enviarSlack(mensagens):
    """Posta as mensagens no canal pela API do Slack (bot token). Devolve (ok, mensagem)."""
    token = obterVariavel("SLACK_BOT_TOKEN_CRAVA_COTAS")
    canal = obterVariavel("SLACK_CANAL_CRAVA_COTAS")
    if not token or not canal:
        return False, "SLACK_BOT_TOKEN_CRAVA_COTAS e SLACK_CANAL_CRAVA_COTAS não configurados (coloque no env/.env.segredo)."
    conteudo = json.dumps(mensagens, sort_keys=True, default=str)
    espera = segundosParaRepetir(conteudo)
    if espera:
        return False, f"Esta mesma mensagem acabou de ser enviada ao Slack. Aguarde {espera}s para enviar de novo."
    try:
        for mensagem in mensagens:
            titulo = {"type": "section", "text": {"type": "mrkdwn", "text": mensagem["texto"]}}
            base = {"channel": canal, "text": mensagem["texto"].replace("*", "")}
            if mensagem["tabela"] is None:
                resposta = postarSlack(token, {**base, "blocks": [titulo]})
            else:
                # Tabela dentro de "attachments"; se o Slack recusar, tenta tudo em "blocks"
                resposta = postarSlack(token, {**base, "blocks": [titulo], "attachments": [{"blocks": [mensagem["tabela"]]}]})
                if not resposta.get("ok") and resposta.get("error") in ("invalid_attachments", "invalid_blocks"):
                    resposta = postarSlack(token, {**base, "blocks": [titulo, mensagem["tabela"]]})
            if not resposta.get("ok"):
                liberarConteudo(conteudo)
                return False, f"O Slack respondeu: {resposta.get('error')} {resposta.get('response_metadata', '')}"
        return True, "Enviado ao Slack."
    except Exception as excecao:
        liberarConteudo(conteudo)
        return False, f"Não foi possível enviar: {excecao}"
