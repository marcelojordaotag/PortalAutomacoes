"""Busca os dados das carteiras na API Britech e grava o Relatorio_Rentabilidade.xlsx + os extratos de conta corrente.

Uso na linha de comando (le os IDs de ids_cliente.xlsx):
    python -m app.api.api_britech

Uso pela página (pagina.py): o app escolhe os IDs e o periodo e chama buscar_dados().
"""
import os
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

from app.ambiente.config_ambiente import obterDiretorioDados

BASE_URL = os.environ.get("API_PRC_URL", "")

USUARIO = os.environ.get("API_PRC_USUARIO", "")
SENHA = os.environ.get("API_PRC_SENHA", "")

PASTA = obterDiretorioDados("britech")
ARQUIVO_IDS = PASTA / "ids_cliente.xlsx"
ARQUIVO_SAIDA = PASTA / "Relatorio_Rentabilidade.xlsx"
PASTA_EXTRATOS = PASTA / "extratos"
DATA_INICIO_PADRAO = "2026-07-31"
DATA_FIM_PADRAO = "2026-08-31"

# Historico de cotas para o Monitor de cotas (precisa de bem mais dias que a conferencia: as janelas de 252 e 126
# dias so comecam a classificar depois de metade da janela)
ARQUIVO_HISTORICO = PASTA / "Historico_Cotas.csv"
HISTORICO_DIAS_PADRAO = 730  # 2 anos antes da data final
COLUNAS_HISTORICO = ["Data", "IdCarteira", "CotaBruta", "PLFechamento", "QuantidadeFechamento"]

# Tempo limite das chamadas (segundos): (conectar, esperar resposta). Sem isso, uma API que trava
# deixa o programa esperando para sempre (no app, o botao "Buscar na API" ficaria preso).
TIMEOUT = (15, 120)
TIMEOUT_EXTRATO = (15, 180)  # o extrato e um arquivo e demora mais


class ErroAPI(RuntimeError):
    """A API nao respondeu a tempo ou nao foi possivel conecta-la. A mensagem ja e amigavel para mostrar ao usuario."""


class AtlasPasAPI:
    def __init__(self, base_url, usuario, senha):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.session.auth = (usuario, senha)
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })

    def close(self):
        """Fecha as conexoes abertas da sessao."""
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, *excecao):
        self.close()

    def _executarGet(self, endpoint, params):
        url = f"{self.base_url}/{endpoint}"
        try:
            print(f"Consultando: {url} {params}")
            resposta_servidor = self.session.get(url, params=params, timeout=TIMEOUT)

            if resposta_servidor.status_code == 401:
                print("❌ ERRO: Autenticação falhou.")
                return None

            resposta_servidor.raise_for_status()
            return resposta_servidor.json()

        except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError) as excecao:
            raise ErroAPI(f"Não consegui conectar na API ({endpoint}). Confira a rede e o acesso. Detalhe: {excecao}") from None
        except requests.exceptions.Timeout:
            raise ErroAPI(f"A API não respondeu em {TIMEOUT[1]} segundos ({endpoint}). Tente de novo daqui a pouco "
                          "ou use um período menor.") from None
        except Exception as excecao:
            print(f"❌ Erro na requisição: {excecao}")
        return None

    def baixarExtratoContaCorrente(self, id_cliente, data_inicio, data_fim, caminho, periodo=1):
        """Baixa o extrato de conta corrente em Excel (a API devolve o arquivo, nao JSON). periodo=1 e 'Mes'."""
        url = f"{self.base_url}/api/Relatorio/RelatorioExtratoContaCorrente"
        params = {"IdCliente": id_cliente, "DataInicio": data_inicio, "DataFim": data_fim,
                  "Periodo": periodo, "TipoArquivo": "Excel"}
        try:
            print(f"Consultando: {url} {params}")
            resposta_servidor = self.session.get(url, params=params, timeout=TIMEOUT_EXTRATO)
            resposta_servidor.raise_for_status()
            with open(caminho, "wb") as arquivo_destino:
                arquivo_destino.write(resposta_servidor.content)
            return True
        except Exception as excecao:
            print(f"❌ Erro ao baixar extrato: {excecao}")
        return False

    def buscarRentabilidadeAtivoDia(self, id_cliente, data_inicio, data_fim):
        return self._executarGet("api/Rentabilidade/BuscaRentabAtivo_Dia",{"idCliente": id_cliente, "dataInicio": data_inicio, "dataFim": data_fim})

    def buscarRentabilidadeClasse(self, id_cliente, data_inicial, data_final):
        return self._executarGet("api/Rentabilidade/BuscaRentabClasse_PeriodoNaoExplodida",{"IdCliente": id_cliente, "DataInicial": data_inicial, "DataFinal": data_final})

    def buscarRentabilidadeSubclasse(self, id_cliente, data_inicial, data_final):
        return self._executarGet("api/Rentabilidade/BuscaRentabSubClasse_PeriodoNaoExplodida",{"IdCliente": id_cliente, "DataInicial": data_inicial, "DataFinal": data_final})

    def buscarRentabilidadeEstrategia(self, id_cliente_proprietario, data_inicio, data_fim):
        return self._executarGet("api/Rentabilidade/BuscaRentabEstrategia_PeriodoNaoExplodida",{"idClienteProprietario": id_cliente_proprietario, "dataInicio": data_inicio, "dataFim": data_fim})

    def buscarHistoricoCotaDia(self, id_cliente, data_inicio, data_fim):
        """Cota, PL e quantidade de cotas por dia (mostra se houve entrada/saida de cotas)."""
        return self._executarGet("api/Fundo/BuscaHistoricoCotaDia",{"idCarteira": id_cliente, "dataInicio": data_inicio, "dataFim": data_fim})

    def buscarOperacoesCotista(self, id_cliente, data_inicio, data_fim):
        """Aplicacoes e resgates de cotas da carteira no periodo (sem precisar do ID do cotista)."""
        return self._executarGet("api/Fundo/OperacaoCotistaAnalitico_PorCarteiraPeriodo",{"IdsCarteiras": id_cliente, "DataInicio": data_inicio, "DataFim": data_fim})


