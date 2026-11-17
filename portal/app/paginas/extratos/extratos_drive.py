"""Extratos recebidos no Google Drive: <raiz>/<ano>/<MM>- <Mês>/<pasta do fundo>/arquivo.

A raiz é o Drive compartilhado dos extratos mensais (DRIVE_BKO_PASTA_EXTRATOS). O ano e o mês vêm da data de referência da
rodada: fechamento de outubro de 2026 grava em 2026/10- Outubro; em 2027 passa a usar a pasta de 2027. Pastas que ainda não
existem são criadas. A pasta do fundo é a que já existe com o mesmo nome (ou com o nome dele dentro do nome do fundo); se não
houver, cria uma com o nome do fundo. O acesso é o da conta Google que a pessoa conectou no portal.
"""
import hashlib
import io
import os
import re
import threading
import unicodedata
from concurrent.futures import ThreadPoolExecutor

import streamlit as st

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

from app.ambiente.config_ambiente import obterVariavel
from app.seguranca import controle_acesso
from app.utilitarias import drive_google, email_gmail

MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
PASTAS_ESPECIAIS = ("_Revisar", "Remetente")  # pastas de anexos sem fundo identificado: não entram no casamento por nome
MAX_PAGINAS_PDF = 3

trava_criacao = threading.Lock()
trava_texto = threading.Lock()
dict_textos = {}  # (id do arquivo, data de modificação) -> texto das primeiras páginas do PDF


class ArquivoSalvo:
    """Arquivo que já está no Drive, numa pasta de fundo do mês."""

    def __init__(self, id_arquivo, nm_arquivo, nm_pasta, ds_modificado=""):
        self.id = id_arquivo
        self.nome = nm_arquivo
        self.pasta = nm_pasta
        self.modificado = ds_modificado

    def paraTexto(self):
        """Forma guardada no banco (portal_tb_extratos_anexo_salvo.ds_caminho)."""
        return f"drive:{self.id}|{self.pasta}|{self.nome}"


def arquivoDeTexto(ds_texto):
    """Volta de paraTexto(); None se o texto for de um arquivo antigo em disco."""
    if not str(ds_texto).startswith("drive:"):
        return None
    lista_partes = str(ds_texto)[len("drive:"):].split("|", 2)
    if len(lista_partes) != 3:
        return None
    return ArquivoSalvo(lista_partes[0], lista_partes[2], lista_partes[1])


def loginAtual():
    dict_usuario = controle_acesso.usuarioAtual()
    if not dict_usuario:
        raise email_gmail.GmailNaoConectadoErro("")
    return dict_usuario["usuario"]


class PastaDeTesteAusenteErro(Exception):
    """A tela de teste precisa de uma pasta de teste no Drive (DRIVE_BKO_PASTA_EXTRATOS_TESTE) e ela não foi definida."""


def idRaiz():
    """Raiz dos extratos no Drive. Na tela de teste (/extratos?teste) é uma pasta de teste: nunca grava no Drive da empresa."""
    if "teste" in st.query_params:
        id_teste = obterVariavel("DRIVE_BKO_PASTA_EXTRATOS_TESTE")
        if not id_teste or id_teste.startswith("DEFINIR-"):
            raise PastaDeTesteAusenteErro("DRIVE_BKO_PASTA_EXTRATOS_TESTE não definida: a tela de teste não grava no Drive da empresa.")
        return id_teste
    return obterVariavel("DRIVE_BKO_PASTA_EXTRATOS")


def nomeSeguro(ds_texto):
    ds_limpo = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(ds_texto))
    return re.sub(r"\s+", " ", ds_limpo).strip(" .") or "sem_nome"


