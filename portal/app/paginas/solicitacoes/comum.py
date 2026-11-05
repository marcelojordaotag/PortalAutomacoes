"""Dados, regras e e-mail das solicitações, compartilhados por Registro de Solicitações e Registro Solicitações de Fechamento."""
import json
import os
import shutil
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from app.ambiente.config_ambiente import obterDiretorioDados

PASTA = obterDiretorioDados("solicitacoes")
# Para migrar à pasta compartilhada depois, basta apontar PASTA_DADOS para ela (ex.: Path(r"G:\...")).
PASTA_DADOS = PASTA
ARQ_SOLICITACOES = PASTA_DADOS / "solicitacoes.json"
ARQ_CLIENTES = PASTA_DADOS / "clientes.json"
PASTA_BACKUP = PASTA_DADOS / "backups"
PASTA_EVIDENCIAS = PASTA_DADOS / "evidencias"

TIPOS = ["Ajuste Fechamento", "Dúvida", "Pendente Extrato"]
STATUS = ["Em aberto", "Em Processamento", "Concluído"]
CLASSE_STATUS = {"Em aberto": "div", "Em Processamento": "warn", "Concluído": "ok"}
# Prazo (dias corridos) por tipo; não concluída além disso conta como atrasada. Ajuste aqui conforme o combinado.
SLA_DIAS = {"Ajuste Fechamento": 5, "Dúvida": 2, "Pendente Extrato": 5}
SLA_PADRAO = 5
PRIORIDADES = ["Normal", "Urgente"]
MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
URGENTE_BADGE = '<span class="badge div">URGENTE</span>'
SLA_URGENTE_DIAS = 1  # solicitação urgente ignora o prazo do tipo e deve sair em 1 dia

# Nomes de solicitante que são o mesmo usuário (chave sem acento e minúscula -> nome oficial).
ALIAS_SOLICITANTE = {"jessica": "Jéssica"}

EMAIL_PARA = os.getenv("EMAIL_PARA_SOLICITACOES")
EMAIL_CC = os.getenv("EMAIL_CC_SOLICITACOES")

# ---------------------------------------------------------------- dados
def agora():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def canonSolicitante(nome):
    """Padroniza o nome (espaços e acentos nos apelidos conhecidos) para não duplicar a mesma pessoa."""
    nome = " ".join((nome or "").split())
    chave = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().lower()
    return ALIAS_SOLICITANTE.get(chave, nome)


