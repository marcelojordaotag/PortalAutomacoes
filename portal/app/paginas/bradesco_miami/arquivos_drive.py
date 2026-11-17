"""Arquivos do Offshore no Google Drive (só leitura): histórico por banco/ano/mês e o arquivo modelo (De-Para e e-mails).

A pasta do histórico e o arquivo modelo são achados pelo ID (DRIVE_BKO_PASTA_HISTORICO e DRIVE_BKO_ARQUIVO_MODELO); dali em
diante as pastas são achadas pelo nome (ano, mês, banco). O acesso é o da conta Google que a pessoa conectou no portal.
Para a tela não ficar lenta: uma conexão só por sessão, poucas consultas em lote, cache e downloads em paralelo.
"""
import io
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

import streamlit as st
from googleapiclient.errors import HttpError
from openpyxl import load_workbook

from app.ambiente.config_ambiente import obterVariavel
from app.seguranca import controle_acesso
from app.utilitarias import drive_google, email_gmail

ERROS_DRIVE = (HttpError, email_gmail.GmailNaoConectadoErro)
NOME_HISTORICO = "Histórico Excel"
NOME_MODELO = "Modelo BTG_US BTG_Cayman MS.xlsm"
SEGUNDOS_CACHE_ARQUIVO = 300
MAX_ARQUIVOS_CACHE = 80

dict_bytes_cache = OrderedDict()  # (login, id, modificado) -> (momento, bytes); compartilhado entre sessões
trava_cache = threading.Lock()


class ArquivoDrive:
    """Arquivo do histórico no Drive (id None = não existe). Imita o mínimo de pathlib.Path que a página usa."""

    def __init__(self, nm_arquivo, id_arquivo, ds_caminho, ds_modificado=""):
        self.name = nm_arquivo
        self.id = id_arquivo
        self.caminho = ds_caminho
        self.modificado = ds_modificado

    def exists(self):
        return self.id is not None

    def chave(self):
        return (self.name, self.id, self.modificado)

    def __str__(self):
        return self.caminho

    def __eq__(self, outro):
        return isinstance(outro, ArquivoDrive) and self.chave() == outro.chave()

    def __hash__(self):
        return hash(self.chave())


def loginAtual():
    dict_usuario = controle_acesso.usuarioAtual()
    if not dict_usuario:
        raise email_gmail.GmailNaoConectadoErro("")
    return dict_usuario["usuario"]


def textoErro(erro):
    """Texto curto para a tela quando uma chamada ao Drive falha."""
    if isinstance(erro, email_gmail.GmailNaoConectadoErro):
        return "A conexão com a conta Google expirou ou não existe. Conecte-se de novo (use \"Conectar ao Google\" na lateral)."
    if isinstance(erro, HttpError):
        return drive_google.mensagemDeErro(erro)
    return str(erro)


def idHistorico():
    return obterVariavel("DRIVE_BKO_PASTA_HISTORICO")


# ---------------------------------------------------------------- pastas do histórico
@st.cache_data(ttl=120, show_spinner=False)
def pastasDoMes(login, nr_ano, nm_mes):
    """Pastas do ano e do mês e as pastas dos bancos que há no mês: {"ano": id|None, "mes": id|None, "bancos": {nome: id}}.
    São 3 consultas no máximo, e valem para todos os bancos."""
    servico = drive_google.servicoReutilizado(login)
    dict_pastas = {"ano": None, "mes": None, "bancos": {}}
    dict_ano = drive_google.buscarPorNome(servico, idHistorico(), str(nr_ano), ic_pasta=True)
    if not dict_ano:
        return dict_pastas
    dict_pastas["ano"] = dict_ano["id"]
    dict_mes = drive_google.buscarPorNome(servico, dict_ano["id"], nm_mes, ic_pasta=True)
    if not dict_mes:
        return dict_pastas
    dict_pastas["mes"] = dict_mes["id"]
    dict_pastas["bancos"] = {dict_item["nome"]: dict_item["id"] for dict_item in
                             drive_google.listarPasta(servico, dict_mes["id"], ic_somente_pastas=True)}
    return dict_pastas


@st.cache_data(ttl=60, show_spinner=False)
def arquivosDoDia(login, nr_ano, nm_mes, ds_dia):
    """Arquivos .xlsx do dia (AAAAMMDD) em todas as pastas de banco do mês, numa consulta só:
    {pasta do banco: {nome em minúsculas: (id, nome, modificado)}}."""
    dict_bancos = pastasDoMes(login, nr_ano, nm_mes)["bancos"]
    if not dict_bancos:
        return {}
    dict_nomes = {id_pasta: nm_pasta for nm_pasta, id_pasta in dict_bancos.items()}
    servico = drive_google.servicoReutilizado(login)
    dict_saida = {nm_pasta: {} for nm_pasta in dict_bancos}
    for dict_item in _filhosDe(servico, list(dict_bancos.values()), f" and name contains '{ds_dia}'", ", modifiedTime"):
        nm_arquivo = dict_item["name"]
        if nm_arquivo.lower().endswith(".xlsx") and not nm_arquivo.startswith("~$"):
            dict_saida[dict_nomes[dict_item["parents"][0]]][nm_arquivo.lower()] = (dict_item["id"], nm_arquivo, dict_item.get("modifiedTime", ""))
    return dict_saida