def lerIds(arquivo=ARQUIVO_IDS):
    """IDs da coluna id_cliente da planilha (sem repeticao). Lista vazia se a planilha nao existir."""
    arquivo = Path(arquivo)
    if not arquivo.exists():
        return []
    return (pd.read_excel(arquivo, dtype=str)["id_cliente"]
            .dropna().str.strip().drop_duplicates().tolist())


def montarConsultas(api):
    """aba do Excel -> consulta da API. As duas ultimas explicam divergencias de PL (movimentacao de cotistas)."""
    return {
        "Ativo": api.buscarRentabilidadeAtivoDia,
        "Classe": api.buscarRentabilidadeClasse,
        "SubClasse": api.buscarRentabilidadeSubclasse,
        "Estrategia": api.buscarRentabilidadeEstrategia,
        "HistCota": api.buscarHistoricoCotaDia,
        "OpCotista": api.buscarOperacoesCotista,
    }


def _executarHistorico(clientes, data_inicio, data_fim, arquivo_saida, api, progresso):
    """Uma chamada por carteira (BuscaHistoricoCotaDia) e um CSV com Data, IdCarteira, CotaBruta, PL e quantidade de cotas."""
    quadros, sem_dados = [], []
    for ordem_item, cliente in enumerate(clientes):
        if progresso:
            progresso(ordem_item / len(clientes), f"Carteira {cliente}: histórico de cotas")
        dados = api.buscarHistoricoCotaDia(cliente, data_inicio, data_fim)
        if dados:
            df = pd.DataFrame(dados)
            for coluna in COLUNAS_HISTORICO:
                if coluna not in df.columns:
                    df[coluna] = None
            quadros.append(df[COLUNAS_HISTORICO])
        else:
            print(f"⚠️ Sem histórico de cotas: carteira {cliente}")
            sem_dados.append(cliente)
    if not quadros:
        raise RuntimeError("A API não devolveu histórico de cotas para nenhuma carteira.")
    historico = pd.concat(quadros, ignore_index=True)
    historico["Data"] = pd.to_datetime(historico["Data"]).dt.strftime("%Y-%m-%d")
    arquivo_saida.parent.mkdir(parents=True, exist_ok=True)
    temporario = arquivo_saida.with_name(arquivo_saida.stem + ".tmp.csv")
    historico.to_csv(temporario, index=False)
    try:
        os.replace(temporario, arquivo_saida)
    except PermissionError:
        temporario.unlink(missing_ok=True)
        raise PermissionError(f"Não consegui gravar {arquivo_saida.name}. Feche o arquivo e tente de novo.")
    return {"arquivo": str(arquivo_saida), "linhas": len(historico),
            "carteiras": [id_carteira for id_carteira in clientes if id_carteira not in sem_dados], "sem_dados": sem_dados}