def carregar():
    try:
        regs = json.loads(ARQ_SOLICITACOES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    for registro in regs:
        registro["solicitante"] = canonSolicitante(registro.get("solicitante", ""))
    return regs


def backupDiario():
    """Copia o solicitacoes.json para backups/ uma vez por dia (estado do início do dia)."""
    if not ARQ_SOLICITACOES.exists():
        return
    PASTA_BACKUP.mkdir(exist_ok=True)
    destino = PASTA_BACKUP / f"solicitacoes_{date.today().isoformat()}.json"
    if not destino.exists():
        shutil.copy2(ARQ_SOLICITACOES, destino)


def salvar(registros):
    backupDiario()
    tmp = ARQ_SOLICITACOES.with_suffix(".tmp")
    tmp.write_text(json.dumps(registros, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ARQ_SOLICITACOES)  # troca atômica: nunca deixa o arquivo pela metade


def carregarClientes():
    try:
        return json.loads(ARQ_CLIENTES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def evento(reg, titulo, detalhe=""):
    quem = (st.session_state.get("auth") or {}).get("usuario", "")
    reg.setdefault("historico", []).append({"quando": agora(), "evento": titulo, "detalhe": detalhe, "usuario": quem})


def nomeCurto(cliente):
    """'1234 - JOAO DA SILVA SANTOS' -> '1234 - JOAO SILVA SANTOS' (ID + primeiro + dois últimos)."""
    if " - " not in cliente:
        return cliente
    id_parte, resto = cliente.split(" - ", 1)
    partes_nome = resto.strip().split()
    if len(partes_nome) >= 3:
        partes_nome = [partes_nome[0], partes_nome[-2], partes_nome[-1]]
    return f"{id_parte} - {' '.join(partes_nome)}"


def prazoDias(registro):
    if registro.get("prioridade") == "Urgente" and registro.get("sla_data") and registro.get("data"):
        return max(diasEntre(registro["data"], registro["sla_data"]) or 0, 0)  # SLA escolhido pelo solicitante
    if registro.get("prioridade") == "Urgente":
        return SLA_URGENTE_DIAS
    return SLA_DIAS.get(registro.get("tipo", ""), SLA_PADRAO)


def previsaoConclusao(registros, tipo, prioridade="Normal"):
    """Estima em quantos dias uma solicitação nova do tipo deve ser concluída, com base nas concluídas.

    Retorna mediana (metade conclui até lá), p80 (80% concluem até lá) e a quantidade usada.
    Com menos de 3 concluídas do tipo usa todas as concluídas; sem histórico, cai no prazo (SLA).
    """
    def duracoes(filtro_tipo):
        out = []
        for registro in registros:
            if registro.get("status") != "Concluído" or not registro.get("data_conclusao") or not registro.get("data"):
                continue
            if filtro_tipo and registro.get("tipo") != tipo:
                continue
            if (registro.get("prioridade", "Normal") == "Urgente") != (prioridade == "Urgente"):
                continue
            out.append(diasEntre(registro["data"], registro["data_conclusao"]))
        return sorted(duracao for duracao in out if duracao is not None and duracao >= 0)

    base, origem = duracoes(True), f"do tipo {tipo}"
    if len(base) < 3:
        base, origem = duracoes(False), "de todos os tipos"
    if len(base) < 3:
        return {"n": len(base), "mediana": None, "p80": None, "origem": origem}
    mediana = base[len(base) // 2] if len(base) % 2 else (base[len(base) // 2 - 1] + base[len(base) // 2]) / 2
    p80 = base[min(len(base) - 1, int(len(base) * 0.8))]
    return {"n": len(base), "mediana": mediana, "p80": p80, "origem": origem}


def textoPrevisao(prev, tipo, prioridade, a_partir_de):
    if prev["mediana"] is None:
        sla = SLA_URGENTE_DIAS if prioridade == "Urgente" else SLA_DIAS.get(tipo, SLA_PADRAO)
        return (f"Ainda não há histórico suficiente para prever. Prazo combinado (SLA): {sla} dia(s), "
                f"até {(a_partir_de + timedelta(days=sla)).strftime('%d/%m/%Y')}.")
    med, p80 = prev["mediana"], prev["p80"]
    d_med = a_partir_de + timedelta(days=int(round(med)))
    d_p80 = a_partir_de + timedelta(days=int(p80))
    return (f"Previsão (base: {prev['n']} concluídas {prev['origem']}): metade é concluída em até **{med:g} dia(s)** "
            f"(≈ {d_med.strftime('%d/%m/%Y')}) e 80% em até **{p80} dia(s)** (≈ {d_p80.strftime('%d/%m/%Y')}).")


def dataBr(iso):
    return date.fromisoformat(iso).strftime("%d/%m/%Y") if iso else ""


def diasEntre(ini, fim=None):
    if not ini:
        return None
    d0 = date.fromisoformat(ini)
    d1 = date.fromisoformat(fim) if fim else date.today()
    return (d1 - d0).days


def paraDf(registros):
    linhas = []
    for registro in registros:
        concluido = registro["status"] == "Concluído"
        dias = diasEntre(registro.get("data"), registro.get("data_conclusao") if concluido else None)
        linhas.append({
            "ID": registro["id"], "Cliente": registro["cliente"], "Solicitante": registro.get("solicitante", ""),
            "Data": registro.get("data"), "Tipo": registro.get("tipo", ""), "Prioridade": registro.get("prioridade", "Normal"), "Status": registro["status"],
            "Conclusão": registro.get("data_conclusao"), "Dias": dias,
            "Dias p/ concluir": dias if concluido else None,
            "Aberta há (dias)": None if concluido else dias,
            "Atrasada": (not concluido) and dias is not None and dias > prazoDias(registro),
            "Prazo (dias)": prazoDias(registro),
            "No prazo": (dias <= prazoDias(registro)) if concluido and dias is not None else None,
            "Descrição": registro.get("descricao", ""),
        })
    df = pd.DataFrame(linhas)
    if not df.empty:
        df["Data_dt"] = pd.to_datetime(df["Data"])
        df["Mês"] = df["Data_dt"].dt.strftime("%Y-%m")
    return df


# ---------------------------------------------------------------- e-mail (Outlook)
def abrirEmail(reg):
    """Abre o rascunho no Outlook (não envia). Retorna (ok, mensagem)."""
    try:
        import pythoncom
        import win32com.client  # só existe no Windows com Outlook
        pythoncom.CoInitialize()  # o Streamlit roda a página numa thread sem COM inicializado
        aplicativo_outlook = win32com.client.Dispatch("Outlook.Application")
        mensagem_email = aplicativo_outlook.CreateItem(0)
    except Exception as erro:  # noqa: BLE001
        return False, f"Não consegui acessar o Outlook: {erro}"

    evidencia = reg.get("evidencia") or ""
    mensagem_email.To = EMAIL_PARA
    mensagem_email.CC = EMAIL_CC
    urgente = "URGENTE - " if reg.get("prioridade") == "Urgente" else ""
    mensagem_email.Subject = f"{urgente}NOVA SOLICITAÇÃO : {nomeCurto(reg['cliente'])}"
    if urgente:
        mensagem_email.Importance = 2  # alta
    mensagem_email.Body = (
        "Olá,\n\nUma nova demanda foi registrada:\n\n"
        f"CLIENTE: {reg['cliente']}\nSOLICITANTE: {reg.get('solicitante', '')}\n"
        f"TIPO: {reg.get('tipo', '')}\nCOMPETÊNCIA: {reg.get('competencia', '')}\nPRIORIDADE: {reg.get('prioridade', 'Normal')}\n"
        f"{'SLA (PRAZO): ' + dataBr(reg['sla_data']) + chr(10) if reg.get('sla_data') else ''}DESCRIÇÃO: {reg.get('descricao', '')}\n"
        f"EVIDÊNCIA: {'Sim (conforme anexo)' if evidencia else 'Não possui evidência'}\n\n"
        f"Favor iniciar a análise.\n\nAtenciosamente,\n{reg.get('solicitante', '')}"
    )
    if evidencia and Path(evidencia).exists():
        mensagem_email.Attachments.Add(str(Path(evidencia).resolve()))
    mensagem_email.Display()
    return True, "Rascunho aberto no Outlook."