def _norm(ds_texto):
    ds_ascii = unicodedata.normalize("NFKD", str(ds_texto)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", ds_ascii).strip()


def _numeroDoMes(nm_pasta):
    """Número do mês no começo do nome da pasta ('01 - Janeiro', '10- Outubro'); None se não tiver."""
    achou = re.match(r"\s*(\d{1,2})\s*[-–]", nm_pasta)
    return int(achou.group(1)) if achou else None


def textoErro(erro):
    if isinstance(erro, email_gmail.GmailNaoConectadoErro):
        return "A conexão com a conta Google expirou ou não existe. Conecte-se de novo (use \"Conectar ao Google\" na lateral)."
    if isinstance(erro, drive_google.HttpError):
        return drive_google.mensagemDeErro(erro)
    return str(erro)


ERROS_DRIVE = (drive_google.HttpError, email_gmail.GmailNaoConectadoErro, PastaDeTesteAusenteErro)


# ---------------------------------------------------------------- pastas
@st.cache_data(ttl=120, show_spinner=False)
def _subpastas(login, id_pasta):
    lista_itens = drive_google.listarPasta(drive_google.servicoReutilizado(login), id_pasta, ic_somente_pastas=True)
    return [{"id": dict_item["id"], "nome": dict_item["nome"]} for dict_item in lista_itens]


def _acharOuCriar(login, id_pai, casa, nm_novo, ic_criar):
    """ID da subpasta cujo nome satisfaz `casa`. Se não existir e ic_criar, cria com o nome nm_novo."""
    for dict_pasta in _subpastas(login, id_pai):
        if casa(dict_pasta["nome"]):
            return dict_pasta["id"]
    if not ic_criar:
        return None
    servico = drive_google.servicoReutilizado(login)
    with trava_criacao:  # duas pessoas ao mesmo tempo não criam a mesma pasta duas vezes
        for dict_pasta in drive_google.listarPasta(servico, id_pai, ic_somente_pastas=True):
            if casa(dict_pasta["nome"]):
                _subpastas.clear()
                return dict_pasta["id"]
        id_criada = servico.files().create(
            body={"name": nm_novo, "mimeType": drive_google.MIME_PASTA, "parents": [id_pai]}, fields="id", supportsAllDrives=True,
        ).execute()["id"]
    _subpastas.clear()
    return id_criada


def idPastaDoMes(login, nr_ano, nr_mes, ic_criar=False):
    """ID da pasta do mês (<raiz>/<ano>/<MM>- <Mês>); None se não existir e ic_criar for False."""
    id_ano = _acharOuCriar(login, idRaiz(), lambda nm_pasta: nm_pasta.strip() == str(nr_ano), str(nr_ano), ic_criar)
    if not id_ano:
        return None
    return _acharOuCriar(login, id_ano, lambda nm_pasta: _numeroDoMes(nm_pasta) == nr_mes, f"{nr_mes:02d}- {MESES[nr_mes - 1]}", ic_criar)


def idPastaDoFundo(login, id_mes, nm_fundo, ic_criar=False):
    """Pasta do fundo dentro do mês: a de nome igual; senão a que tem o nome (palavras inteiras) dentro do nome do fundo
    (a mais específica) ou, no sentido contrário, o nome do fundo dentro do nome da pasta; senão cria (se ic_criar)."""
    nf = _norm(nm_fundo)
    lista_pastas = [dict_pasta for dict_pasta in _subpastas(login, id_mes) if not dict_pasta["nome"].startswith(PASTAS_ESPECIAIS)]
    if nf:
        for dict_pasta in lista_pastas:
            if _norm(dict_pasta["nome"]) == nf:
                return dict_pasta["id"]
        lista_dentro = [dict_pasta for dict_pasta in lista_pastas if _norm(dict_pasta["nome"]) and f" {_norm(dict_pasta['nome'])} " in f" {nf} "]
        if lista_dentro:
            return max(lista_dentro, key=lambda dict_pasta: len(_norm(dict_pasta["nome"])))["id"]
        lista_contem = [dict_pasta for dict_pasta in lista_pastas if f" {nf} " in f" {_norm(dict_pasta['nome'])} "]
        if lista_contem:
            return min(lista_contem, key=lambda dict_pasta: len(_norm(dict_pasta["nome"])))["id"]
    if not ic_criar:
        return None
    return _acharOuCriar(login, id_mes, lambda nm_pasta: nm_pasta == nomeSeguro(nm_fundo), nomeSeguro(nm_fundo), True)


def nomeDaPasta(login, id_mes, id_pasta, nm_padrao=""):
    """Nome real da pasta (que pode ser diferente do nome do fundo, ex.: 'Chimera')."""
    for dict_pasta in _subpastas(login, id_mes):
        if dict_pasta["id"] == id_pasta:
            return dict_pasta["nome"]
    return nm_padrao


def idPastaPorNome(login, id_mes, nm_pasta, ic_criar=True):
    """Pasta de nome exato dentro do mês (ex.: a de revisão '_Revisar - <remetente>'); cria se não existir."""
    return _acharOuCriar(login, id_mes, lambda nm_existente: nm_existente == nomeSeguro(nm_pasta), nomeSeguro(nm_pasta), ic_criar)


def linkDaPasta(id_pasta):
    return f"https://drive.google.com/drive/folders/{id_pasta}"


# ---------------------------------------------------------------- arquivos
@st.cache_data(ttl=30, show_spinner=False)
def listarArquivos(login, id_pasta):
    """Arquivos (não pastas) de uma pasta: [{id, nome, tamanho, modificado}]."""
    lista_itens = drive_google.listarPasta(drive_google.servicoReutilizado(login), id_pasta)
    return [{"id": dict_item["id"], "nome": dict_item["nome"], "tamanho": dict_item["tamanho"], "modificado": dict_item["modificado"]}
            for dict_item in lista_itens if not dict_item["pasta"] and not dict_item["nome"].startswith("~$")]


def salvarArquivo(login, id_pasta, nm_pasta, nm_arquivo, conteudo, ic_evitar_duplicata=False):
    """Grava o arquivo na pasta sem sobrescrever nada: nome repetido ganha ' (1)', ' (2)'... Com ic_evitar_duplicata, se já há um
    arquivo de mesmo nome e tamanho, não grava e devolve o existente. Devolve o ArquivoSalvo."""
    servico = drive_google.servicoReutilizado(login)
    dict_existentes = {dict_item["nome"].lower(): dict_item for dict_item in drive_google.listarPasta(servico, id_pasta) if not dict_item["pasta"]}
    ds_base, ds_extensao = os.path.splitext(nm_arquivo)
    nm_destino, nr_copia = nm_arquivo, 1
    while nm_destino.lower() in dict_existentes:
        dict_igual = dict_existentes[nm_destino.lower()]
        if ic_evitar_duplicata and dict_igual["tamanho"] == len(conteudo):
            return ArquivoSalvo(dict_igual["id"], dict_igual["nome"], nm_pasta, dict_igual["modificado"])
        nm_destino = f"{ds_base} ({nr_copia}){ds_extensao}"
        nr_copia += 1
    dict_criado = drive_google.enviarArquivo(servico, id_pasta, nm_destino, conteudo, ic_substituir=False)
    listarArquivos.clear()
    return ArquivoSalvo(dict_criado["id"], dict_criado["name"], nm_pasta, dict_criado.get("modifiedTime", ""))


def moverArquivo(login, arquivo, id_pasta_destino, nm_pasta_destino):
    """Move um arquivo que já está no Drive para outra pasta (ex.: da pasta de revisão para a do fundo)."""
    servico = drive_google.servicoReutilizado(login)
    lista_pais = servico.files().get(fileId=arquivo.id, fields="parents", supportsAllDrives=True).execute().get("parents", [])
    servico.files().update(fileId=arquivo.id, addParents=id_pasta_destino, removeParents=",".join(lista_pais),
                           fields="id", supportsAllDrives=True).execute()
    listarArquivos.clear()
    return ArquivoSalvo(arquivo.id, arquivo.nome, nm_pasta_destino, arquivo.modificado)


def tamanhoDoArquivo(login, arquivo):
    """Tamanho (bytes) de um arquivo que está no Drive."""
    dict_info = drive_google.servicoReutilizado(login).files().get(fileId=arquivo.id, fields="size", supportsAllDrives=True).execute()
    return int(dict_info.get("size", 0))


def guardarTexto(arquivo, ds_texto):
    """Guarda o texto do PDF que já foi lido (do temporário, antes do envio), para não baixar o arquivo de novo."""
    with trava_texto:
        dict_textos[(arquivo.id, arquivo.modificado)] = ds_texto


def _extrairTexto(conteudo):
    try:
        return " ".join((pagina.extract_text() or "") for pagina in PdfReader(io.BytesIO(conteudo)).pages[:MAX_PAGINAS_PDF])
    except Exception:  # noqa: BLE001  (PDF protegido ou corrompido: sem texto)
        return ""


def _baixarTexto(login, arquivo, servico):
    chave = (arquivo.id, arquivo.modificado)
    with trava_texto:
        if chave in dict_textos:
            return dict_textos[chave]
    ds_texto = _extrairTexto(drive_google.baixarArquivo(servico, arquivo.id)) if PdfReader is not None and arquivo.nome.lower().endswith(".pdf") else ""
    with trava_texto:
        dict_textos[chave] = ds_texto
    return ds_texto


def textoDoPdf(arquivo):
    """Texto das primeiras páginas do PDF que está no Drive (guardado em memória por arquivo e data de modificação)."""
    login = loginAtual()
    return _baixarTexto(login, arquivo, drive_google.servicoReutilizado(login))


def prepararTextos(login, lista_arquivos):
    """Baixa e lê vários PDFs ao mesmo tempo, para a contagem não esperar um arquivo de cada vez."""
    lista_faltam = [arquivo for arquivo in lista_arquivos if arquivo.nome.lower().endswith(".pdf") and (arquivo.id, arquivo.modificado) not in dict_textos]
    if not lista_faltam or PdfReader is None:
        return

    def lerUm(arquivo):
        _baixarTexto(login, arquivo, drive_google.obterServicoDrive(login))  # cada thread usa a sua conexão

    with ThreadPoolExecutor(max_workers=min(6, len(lista_faltam))) as executor:
        list(executor.map(lerUm, lista_faltam))


def assinaturaDoMes(login, nr_ano, nr_mes):
    return _assinaturaDoMes(login, nr_ano, nr_mes, idRaiz())  # a raiz entra na chave do cache: tela de teste e tela real não se misturam


@st.cache_data(ttl=45, show_spinner=False)
def _assinaturaDoMes(login, nr_ano, nr_mes, id_raiz):
    """Impressão digital dos arquivos do mês (ids e datas de modificação): muda quando chega, sai ou é alterado um arquivo,
    inclusive os colocados à mão. Serve para a tela perceber a mudança sem baixar nada."""
    id_mes = idPastaDoMes(login, nr_ano, nr_mes, ic_criar=False)
    if not id_mes:
        return ""
    servico = drive_google.servicoReutilizado(login)
    lista_ids = [id_mes] + [dict_pasta["id"] for dict_pasta in drive_google.listarPasta(servico, id_mes, ic_somente_pastas=True)]
    lista_itens = drive_google.listarFilhosEmLote(servico, lista_ids, f" and mimeType != '{drive_google.MIME_PASTA}'")
    ds_base = "|".join(sorted(f"{dict_item['id']}:{dict_item.get('modifiedTime', '')}" for dict_item in lista_itens))
    return hashlib.sha1(ds_base.encode()).hexdigest()