def buscarHistoricoCotas(clientes, data_inicio, data_fim, arquivo_saida=ARQUIVO_HISTORICO,
                           api = None,
                           progresso = None):
    """Busca so o historico de cotas (para o Monitor de cotas). Mesmas regras de erro e de fechamento de buscar_dados()."""
    clientes = list(dict.fromkeys(str(id_carteira).strip() for id_carteira in clientes if str(id_carteira).strip()))
    if not clientes:
        raise ValueError("Nenhuma carteira informada.")
    data_inicio, data_fim = str(data_inicio), str(data_fim)
    if data_inicio >= data_fim:
        raise ValueError("A data inicial precisa ser anterior à data final.")
    propria = api is None
    api = api or AtlasPasAPI(BASE_URL, USUARIO, SENHA)
    try:
        return _executarHistorico(clientes, data_inicio, data_fim, Path(arquivo_saida), api, progresso)
    finally:
        if propria:
            api.close()


def buscarDados(clientes, data_inicio, data_fim, arquivo_saida=ARQUIVO_SAIDA, pasta_extratos=PASTA_EXTRATOS,
                 api = None,
                 progresso = None,
                 historico_inicio=None, arquivo_historico=ARQUIVO_HISTORICO):
    """Busca as carteiras na API e grava o Excel e os extratos.

    clientes          - lista de IDs
    data_inicio       - dia-base ('AAAA-MM-DD' ou date); data_fim - ultimo dia
    progresso         - funcao opcional (fracao de 0 a 1, texto) para mostrar andamento
    historico_inicio  - se informado, busca tambem o historico de cotas desde essa data (Monitor de cotas)
    Levanta ValueError (entrada invalida), RuntimeError/ErroAPI (API sem dados, sem resposta ou fora do ar) ou
    PermissionError (Excel aberto).
    Retorna {'arquivo', 'abas', 'clientes', 'sem_dados': {aba: [ids]}, 'extratos_falhos': [ids], 'historico': dict|None}.
    O arquivo antigo so e substituido se tudo der certo. A conexao com a API e fechada no fim, mesmo se der erro.
    Se so o historico falhar, a conferencia ja gravada e mantida e o erro vem em resultado['historico']['erro'].
    """
    clientes = list(dict.fromkeys(str(id_carteira).strip() for id_carteira in clientes if str(id_carteira).strip()))
    if not clientes:
        raise ValueError("Nenhuma carteira informada.")
    data_inicio, data_fim = str(data_inicio), str(data_fim)
    if data_inicio >= data_fim:
        raise ValueError("A data inicial precisa ser anterior à data final.")
    if historico_inicio:
        historico_inicio = str(historico_inicio)
        if historico_inicio >= data_fim:
            raise ValueError("O início do histórico do monitor precisa ser anterior à data final.")

    propria = api is None  # so fecha a sessao se foi criada aqui (quem passa a sua cuida dela)
    api = api or AtlasPasAPI(BASE_URL, USUARIO, SENHA)
    try:
        return _executarBusca(clientes, data_inicio, data_fim, Path(arquivo_saida), Path(pasta_extratos), api, progresso,
                               historico_inicio, Path(arquivo_historico))
    finally:
        if propria:
            api.close()


