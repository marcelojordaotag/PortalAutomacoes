"""Aviso de solicitação urgente no Slack (sem Streamlit): tabela com todos os itens da solicitação."""
import json

from app.ambiente.config_ambiente import obterVariavel
from app.utilitarias.limite_slack import liberarConteudo, postarComLimite, segundosParaRepetir
from app.paginas.solicitacoes.comum import dataBr, diasEntre


def celula(valor):
    texto = str(valor or "").strip()
    return {"type": "raw_text", "text": texto or "-"}  # o Slack recusa célula vazia


def montarMensagem(reg, extras=()):
    """Cabeçalho em destaque + tabela horizontal (itens nas colunas, valores numa linha) com todos os campos."""
    itens = [
        ("ID", f"#{reg['id']}"), ("Cliente", reg["cliente"]), ("Solicitante", reg.get("solicitante", "")),
        ("Data de abertura", dataBr(reg.get("data"))), ("Competência", reg.get("competencia", "")),
        ("Tipo de demanda", reg.get("tipo", "")), ("Urgência", "URGENTE" if reg.get("prioridade") == "Urgente" else "Não"),
        ("SLA (prazo)", dataBr(reg.get("sla_data"))), ("Descrição", reg.get("descricao", "")),
        ("Evidência", "Sim" if reg.get("evidencia") else "Não possui"), *extras,
    ]
    texto = f":rotating_light: *SOLICITAÇÃO URGENTE #{reg['id']}* :rotating_light:\nSLA: *{dataBr(reg.get('sla_data'))}* · {reg['cliente']}"
    tabela = {"type": "table", "rows": [[celula(item) for item, _ in itens], [celula(valor) for _, valor in itens]]}
    return texto, tabela


def postarSlack(token, payload):
    resposta = postarComLimite("https://slack.com/api/chat.postMessage", headers={"Authorization": f"Bearer {token}"},
                             json=payload, timeout=30)
    resposta.raise_for_status()
    return resposta.json()


def enviarMensagem(texto, tabela, texto_simples, sucesso, cor="#C0392B"):
    """Posta cabeçalho + tabela no canal das solicitações. Devolve (ok, mensagem)."""
    # Variáveis próprias das solicitações; se não existirem, usa o bot e o canal já configurados no env (CRAVA_COTAS)
    token = obterVariavel("SLACK_BOT_TOKEN_SOLICITACOES") or obterVariavel("SLACK_BOT_TOKEN_CRAVA_COTAS")
    canal = obterVariavel("SLACK_CANAL_SOLICITACOES") or obterVariavel("SLACK_CANAL_CRAVA_COTAS")
    if not token or not canal:
        return False, "Slack não enviado: configure SLACK_BOT_TOKEN_SOLICITACOES e SLACK_CANAL_SOLICITACOES no env/.env.segredo."
    conteudo = json.dumps([texto, tabela], sort_keys=True, default=str)
    espera = segundosParaRepetir(conteudo)
    if espera:
        return False, f"Slack não enviado: esta mesma mensagem acabou de ser enviada. Aguarde {espera}s."
    titulo = {"type": "section", "text": {"type": "mrkdwn", "text": texto}}
    base = {"channel": canal, "text": texto_simples}
    try:
        resposta = postarSlack(token, {**base, "blocks": [titulo], "attachments": [{"color": cor, "blocks": [tabela]}]})
        if not resposta.get("ok") and resposta.get("error") in ("invalid_attachments", "invalid_blocks"):
            resposta = postarSlack(token, {**base, "blocks": [titulo, tabela]})
        if not resposta.get("ok"):
            liberarConteudo(conteudo)
            return False, f"Slack respondeu: {resposta.get('error')}"
        return True, sucesso
    except Exception as excecao:  # noqa: BLE001
        liberarConteudo(conteudo)
        return False, f"Não foi possível enviar ao Slack: {excecao}"


def avisarSlackUrgente(reg):
    texto, tabela = montarMensagem(reg)
    return enviarMensagem(texto, tabela, f"SOLICITAÇÃO URGENTE #{reg['id']} - {reg['cliente']}", "Aviso urgente enviado ao Slack.")


def cobrarSlack(reg):
    """Cobra o processamento de uma solicitação ainda sem conclusão."""
    dias = diasEntre(reg.get("data"))
    _, tabela = montarMensagem(reg, extras=[("Status", reg.get("status", "")), ("Aberta há (dias)", dias)])
    urgente = reg.get("prioridade") == "Urgente"
    prefixo = ":rotating_light: *URGENTE* " if urgente else ""
    texto = (f"{prefixo}:hourglass_flowing_sand: *COBRANÇA: solicitação #{reg['id']} sem resposta* — aberta há {dias} dia(s)"
             f"{' · SLA ' + dataBr(reg['sla_data']) if reg.get('sla_data') else ''}\n{reg['cliente']} · status: {reg.get('status', '')}")
    return enviarMensagem(texto, tabela, f"COBRANÇA: solicitação #{reg['id']} - {reg['cliente']}", "Cobrança enviada ao Slack.", cor="#E67E22")
