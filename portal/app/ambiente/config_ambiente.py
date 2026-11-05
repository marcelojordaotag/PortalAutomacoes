import os
from pathlib import Path

import boto3
from decouple import Config, RepositoryEnv

APP_ENV = os.getenv("APP_ENV")
if not APP_ENV:
    raise RuntimeError("APP_ENV não definido (local | hom | prd)")

APP_ENV = APP_ENV.lower()
if APP_ENV not in {"local", "hom", "prd"}:
    raise RuntimeError(f"APP_ENV inválido: {APP_ENV}")

diretorio_base = Path(__file__).resolve().parents[2]
arquivo_env = diretorio_base / "env" / f".env.{APP_ENV}"
configuracao_env = Config(RepositoryEnv(str(arquivo_env)))

for chave, valor in configuracao_env.repository.data.items():
    if chave not in os.environ:
        os.environ[chave] = valor

# Segredos de uso local que não vêm de variável do SO: arquivo fora do git, só no ambiente local
arquivo_segredo = diretorio_base / "env" / ".env.segredo"
if APP_ENV == "local" and arquivo_segredo.exists():
    for chave, valor in Config(RepositoryEnv(str(arquivo_segredo))).repository.data.items():
        if chave not in os.environ:
            os.environ[chave] = valor

diretorio_dados = Path(os.getenv("PORTAL_DADOS") or diretorio_base / "dados")


def obterDiretorioDados(nm_app):
    dir_app = diretorio_dados / nm_app
    dir_app.mkdir(parents=True, exist_ok=True)
    return dir_app


def obterVariavel(nm_variavel):
    """Lê uma variável de ambiente já carregada pelo config_ambiente (os .env e o Parameter Store)."""
    return os.getenv(nm_variavel, "")


def carregarSegredosParameterStore():
    cliente_ssm = boto3.client("ssm", region_name=os.getenv("AWS_REGIAO"))
    path_parametros = os.getenv("AWS_PARAMETER_STORE_PATH")
    paginador = cliente_ssm.get_paginator("get_parameters_by_path")

    total_parametros = 0
    for pagina in paginador.paginate(Path=path_parametros, Recursive=False, WithDecryption=True):
        for parametro in pagina["Parameters"]:
            nm_parametro = parametro["Name"].split("/")[-1]
            os.environ[nm_parametro] = parametro["Value"]
            total_parametros += 1

    if total_parametros == 0:
        raise RuntimeError(f"Nenhum parâmetro encontrado em {path_parametros}")

    print(f"Parameter Store: {total_parametros} parâmetros carregados de {path_parametros}")


def validarVariaveisObrigatorias():
    lista_obrigatorias = ["EMAIL_PARA_SOLICITACOES", "EMAIL_CC_SOLICITACOES", "API_PRC_URL", "BOLETADOR_PRC_URL",
                         "OFFSHORE_BKO_PASTA_HISTORICO", "OFFSHORE_BKO_ARQUIVO_MODELO"]
    if APP_ENV in {"hom", "prd"}:
        lista_obrigatorias.append("PORTAL_SEGREDO")
    lista_ausentes = [nm_variavel for nm_variavel in lista_obrigatorias if not os.getenv(nm_variavel)]
    lista_pendentes = [nm_variavel for nm_variavel in lista_obrigatorias if os.getenv(nm_variavel, "").startswith("DEFINIR-")]
    if lista_ausentes or lista_pendentes:
        raise RuntimeError("Variáveis obrigatórias ausentes, vazias ou pendentes: " + ", ".join(lista_ausentes + lista_pendentes))


def inicializarAmbiente():
    if APP_ENV in {"hom", "prd"}:
        carregarSegredosParameterStore()
    validarVariaveisObrigatorias()
