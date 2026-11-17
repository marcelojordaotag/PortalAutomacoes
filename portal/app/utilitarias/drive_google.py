"""Google Drive do portal: listar, ler e gravar arquivos em pastas (inclusive de Drive compartilhado).

Usa a mesma conexão Google do e-mail (email_gmail): a pessoa conecta a conta uma vez e o acesso é o dela.
As pastas são identificadas pelo ID (trecho final da URL, depois de /folders/), não por caminho de disco.
"""
import io
import mimetypes

import streamlit as st
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

from app.seguranca import controle_acesso
from app.utilitarias import email_gmail

MIME_PASTA = "application/vnd.google-apps.folder"
CAMPOS_ARQUIVO = "id, name, mimeType, size, modifiedTime"


def obterServicoDrive(login):
    """Cliente da API do Drive do usuário. Levanta GmailNaoConectadoErro se não houver autorização válida."""
    from googleapiclient.discovery import build

    return build("drive", "v3", credentials=email_gmail.obterCredenciais(login), cache_discovery=False)


def servicoReutilizado(login):
    """Cliente do Drive guardado na sessão: criar o cliente e a conexão segura custa cerca de 1 s por chamada, então a
    mesma conexão serve a todas as consultas da sessão. Troca sozinho quando a pessoa reconecta a conta Google."""
    dict_token = email_gmail.lerToken(login)
    if not dict_token:
        raise email_gmail.GmailNaoConectadoErro(login)
    tupla_chave = (login, dict_token.get("conectado_em"))
    tupla_guardada = st.session_state.get("_drive_servico")
    if tupla_guardada and tupla_guardada[0] == tupla_chave:
        return tupla_guardada[1]
    servico = obterServicoDrive(login)  # valida o token e o prazo de 24h
    st.session_state["_drive_servico"] = (tupla_chave, servico)
    return servico


def servicoDriveDaSessao():
    """Cliente do Drive do usuário logado no portal."""
    dict_usuario = controle_acesso.usuarioAtual()
    if not dict_usuario:
        raise email_gmail.GmailNaoConectadoErro("")
    return obterServicoDrive(dict_usuario["usuario"])


def _escapar(texto_bruto):
    return str(texto_bruto).replace("\\", "\\\\").replace("'", "\\'")


def listarPasta(servico, id_pasta, ic_somente_pastas=False, ds_filtro_nome=""):
    """Itens diretos de uma pasta: lista de dicts {id, nome, pasta, tamanho, modificado}, pastas primeiro e por nome."""
    ds_consulta = f"'{id_pasta}' in parents and trashed = false"
    if ic_somente_pastas:
        ds_consulta += f" and mimeType = '{MIME_PASTA}'"
    if ds_filtro_nome:
        ds_consulta += f" and name contains '{_escapar(ds_filtro_nome)}'"
    lista_itens, ds_pagina = [], None
    while True:
        dict_resposta = servico.files().list(
            q=ds_consulta, pageToken=ds_pagina, pageSize=200, fields=f"nextPageToken, files({CAMPOS_ARQUIVO})",
            supportsAllDrives=True, includeItemsFromAllDrives=True, corpora="allDrives", orderBy="name",
        ).execute()
        for dict_arquivo in dict_resposta.get("files", []):
            lista_itens.append({
                "id": dict_arquivo["id"], "nome": dict_arquivo["name"], "pasta": dict_arquivo["mimeType"] == MIME_PASTA,
                "tamanho": int(dict_arquivo.get("size", 0)), "modificado": dict_arquivo.get("modifiedTime", ""),
            })
        ds_pagina = dict_resposta.get("nextPageToken")
        if not ds_pagina:
            break
    return sorted(lista_itens, key=lambda dict_item: (not dict_item["pasta"], dict_item["nome"].lower()))


def listarFilhosEmLote(servico, lista_ids, ds_extra="", ds_campos_extra=""):
    """Itens diretos de várias pastas de uma vez (poucas chamadas), com o campo `parents` para saber de qual pasta vieram.
    `ds_extra` completa a busca (ex.: " and mimeType != 'application/vnd.google-apps.folder'") e `ds_campos_extra` os campos."""
    lista_itens = []
    for nr_inicio in range(0, len(lista_ids), 30):
        ds_pais = " or ".join(f"'{id_pai}' in parents" for id_pai in lista_ids[nr_inicio:nr_inicio + 30])
        ds_pagina = None
        while True:
            dict_resposta = servico.files().list(
                q=f"({ds_pais}) and trashed = false{ds_extra}", pageToken=ds_pagina, pageSize=1000,
                fields=f"nextPageToken, files(id, name, mimeType, size, modifiedTime, parents{ds_campos_extra})",
                supportsAllDrives=True, includeItemsFromAllDrives=True, corpora="allDrives",
            ).execute()
            lista_itens += dict_resposta.get("files", [])
            ds_pagina = dict_resposta.get("nextPageToken")
            if not ds_pagina:
                break
    return lista_itens