def _executarBusca(clientes, data_inicio, data_fim, arquivo_saida, pasta_extratos, api,
                    progresso, historico_inicio=None, arquivo_historico = ARQUIVO_HISTORICO):
    consultas = montarConsultas(api)
    total = len(clientes) * (len(consultas) + 1 + (1 if historico_inicio else 0))
    feitos = 0

    def avisar(texto):
        if progresso:
            progresso(min(feitos / total, 1.0), texto)

    resultados = {aba: [] for aba in consultas}
    sem_dados = {aba: [] for aba in consultas}

    for cliente in clientes:
        print(f"\n=== Carteira {cliente} ===")
        for aba, consulta in consultas.items():
            avisar(f"Carteira {cliente}: {aba}")
            dados = consulta(cliente, data_inicio, data_fim)
            if dados:
                df = pd.DataFrame(dados)
                df.insert(0, "id_cliente_consulta", cliente)
                resultados[aba].append(df)
            else:
                # OpCotista vazio e normal: significa que nao houve aplicacao nem resgate de cotas
                print(f"⚠️ Sem dados: {aba} / carteira {cliente}")
                sem_dados[aba].append(cliente)
            feitos += 1

    # Extrato de conta corrente de cada carteira (usado pelo converter.py na ponte da diferenca)
    pasta_extratos.mkdir(parents=True, exist_ok=True)
    extratos_falhos = []
    for cliente in clientes:
        avisar(f"Carteira {cliente}: extrato de conta corrente")
        ok = api.baixarExtratoContaCorrente(
            cliente, data_inicio, data_fim, pasta_extratos / f"ReportExtratoContaCorrente_{cliente}.xlsx")
        if not ok:
            extratos_falhos.append(cliente)
        feitos += 1

    abas = [aba for aba, dfs in resultados.items() if dfs]
    if "Ativo" not in abas:
        raise RuntimeError("A API não devolveu dados de ativos para nenhuma carteira. Confira os IDs, o período e o acesso.")

    # Grava num arquivo temporario e so troca no fim: se o Excel estiver aberto, o arquivo antigo fica intacto
    avisar("Gravando o Excel")
    temporario = arquivo_saida.with_name(arquivo_saida.stem + ".tmp.xlsx")
    with pd.ExcelWriter(temporario, engine="openpyxl") as escritor:
        for aba in abas:
            pd.concat(resultados[aba], ignore_index=True).to_excel(escritor, sheet_name=aba, index=False)
            print(f"✅ Aba '{aba}' gerada.")
    try:
        os.replace(temporario, arquivo_saida)
    except PermissionError:
        temporario.unlink(missing_ok=True)
        raise PermissionError(f"Não consegui gravar {arquivo_saida.name}. Feche o arquivo no Excel e tente de novo.")

    # Historico para o Monitor de cotas: depois da conferencia gravada, para nao perde-la se so esta etapa falhar
    historico = None
    if historico_inicio:
        base = feitos

        def progressoHistorico(fracao, texto):
            if progresso:
                progresso(min((base + fracao * len(clientes)) / total, 1.0), texto)

        try:
            historico = _executarHistorico(clientes, historico_inicio, data_fim, arquivo_historico, api, progressoHistorico)
        except (RuntimeError, ValueError, PermissionError) as excecao:
            historico = {"erro": str(excecao)}

    if progresso:
        progresso(1.0, "Concluído")
    return {"arquivo": str(arquivo_saida), "abas": abas, "clientes": clientes, "sem_dados": sem_dados,
            "extratos_falhos": extratos_falhos, "historico": historico}


def main():
    clientes = lerIds()
    print(f"{len(clientes)} carteiras lidas de {ARQUIVO_IDS}")
    historico_inicio = (date.fromisoformat(DATA_FIM_PADRAO) - timedelta(days=HISTORICO_DIAS_PADRAO)).isoformat()
    try:
        resultado = buscarDados(clientes, DATA_INICIO_PADRAO, DATA_FIM_PADRAO, historico_inicio=historico_inicio)
    except (ValueError, RuntimeError, PermissionError) as excecao:  # mensagem clara em vez de um traceback longo
        print(f"\n❌ {excecao}")
        raise SystemExit(1)
    print(f"\n🚀 Arquivo '{resultado['arquivo']}' salvo.")
    resultado_historico = resultado["historico"]
    if resultado_historico and "erro" in resultado_historico:
        print(f"⚠️ Histórico de cotas (monitor) não gravado: {resultado_historico['erro']}")
    elif resultado_historico:
        print(f"📈 Histórico de cotas: {resultado_historico['linhas']} linhas em '{resultado_historico['arquivo']}'.")


if __name__ == "__main__":
    main()