def _filhosDe(servico, lista_ids, ds_extra="", ds_campos_extra=""):
    """Itens diretos de várias pastas de uma vez (poucas chamadas), com o campo `parents` para saber de qual pasta vieram."""
    lista_itens = []
    for nr_inicio in range(0, len(lista_ids), 30):
        ds_pais = " or ".join(f"'{id_pai}' in parents" for id_pai in lista_ids[nr_inicio:nr_inicio + 30])
        ds_pagina = None
        while True:
            dict_resposta = servico.files().list(
                q=f"({ds_pais}) and trashed = false{ds_extra}", pageToken=ds_pagina, pageSize=1000,
                fields=f"nextPageToken, files(id, name, mimeType, parents{ds_campos_extra})", supportsAllDrives=True,
                includeItemsFromAllDrives=True, corpora="allDrives",
            ).execute()
            lista_itens += dict_resposta.get("files", [])
            ds_pagina = dict_resposta.get("nextPageToken")
            if not ds_pagina:
                break
    return lista_itens


@st.cache_data(ttl=600, show_spinner=False)
def listarTodosDoBanco(login, nm_pasta_banco):
    """Todos os .xlsx do banco em todos os anos e meses: [{id, nome, caminho, modificado}]. 4 consultas ao Drive, em lote."""
    servico = drive_google.servicoReutilizado(login)
    ds_pasta = f" and mimeType = '{drive_google.MIME_PASTA}'"
    dict_anos = {dict_item["id"]: dict_item["name"] for dict_item in _filhosDe(servico, [idHistorico()], ds_pasta)}
    dict_meses = {dict_item["id"]: (dict_anos[dict_item["parents"][0]], dict_item["name"])
                  for dict_item in _filhosDe(servico, list(dict_anos), ds_pasta)}
    ds_banco = nm_pasta_banco.replace("'", "\\'")
    dict_bancos = {dict_item["id"]: (*dict_meses[dict_item["parents"][0]], dict_item["name"])
                   for dict_item in _filhosDe(servico, list(dict_meses), f"{ds_pasta} and name = '{ds_banco}'")}
    lista_arquivos = []
    for dict_item in _filhosDe(servico, list(dict_bancos), f" and mimeType != '{drive_google.MIME_PASTA}' and name contains '.xlsx'", ", modifiedTime"):
        if not dict_item["name"].lower().endswith(".xlsx") or dict_item["name"].startswith("~$"):
            continue
        lista_arquivos.append({
            "id": dict_item["id"], "nome": dict_item["name"], "modificado": dict_item.get("modifiedTime", ""),
            "caminho": "/".join([NOME_HISTORICO, *dict_bancos[dict_item["parents"][0]], dict_item["name"]]),
        })
    return lista_arquivos


# ---------------------------------------------------------------- conteúdo dos arquivos
def _guardarNoCache(chave, conteudo):
    with trava_cache:
        dict_bytes_cache[chave] = (time.time(), conteudo)
        dict_bytes_cache.move_to_end(chave)
        while len(dict_bytes_cache) > MAX_ARQUIVOS_CACHE:
            dict_bytes_cache.popitem(last=False)


def _lerDoCache(chave):
    with trava_cache:
        tupla_guardada = dict_bytes_cache.get(chave)
    if tupla_guardada and time.time() - tupla_guardada[0] < SEGUNDOS_CACHE_ARQUIVO:
        return tupla_guardada[1]
    return None


def baixarBytes(login, id_arquivo, ds_modificado="", servico=None):
    """Conteúdo do arquivo; fica em cache (por arquivo e data de modificação) para a tela não baixar de novo."""
    chave = (login, id_arquivo, ds_modificado)
    conteudo = _lerDoCache(chave)
    if conteudo is None:
        conteudo = drive_google.baixarArquivo(servico or drive_google.servicoReutilizado(login), id_arquivo)
        _guardarNoCache(chave, conteudo)
    return conteudo


def baixarVarios(login, lista_arquivos):
    """Baixa vários arquivos ao mesmo tempo ([(id, modificado)]) e deixa tudo em cache. Cada thread usa a sua conexão."""
    lista_faltam = [(id_arquivo, ds_modificado) for id_arquivo, ds_modificado in dict.fromkeys(lista_arquivos)
                    if _lerDoCache((login, id_arquivo, ds_modificado)) is None]
    if not lista_faltam:
        return

    def baixarUm(tupla_arquivo):
        baixarBytes(login, tupla_arquivo[0], tupla_arquivo[1], servico=drive_google.obterServicoDrive(login))

    with ThreadPoolExecutor(max_workers=min(6, len(lista_faltam))) as executor:
        list(executor.map(baixarUm, lista_faltam))


def abrirPlanilha(arquivo):
    """Abre (somente leitura) um arquivo do histórico, baixado do Drive."""
    return load_workbook(io.BytesIO(baixarBytes(loginAtual(), arquivo.id, arquivo.modificado)), read_only=True, data_only=True)


def idModelo():
    return obterVariavel("DRIVE_BKO_ARQUIVO_MODELO")


def abrirModelo(login):
    """Abre (somente leitura) o arquivo modelo (aba De-Para e aba E-mail), baixado do Drive."""
    return load_workbook(io.BytesIO(baixarBytes(login, idModelo())), read_only=True, data_only=True)