def buscarPorNome(servico, id_pasta, nm_item, ic_pasta=None):
    """Item de nome exato dentro da pasta (None se não existir). ic_pasta True/False restringe a pastas/arquivos."""
    ds_consulta = f"'{id_pasta}' in parents and trashed = false and name = '{_escapar(nm_item)}'"
    if ic_pasta is not None:
        ds_consulta += f" and mimeType {'=' if ic_pasta else '!='} '{MIME_PASTA}'"
    lista_achados = servico.files().list(
        q=ds_consulta, pageSize=1, fields=f"files({CAMPOS_ARQUIVO})", supportsAllDrives=True,
        includeItemsFromAllDrives=True, corpora="allDrives",
    ).execute().get("files", [])
    return lista_achados[0] if lista_achados else None


def resolverCaminho(servico, id_raiz, lista_nomes):
    """ID da pasta no fim de um caminho de nomes a partir da raiz (ex.: ["2026", "Novembro", "BTG US"]); None se não existir."""
    id_atual = id_raiz
    for nm_pasta in lista_nomes:
        dict_achado = buscarPorNome(servico, id_atual, nm_pasta, ic_pasta=True)
        if not dict_achado:
            return None
        id_atual = dict_achado["id"]
    return id_atual


def obterOuCriarPasta(servico, id_pasta_pai, nm_pasta):
    """ID da subpasta com esse nome; cria se não existir."""
    dict_achado = buscarPorNome(servico, id_pasta_pai, nm_pasta, ic_pasta=True)
    if dict_achado:
        return dict_achado["id"]
    return servico.files().create(
        body={"name": nm_pasta, "mimeType": MIME_PASTA, "parents": [id_pasta_pai]}, fields="id", supportsAllDrives=True,
    ).execute()["id"]


def baixarArquivo(servico, id_arquivo):
    """Conteúdo (bytes) de um arquivo do Drive. Arquivos nativos do Google (Docs/Planilhas) não entram aqui."""
    fluxo_bytes = io.BytesIO()
    baixador = MediaIoBaseDownload(fluxo_bytes, servico.files().get_media(fileId=id_arquivo, supportsAllDrives=True))
    ic_pronto = False
    while not ic_pronto:
        _, ic_pronto = baixador.next_chunk()
    return fluxo_bytes.getvalue()


def enviarArquivo(servico, id_pasta, nm_arquivo, conteudo, ic_substituir=True):
    """Grava o arquivo (bytes) na pasta. Com ic_substituir, atualiza o de mesmo nome em vez de criar duplicata.
    Devolve o dict do arquivo gravado (id, nome...)."""
    ds_tipo = mimetypes.guess_type(nm_arquivo)[0] or "application/octet-stream"
    midia = MediaIoBaseUpload(io.BytesIO(conteudo), mimetype=ds_tipo, resumable=len(conteudo) > 5 * 1024 * 1024)
    dict_existente = buscarPorNome(servico, id_pasta, nm_arquivo, ic_pasta=False) if ic_substituir else None
    if dict_existente:
        return servico.files().update(
            fileId=dict_existente["id"], media_body=midia, fields=CAMPOS_ARQUIVO, supportsAllDrives=True).execute()
    return servico.files().create(
        body={"name": nm_arquivo, "parents": [id_pasta]}, media_body=midia, fields=CAMPOS_ARQUIVO, supportsAllDrives=True).execute()


def mensagemDeErro(erro):
    """Texto curto para mostrar na tela quando uma chamada ao Drive falha."""
    if isinstance(erro, HttpError):
        if erro.resp.status == 404:
            return "Pasta ou arquivo não encontrado, ou a sua conta não tem acesso a ele."
        if erro.resp.status == 403:
            return "A sua conta não tem permissão para esta operação no Drive."
    return str(erro)
