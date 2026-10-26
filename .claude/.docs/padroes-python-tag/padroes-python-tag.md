---
name: padroes-python-tag
description: >-
  Padrões de arquitetura e convenções dos projetos Python da TAG Invest — sistemas de
  processamento financeiro nos formatos ETL/Batch, API REST (Flask) e Dashboard (Streamlit).
  Use SEMPRE que for iniciar um novo projeto Python da TAG, criar a estrutura de pastas
  (app/ambiente, app/database, app/api, app/seguranca, app/utilitarias), escrever funções,
  variáveis ou classes, configurar ambiente (APP_ENV, python-decouple, AWS Parameter Store), abrir conexões
  de banco (MySQL), fazer chamadas HTTP, integrar Google Drive/Sheets,
  tratar exceções, registrar processamento em banco, montar o requirements.txt, ou revisar se
  um código segue o padrão da casa. Vale mesmo quando o usuário não cita "padrão" explicitamente
  — qualquer trabalho Python nesses projetos deve seguir estas convenções.
---

# Padrões Python da TAG Invest

Referência das convenções comuns a **todos** os projetos Python da TAG. Ao trabalhar em qualquer
projeto Python, siga estritamente estas diretrizes.

Caso existe um projeto na pasta, verifique se está de acordo com as regras estabelecidas neste documento, caso não esteja,
ajuste para atender aos padrões — e siga [Adaptação de Projeto Existente ao
Padrão](#adaptação-de-projeto-existente-ao-padrão), que trata da remoção do que ficou para trás.

---

## Regras Inegociáveis de Nomenclatura

Estas regras se aplicam **sem exceção** — inclusive em variáveis temporárias, parâmetros de função e variáveis de loop.

| Elemento | Padrão | Exemplo |
|----------|--------|---------|
| Funções | camelCase em português | `processarCargaXML`, `enviarEmailNotificacao` |
| Variáveis | snake_case em português + prefixo de domínio | `nm_fundo`, `vl_pl_carteira`, `dt_posicao` |
| Classes | PascalCase | `ControleAcessoErro`, `ProcessamentoErro` |
| Arquivos/módulos | snake_case | `config_ambiente.py`, `db.py` |

**Nunca use inglês** para nomear funções, variáveis ou classes internas — nem em variáveis genéricas como `result`, `data`, `value`, `item`, `response`.

**Nunca use snake_case em funções** e **nunca use camelCase em variáveis**.

### ✅ Correto vs ❌ Incorreto

```python
# FUNÇÕES
def carregarDados():          # ✅ camelCase em português
def load_data():              # ❌ inglês + snake_case
def LoadData():               # ❌ inglês + PascalCase
def carregar_dados():         # ❌ snake_case (reservado para variáveis)

# VARIÁVEIS
nm_fundo = ""                 # ✅ snake_case com prefixo de domínio
fund_name = ""                # ❌ inglês
fundoNome = ""                # ❌ camelCase (reservado para funções)
nome_fundo = ""               # ❌ sem prefixo de domínio

# VARIÁVEIS TEMPORÁRIAS E DE LOOP (a IA frequentemente erra aqui)
for registro in lista_cotas:              # ✅
    vl_cota = registro["vl_cota"]         # ✅

for item in result:                       # ❌ inglês
    value = item["vl_cota"]              # ❌ inglês

# PARÂMETROS DE FUNÇÃO
def processarFundo(nm_fundo, dt_referencia, vl_pl):   # ✅
def processarFundo(fund_name, ref_date, pl_value):    # ❌ inglês
```

---

## Visão Geral

Os projetos Python da TAG são sistemas de processamento financeiro que incluem:
- **ETL / Batch**: carga e transformação de posições, cotas e XMLs
- **APIs REST**: serviços internos com Flask
- **Dashboards**: interfaces interativas com Streamlit

Todos os projetos seguem a mesma estrutura, convenções de código e mecanismo de configuração de ambiente.

---

## Tipo de Projeto — Quando usar cada template

Ao iniciar um projeto Python, identifique o tipo antes de criar a estrutura de pastas:

| Tipo | Quando usar | Ponto de entrada |
|------|-------------|-----------------|
| **Dashboard (Streamlit)** | Interface interativa para visualização e consulta de dados por usuários internos | `main.py` ou `app.py` executado via `streamlit run` |
| **ETL / Batch** | Processamento agendado, carga de dados, geração de arquivos, envio de e-mails | `main.py` executado via agendador ou terminal |
| **API REST (Flask)** | Exposição de endpoints para consumo por outros sistemas ou frontends | `main.py` inicializa o app Flask |

> Projetos híbridos (ex.: ETL + dashboard) devem ser separados em dois projetos distintos — nunca misture Flask ou Streamlit com lógica de batch no mesmo `main.py`.

## Versão do Python

**Todos os projetos devem usar Python 3.10.9.**

**Todo projeto — ETL/Batch, API REST e Streamlit — é obrigatório criar ambiente virtual (`venv`).**
Nunca instale dependências no Python global da máquina. Ver [Ambiente Virtual](#ambiente-virtual-obrigatório-em-todos-os-projetos).

Para projetos Streamlit, use também **Streamlit 1.43.0**.

---

## Ambiente Virtual (obrigatório em todos os projetos)

O `venv` fica **dentro da pasta do projeto, um nível acima da pasta que contém o código** —
ou seja, `venv/` e a pasta de código são irmãs dentro da pasta do projeto.
**Nunca crie o `venv` dentro da pasta do código.**

Se a pasta do projeto já tiver o código solto na raiz, crie uma nova pasta e mova todo o código
para dentro dela antes de criar o `venv`.

A criação do `venv` deve acontecer **automaticamente** ao iniciar qualquer projeto novo:

```bash
# Na raiz da pasta do projeto, um nível acima da pasta de código
python -m venv venv

# Ativar (Windows)
venv\Scripts\activate

# Instalar dependências
pip install -r codigo-do-projeto/requirements.txt
```

```
pasta-do-projeto/                    # Pasta raiz do projeto
├── venv/                            # Ambiente virtual — irmão da pasta de código
└── codigo-do-projeto/               # Todo o código do projeto fica aqui
```

---

## Estrutura Padrão de Projeto

```
nome-do-projeto/
├── main.py                          # Ponto de entrada da aplicação
├── requirements.txt                 # Dependências
├── env/
│   ├── .env.local                   # Variáveis de ambiente local
│   ├── .env.hom                     # Variáveis de ambiente homologação
│   └── .env.prd                     # Variáveis de ambiente produção
└── app/
    ├── ambiente/
    │   └── config_ambiente.py       # Inicialização e configuração do ambiente
    ├── database/
    │   └── db.py                    # Conexão e queries MySQL
    ├── api/
    │   └── api_*.py                 # Clientes para APIs externas
    ├── processamento_*.py           # Lógica de negócio e processamento
    ├── gera_*.py                    # Geração de relatórios e arquivos
    ├── envia_*.py                   # Envio de e-mails e arquivos
    ├── seguranca/
    │   └── controle_acesso.py       # Controle de acesso e JWT (projetos web)
    ├── assets/                      # Arquivos de apoio (parametrização, de-para, layout, imagens)
    └── utilitarias/                 # Funções auxiliares reutilizáveis
```

Arquivos de apoio de que o projeto depende para rodar — `.json` de parametrização, `.csv` de de-para,
`.xml` de layout, planilha modelo, imagens — ficam em `app/assets/` e **são versionados**. Entrada e
saída de processamento (extratos, posições, bases exportadas) ficam em `dados/`, que nunca vai para o
repositório.

Para projetos **Flask** (APIs REST), adicionar dentro de `app/`:

```
app/
├── __init__.py                      # Inicialização do app Flask
└── rotas/                           # Definição de rotas/endpoints
```

Para projetos **Streamlit** (dashboards), ver seção específica abaixo.

---

## Projetos Streamlit — Configurações Específicas

### Estrutura de pastas

Como em todos os projetos, o **ambiente virtual** (`venv`) é obrigatório e fica na raiz da pasta do projeto, **um nível acima da pasta de código**. **Nunca crie o `venv` dentro da pasta do código.**

```
pasta-do-projeto/                    # Pasta raiz do projeto
├── venv/                            # Ambiente virtual — irmão da pasta de código
└── codigo-do-projeto/               # Todo o código do projeto fica aqui
    ├── main.py
    ├── requirements.txt
    ├── env/
    │   ├── .env.local
    │   ├── .env.hom
    │   └── .env.prd
    ├── app/
    │   ├── ambiente/
    │   │   └── config_ambiente.py
    │   ├── database/
    │   │   └── db.py
    │   ├── consultas/               # Módulos de consulta de dados
    │   ├── servicos/                # Serviços e integrações
    │   └── assets/                  # Imagens e arquivos estáticos
    └── .streamlit/
        └── config.toml              # Configuração de tema
```

### Tema padrão TAG — `.streamlit/config.toml`

```toml
[theme]
primaryColor="#F63366"
backgroundColor="#E6E4DB"
secondaryBackgroundColor="#F0F2F6"
textColor="#630D24"
font="serif"
```

---

## Adaptação de Projeto Existente ao Padrão

Adaptar um projeto que já existe **não é acrescentar a estrutura nova ao lado da antiga** — é
substituí-la. A migração só está concluída quando a pasta do projeto contém a estrutura padrão e
**nada além dela**. Deixar a organização anterior convivendo com a nova é o pior dos dois mundos:
dobra o que precisa ser lido, cria dúvida sobre qual arquivo está no ar e faz um `import` antigo
continuar funcionando por acidente.

### Roteiro

1. **Mapear** tudo que existe na pasta hoje, arquivo por arquivo, e decidir para onde cada coisa vai:
   absorvida na estrutura nova, ou descartada.
2. **Migrar** o conteúdo para a estrutura padrão (`main.py`, `app/`, `env/`, `requirements.txt`).
3. **Validar** que a aplicação sobe e roda a partir da estrutura nova — sem isso, não apague nada.
4. **Salvar a versão** com a estrutura nova já funcionando. É esse commit que torna a limpeza
   reversível: o que for apagado depois continua recuperável pelo histórico do Git.
5. **Excluir** de fato o que sobrou (ver lista abaixo).
6. **Conferir a pasta** no fim, listando o conteúdo, e comparar com a estrutura padrão. Se aparecer
   algo que não está na estrutura, ou ele tem uma justificativa clara, ou sai.

### O que costuma ficar para trás

- pastas de código da organização anterior — `src/`, `scripts/`, `utils/`, `lib/`, `codigo/`
- pontos de entrada antigos — `app.py`, `run.py`, `executa.py`, `index.py`, duplicando o `main.py`
- **arquivos `.bat`** — `executar.bat`, `iniciar.bat`, `run.bat`, atalhos de duplo clique. Removidos
  sempre, sem exceção: a execução passa a ser pelo `venv` do projeto (`python -m streamlit run
  main.py`, `python main.py`) ou por um launcher em Python
- configuração antiga — `config.py`, `settings.py`, `constantes.py`, `.env` solto na raiz (fora de `env/`)
- `venv/` criado dentro da pasta do código (o correto é um nível acima)
- `requirements-dev.txt`, `requirements_old.txt`, `Pipfile`, `poetry.lock`, `environment.yml`
- `__init__.py` e `__pycache__/`
- notebooks de rascunho (`.ipynb`), arquivos de teste manual (`teste.py`, `temp.py`)
- `README.md`, `Dockerfile`, `.flake8`, `setup.cfg` e afins gerados por outro padrão
- qualquer pasta com nome de arquivamento — `_old`, `backup`, `v1`, `antigo`, `nao_usar`

### Regras da exclusão

- **Só apague depois de validar e versionar.** A ordem é sempre: funciona → commit → limpa.
- **Nunca renomeie para "arquivar".** Criar `main_old.py` ou `src_backup/` não é limpeza, é
  exatamente o entulho que esta seção existe para evitar. O histórico do Git é o backup.
- **Nunca apague o que não foi entendido.** Se não ficou claro se um arquivo ainda é usado, ele não
  entra na exclusão automática — vai para a lista de confirmação.
- **Confirme antes de excluir**, numa única mensagem no fim, listando os caminhos e o motivo de cada
  um. Vale sobretudo para arquivo que não é código: planilha, CSV, XML de entrada, credencial,
  documento. Código órfão dá para deduzir; um `.xlsx` na raiz da pasta, não.
- **Fora da limpeza, sempre:** `.git/`, o `venv/` correto (irmão da pasta de código), arquivos de
  dados que o processo consome, credenciais locais (`service_account.json`) e qualquer coisa listada
  no `.gitignore` que não seja gerada pelo próprio código.

### Fechamento

Ao terminar, informe o que foi removido e o que ficou pendente de confirmação:

> *"Migração concluída — o projeto roda a partir da estrutura padrão. Removi `src/`, `config.py`,
> `app.py` (substituído pelo `main.py`) e o `venv/` que estava dentro da pasta do código.*
>
> *Ficaram 2 arquivos que prefiro não apagar sem confirmar: `base_fundos.xlsx` e `relatorio_2024.csv`
> na raiz. Nenhum dos dois é lido pelo código — são entrada manual ou sobra? Se forem sobra, apago."*

---

## Configuração de Ambiente

### Variável de ambiente obrigatória

```bash
APP_ENV=local   # local | hom | prd
```

### Padrão de `config_ambiente.py`

Os segredos vêm do **AWS Parameter Store**. A autenticação é pela **IAM role da EC2**
— a cadeia de credenciais padrão do boto3 resolve sozinha, sem access key em lugar nenhum.

```python
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
    # O bloco do recurso leva a sigla da área dona do banco (aqui, GST — Gestão)
    lista_obrigatorias = [
        "BANCO_GST_HOST",
        "BANCO_GST_NOME",
        "BANCO_GST_USUARIO",
        "BANCO_GST_SENHA",
    ]
    lista_ausentes = [nm_variavel for nm_variavel in lista_obrigatorias if not os.getenv(nm_variavel)]
    if lista_ausentes:
        raise RuntimeError("Variáveis obrigatórias ausentes ou vazias: " + ", ".join(lista_ausentes))


def inicializarAmbiente():
    if APP_ENV in {"hom", "prd"}:
        carregarSegredosParameterStore()
    validarVariaveisObrigatorias()
```

**Precedência resultante** (do mais forte ao mais fraco): variável real do SO → Parameter Store →
`env/.env.<ambiente>`. Isso permite mover qualquer variável do `.env` para o Parameter Store depois,
sem tocar em código.

`Recursive=False` espelha o comportamento do `spring.config.import` dos projetos Java. Se um dia
forem criados subpaths dentro do path do sistema, trocar para `True`.

**Fail-fast obrigatório:** todo projeto deve ter a sua `validarVariaveisObrigatorias()`, listando as
variáveis sem as quais a aplicação não funciona. O objetivo é falhar na inicialização com uma
mensagem clara, e não com um erro de conexão obscuro no meio do processamento.

### Chamada no `main.py`

```python
from app.ambiente.config_ambiente import inicializarAmbiente

inicializarAmbiente()
```

### Convenção de path no Parameter Store

```
/{ambiente}/{área}-{sistema}/{NOME_DA_VARIAVEL}
```

O `{ambiente}` é sempre `hom` ou `prd` (nunca `local` — local não lê do Parameter Store).

O `{área}` identifica a qual área pertence o sistema — use o slug da tabela de siglas abaixo.

O `{sistema}` nome da aplicação.

**Área e sistema formam um único segmento do path, unidos por hífen** — não são dois níveis
separados. O path tem, portanto, sempre e exatamente dois segmentos antes do nome da variável.

```
/hom/gestao-monitoramento-offshore/BANCO_GST_USUARIO
/hom/gestao-monitoramento-offshore/BANCO_GST_SENHA
/hom/rh-departamento-pessoal/BANCO_RH_USUARIO
/hom/rh-departamento-pessoal/BANCO_RH_SENHA
/prd/gestao-monitoramento-offshore/BANCO_GST_USUARIO
/prd/gestao-monitoramento-offshore/BANCO_GST_SENHA
/prd/rh-departamento-pessoal/BANCO_RH_USUARIO
/prd/rh-departamento-pessoal/BANCO_RH_SENHA
```

Os nomes dos parâmetros são **UPPER_SNAKE_CASE, idênticos aos nomes das variáveis de ambiente** que
alimentam — é o último segmento do path que vira a variável.

### Nome da variável: sigla da área no meio

Toda variável que descreve um recurso leva a **sigla da área dona do recurso** entre o recurso e o
atributo:

```
{RECURSO}_{SIGLA}_{ATRIBUTO}
```

```
BANCO_GST_HOST         # host do banco da Gestão
BANCO_GST_PORTA        # porta do banco da Gestão
BANCO_GST_NOME         # schema do banco da Gestão
BANCO_GST_USUARIO      # usuário do banco da Gestão
BANCO_GST_SENHA        # senha do banco da Gestão
BANCO_RH_SENHA         # senha do banco de Recursos Humanos
API_BTC_TOKEN          # token da API do Britech (Processamento)
```

A sigla é a da área **dona do recurso**, não a do sistema que o consome. É isso que permite um
sistema da Gestão que também lê o banco de RH declarar `BANCO_GST_SENHA` e `BANCO_RH_SENHA` no mesmo
path, sem colisão e com a origem de cada credencial legível no próprio nome.

**A sigla vale para o bloco todo do recurso**, sensível ou não — `BANCO_GST_HOST` junto de
`BANCO_GST_SENHA`. Manter o host sem sigla e a senha com sigla quebraria a leitura do bloco e
deixaria o host ambíguo no dia em que o sistema passar a acessar um segundo banco.

Variáveis que não pertencem a um recurso de área continuam sem sigla: `APP_ENV`, `AWS_REGIAO`,
`AWS_PARAMETER_STORE_PATH`, `SECRET_JWT`.

### Glossário de siglas de área

| Área | Slug do path | Sigla |
|------|-----------|-------|
| Gestão | `gestao`  | `GST` |
| Recursos Humanos | `rh`      | `RH` |
| Risco | `risco`   | `RSC` |
| Compliance | `compliance` | `CPL` |
| Backoffice | `backoffice` | `BKO` |
| Processamento | `processamento` | `PRC` |
| Financeiro | `financeiro` | `FIN` |
| Estruturados | `estruturados` | `ETR` |
| Marketing | `marketing` | `MKT` |
| Suporte Comercial | `suporte-comercial` | `SPC` |

Ao criar uma área nova, acrescente a linha aqui antes de cadastrar o primeiro parâmetro — o
glossário é a fonte da verdade da sigla, e renomear parâmetro no Parameter Store depois exige mexer
em código e em deploy.

### Tipo do parâmetro: `String` vs. `SecureString`

Nem tudo sob o path precisa ser criptografado. Só é `SecureString` o que é segredo de fato:

| Tipo de informação | Tipo no Parameter Store |
|--------------------|-------------------------|
| Senhas, tokens, chaves de API, secret JWT, access/secret key | `SecureString` |
| Usuários, URLs de conexão, e-mails remetentes, flags de habilitação | `String` |

Só os parâmetros `SecureString` exigem `kms:Decrypt`. O código não muda em função do tipo:
`get_parameters_by_path(..., WithDecryption=True)` lida transparentemente com uma mistura de
`String` e `SecureString` no mesmo path.

### O que vai no `.env` vs. variáveis de ambiente / Parameter Store

A regra é simples: **se o valor vazar, causa dano?**

| Tipo de informação | Onde armazenar |
|--------------------|----------------|
| Hosts, URLs, schemas, portas, paths, IDs de pasta | `.env.local` / `.env.hom` / `.env.prd` |
| Usuários de banco e de API | Variável de ambiente (local) ou Parameter Store como `String` (HOM/PRD) |
| Senhas, tokens, chaves de API, secret JWT | Variável de ambiente (local) ou Parameter Store como `SecureString` (HOM/PRD) |
| Região e path do Parameter Store | `.env.hom` / `.env.prd` (`AWS_REGIAO`, `AWS_PARAMETER_STORE_PATH`) |

**Usuários de banco são tratados como sensíveis** — nunca ficam em arquivo, mesmo não sendo senha.

**Desenvolvimento local:** as credenciais sensíveis são definidas diretamente como variáveis de
ambiente no sistema operacional — nunca gravadas em arquivo. No Windows, via `setx` (é preciso
reabrir o terminal para que valha).

**HOM / PRD:** não existe credencial de acesso ao Parameter Store para guardar — a IAM role da
instância resolve a autenticação.

**Os três `.env` são versionados** — `.env.local`, `.env.hom` e `.env.prd` entram no repositório.
Isso só é possível porque nenhum deles contém segredo: o que é sensível vive em variável de ambiente
do SO (local) ou no Parameter Store (HOM/PRD), e o que fica em arquivo é configuração. O ganho é que
quem clonar o projeto roda em qualquer ambiente sem remontar a configuração na mão, e o PR chega com
tudo preenchido.

A contrapartida é que **um valor sensível colado num `.env` vai para o GitHub**. A regra "nunca gravar
usuário ou senha em `.env`, nem no `.env.local`" deixa de ser preferência de organização e passa a ser
o que separa o segredo do repositório.

### Nunca inferir a que ambiente um valor pertence

Nunca copie um valor de um `.env` para outro por semelhança, nem reaproveite o que estava num arquivo
legado sem confirmar a que ambiente ele atendia.

O motivo é que o erro aqui é silencioso. Um host de PRD copiado para o `.env.hom` não quebra nada: a
aplicação sobe, conecta e processa — contra a base de produção, achando que está em homologação. Não
há exceção, log ou teste que acuse; a única pista é o dado real mudando onde não devia.

Para cada valor, a pergunta é sempre a mesma:

- de qual ambiente é este host / usuário / schema / path?
- existe endpoint separado para HOM, ou HOM aponta para o mesmo servidor de PRD de propósito?
- se o valor veio de um arquivo legado, qual ambiente aquele arquivo atendia?

Enquanto a resposta não for conhecida, **não preencha com o valor de outro ambiente**. Deixe um
placeholder que falhe na inicialização (`BANCO_{SIGLA}_HOST=DEFINIR-HOST-HOM`) e siga o trabalho —
falhar na largada é sempre melhor que apontar para o ambiente errado. **Quando perguntar** esses
valores está na seção abaixo.

> A divisão de responsabilidades entre área e TI (quem escreve código, quem cadastra parâmetro,
> quem aprova PR) está no `CLAUDE.md` (§ Quem faz o quê — área x TI). Aqui vale o resumo que importa
> para escrever código: **quem escreve qualquer valor dentro do repositório é sempre a área** — a TI
> não mexe em código nem em arquivo do projeto.

### Quando perguntar as credenciais e os valores de ambiente — no fim do desenvolvimento

**Nunca interrompa o início do trabalho para pedir host, usuário, senha, schema, token ou path de
credencial.** Na hora em que o projeto está sendo criado, quem pediu costuma não ter esses dados à
mão — são valores de infraestrutura, que ficam com a TI. Perguntar ali trava o desenvolvimento por um
dado que não é necessário para escrever o código.

Durante o desenvolvimento, portanto:

- crie os `env/.env.local`, `.env.hom` e `.env.prd` completos, mas com **placeholder no formato
  `DEFINIR-<VARIAVEL>-<AMBIENTE>`** em tudo que não estiver confirmado;
- **não comente a linha do placeholder** — o próprio `DEFINIR-` já diz que o valor está pendente. A
  explicação de o que falta e de quem vem entra na descrição do commit, não no `.env`;
- garanta que a variável esteja em `validarVariaveisObrigatorias()`, para que o placeholder derrube a
  aplicação na inicialização em vez de virar uma conexão errada;
- **siga e conclua todo o resto do trabalho** sem depender desses valores.

**No fim do desenvolvimento, levante as pendências de uma só vez.** Liste cada valor que ficou como
placeholder, diga de qual ambiente ele é e onde vai morar (arquivo, variável do SO ou Parameter
Store), e pergunte se a pessoa tem os valores agora. Exemplo:

> *"Terminei o desenvolvimento. Ficaram 3 dados de acesso pendentes — você já tem esses valores?*
> - *host do banco de homologação (`BANCO_GST_HOST` no `env/.env.hom`)*
> - *usuário do banco (`BANCO_GST_USUARIO`) — vai como variável de ambiente no seu computador, não em
    >   arquivo*
> - *senha do banco (`BANCO_GST_SENHA`) — mesma coisa aqui, e na AWS a TI cadastra o parâmetro para
    >   HOM e PRD*
>
> *Os dois últimos não travam nada: são do Parameter Store e a TI cadastra na hora de subir. Já o host
> precisa estar no `.env.hom` antes do PR — se você ainda não tiver, eu salvo a versão do jeito que
> está, com o placeholder, e retomamos quando o valor chegar."*

Regras dessa conversa final:

- **Uma pergunta só, com a lista toda.** Não pingue a pessoa uma vez por variável.
- **Nunca peça senha, token ou chave em texto no chat.** Passe o comando (`setx BANCO_{SIGLA}_SENHA
  ...`) para a própria pessoa executar, ou o caminho do Parameter Store para ela solicitar o cadastro
  à TI.
- **Nunca preencha um valor "provisório" com o de outro ambiente** para destravar o commit. É
  exatamente o erro silencioso descrito acima.

> A trava de abertura de PR com placeholder pendente, e o texto a usar para pedir o cadastro dos
> parâmetros à TI, estão em `padroes-github-tag.md` (§ Validações antes de abrir o PR).

### Comentários nos `.env` — só o inventário das variáveis sensíveis

O `.env` é arquivo de configuração, não documentação. **O único comentário permitido é um bloco no
fim do arquivo listando as variáveis sensíveis que não estão ali e de onde elas vêm** — em `.local`,
as variáveis de ambiente do SO; em `.hom` / `.prd`, os paths do Parameter Store injetados na
inicialização.

Esse bloco existe por um motivo prático: sem ele, quem abre o arquivo não tem como saber que
`BANCO_GST_USUARIO` e `BANCO_GST_SENHA` são esperados pela aplicação, já que não aparecem em lugar
nenhum. É um inventário — nome da variável e origem, nada mais.

**Não escreva no `.env`:**

- cabeçalho de bloco explicando a convenção de nomes (`# todo o bloco leva a sigla da área...`) — a
  convenção mora neste documento;
- justificativa de valor (`# aponta para a réplica de leitura de PRD, que é a base que o dashboard
  já consultava no arquivo legado`) — isso é história do projeto, vai no commit ou no PR;
- instrução de como definir a variável (`# no Windows, definir uma vez e reabrir o terminal: setx
  ...`) — o passo a passo é da conversa de entrega, não do arquivo;
- comentário em linha de placeholder `DEFINIR-` — o prefixo já é autoexplicativo;
- comentário repetindo o que a variável é (`# host do banco`) — o nome da variável já diz.

Na dúvida entre comentar e não comentar, **não comente**. Um `.env` de 12 linhas legível de uma vez
vale mais que um comentado linha a linha.

### Estrutura do `.env.local`

```env
APP_ENV=local

BANCO_GST_HOST=servidor-local.tag.com.br
BANCO_GST_PORTA=3306
BANCO_GST_NOME=gst_db

PATH_CREDENCIAIS_GOOGLE=C:/credenciais/service_account.json
EMAIL_DELEGACAO=sistema@tag.com.br

# Variáveis de ambiente do SO:
#   BANCO_GST_USUARIO
#   BANCO_GST_SENHA
#   SECRET_JWT
```

### Estrutura do `.env.hom`

```env
AWS_REGIAO=us-east-1
AWS_PARAMETER_STORE_PATH=/hom/gestao-monitoramento-offshore/

BANCO_GST_HOST=DEFINIR-BANCO_GST_HOST-HOM
BANCO_GST_PORTA=3306
BANCO_GST_NOME=DEFINIR-BANCO_GST_NOME-HOM

PATH_CREDENCIAIS_GOOGLE=/credenciais/service_account.json
EMAIL_DELEGACAO=sistema@tag.com.br

# Parameter Store:
#   /hom/gestao-monitoramento-offshore/BANCO_GST_USUARIO   String
#   /hom/gestao-monitoramento-offshore/BANCO_GST_SENHA     SecureString
#   /hom/gestao-monitoramento-offshore/SECRET_JWT          SecureString
```

### Estrutura do `.env.prd`

```env
AWS_REGIAO=us-east-1
AWS_PARAMETER_STORE_PATH=/prd/gestao-monitoramento-offshore/

BANCO_GST_HOST=servidor-prd.tag.com.br
BANCO_GST_PORTA=3306
BANCO_GST_NOME=gst_db

PATH_CREDENCIAIS_GOOGLE=/credenciais/service_account.json
EMAIL_DELEGACAO=sistema@tag.com.br

# Parameter Store:
#   /prd/gestao-monitoramento-offshore/BANCO_GST_USUARIO   String
#   /prd/gestao-monitoramento-offshore/BANCO_GST_SENHA     SecureString
#   /prd/gestao-monitoramento-offshore/SECRET_JWT          SecureString
```

Os exemplos acima usam a Gestão (`GST`, `gestao`) e o sistema `monitoramento-offshore`. Troque pela
sigla e pelo slug da área dona do recurso (ver [Glossário de siglas de
área](#glossário-de-siglas-de-área)) e pelo nome do sistema.

---

## Conexões de Banco de Dados

O arquivo de conexão fica em `app/database/db.py`.

### MySQL — `app/database/db.py`

> Troque `GST` pela sigla da área dona do banco (ver [Glossário de siglas de área](#glossário-de-siglas-de-área)).
> A sigla no exemplo abaixo não é placeholder para copiar literalmente.

```python
import os
from mysql.connector import connection

banco_db = None
banco_db_cursor = None

def iniciarConexaoBanco():
    global banco_db, banco_db_cursor
    banco_db = connection.MySQLConnection(
        user=os.getenv("BANCO_GST_USUARIO"),
        password=os.getenv("BANCO_GST_SENHA"),
        host=os.getenv("BANCO_GST_HOST"),
        database=os.getenv("BANCO_GST_NOME"),
    )
    banco_db_cursor = banco_db.cursor(buffered=True, dictionary=True)

def encerrarConexaoBanco():
    banco_db.close()
    banco_db_cursor.close()

def incluirProcessamento(id_servico, inicio_processamento, fim_processamento, ic_status, descricao):
    sql = """
    INSERT INTO tb_processamento (id_servico, dt_proc_inicio, dt_proc_fim, ic_status_processamento, ds_log_proc)
    VALUES (%s, %s, %s, %s, %s)
    """
    banco_db_cursor.execute(sql, (id_servico, inicio_processamento, fim_processamento, ic_status, descricao))
    banco_db.commit()
    return banco_db_cursor.lastrowid

def atualizarProcessamento(id_processamento, ic_status, descricao, horario_fim_proc):
    sql = """
    UPDATE tb_processamento
    SET ic_status_processamento=%s, ds_log_proc=%s, dt_proc_fim=%s
    WHERE id_processamento=%s
    """
    banco_db_cursor.execute(sql, (ic_status, descricao, horario_fim_proc, id_processamento))
    banco_db.commit()
```

### Execução de queries

```python
sql = "SELECT * FROM tabela WHERE id_campo = %s AND nm_campo = %s"
parametros = (id_valor, nm_valor)
cursor.execute(sql, parametros)
resultado = cursor.fetchall()
```

---

## Organização de Importações

Seguir a ordem: biblioteca padrão → terceiros → módulos do projeto.

```python
# 1. Biblioteca padrão
import os
import json
from datetime import datetime, timedelta
from pathlib import Path

# 2. Terceiros
import pandas as pd
import numpy as np
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 3. Google APIs
from google.oauth2 import service_account
from googleapiclient.discovery import build

# 4. Módulos do projeto
from app.ambiente.config_ambiente import inicializarAmbiente
from app.database import db
from app.api import api_externa
```

---

## Chamadas HTTP

### Padrão com retry

```python
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

session = requests.Session()
retry = Retry(connect=3, backoff_factor=0.5)
adapter = HTTPAdapter(max_retries=retry)
session.mount("http://", adapter)
session.mount("https://", adapter)

resposta = requests.request(
    "GET",
    url,
    auth=(os.getenv("API_USUARIO"), os.getenv("API_SENHA")),
    params=parametros,
)

if resposta.status_code == 200:
    dados = json.loads(resposta.text)
```

### Retry com tenacity

```python
from tenacity import retry, stop_after_attempt, wait_fixed

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
def chamarApiExterna(endpoint, parametros):
    resposta = requests.get(endpoint, params=parametros)
    resposta.raise_for_status()
    return resposta.json()
```

---

## Google Drive / Sheets

```python
from google.oauth2 import service_account
from googleapiclient.discovery import build

def obterServiceDrive():
    creds = service_account.Credentials.from_service_account_file(
        os.getenv("PATH_CREDENCIAIS_GOOGLE"),
        scopes=[
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/drive.file",
        ],
    )
    delegated = creds.with_subject(os.getenv("EMAIL_DELEGACAO"))
    return build("drive", "v3", credentials=delegated)

def obterServiceSheets():
    creds = service_account.Credentials.from_service_account_file(
        os.getenv("PATH_CREDENCIAIS_GOOGLE"),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    delegated = creds.with_subject(os.getenv("EMAIL_DELEGACAO"))
    return build("sheets", "v4", credentials=delegated)
```

---

## Tratamento de Exceções

```python
# Padrão geral: captura ampla com registro no banco
try:
    processarCargaXMLPosicao(lista_arquivos)
except Exception as erro:
    atualizarStatusProcessamento(id_proc, "❌", str(erro))

# Exceções de domínio com classe customizada
class ControleAcessoErro(Exception):
    pass

def verificarPermissao(id_acao, lista_acoes):
    if id_acao not in lista_acoes:
        raise ControleAcessoErro("Seu usuário não tem permissão para acessar esta funcionalidade.")

# JWT (projetos Flask/Streamlit)
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError, DecodeError

try:
    jwt.decode(token, key=os.getenv("SECRET_JWT"), algorithms="HS512")
except ExpiredSignatureError:
    print("Token JWT expirado")
except (InvalidTokenError, DecodeError):
    print("Token JWT inválido")
```

---

## Rastreamento de Processamento

Em vez de logging, os projetos registram o status de execução em tabela de banco de dados.

```python
from app.database import db
from datetime import datetime

def iniciarProcessamento(id_servico, data_inicio):
    return db.incluirProcessamento(id_servico, data_inicio, None, "A", None)

def concluirProcessamento(id_proc, icone, descricao):
    db.atualizarProcessamento(id_proc, icone, descricao, datetime.now())

# Uso no main.py
id_proc = iniciarProcessamento(ID_SERVICO, datetime.now())
try:
    executarProcessamento()
    concluirProcessamento(id_proc, "✅", "Processamento concluído com sucesso")
except Exception as erro:
    concluirProcessamento(id_proc, "❌", str(erro))
```

---

## Bibliotecas e Versões Padrão

> **Atenção:** `numpy==1.24.1` deve sempre constar no `requirements.txt`, mesmo que o projeto não importe numpy diretamente. O `pandas==1.5.3` foi compilado contra numpy 1.x — instalar numpy 2.x sem fixar a versão quebra a ABI e impede a importação do pandas com o erro `numpy.dtype size changed, may indicate binary incompatibility`.

```txt
# Dados
pandas==1.5.3
numpy==1.24.1

# Configuração
python-decouple==3.8

# AWS (Parameter Store)
boto3==1.34.162

# Banco de dados
mysql-connector-python==8.3.0

# HTTP
requests==2.32.3
urllib3==1.26.15
tenacity==9.1.2

# Google
google-api-python-client==2.85.0
google-auth==2.17.3

# Excel / planilhas
openpyxl==3.1.5
XlsxWriter==3.2.9

# XML
xmltodict==0.13.0
protobuf==3.20.3

# Auth
PyJWT==2.8.0

# Web (APIs REST)
Flask==3.0.3

# Dashboard
streamlit==1.43.0

# E-mail / HTML
pretty-html-table==0.9.16
```

---

## O que deve ser seguido

- Funções: **sempre camelCase em português** — ex: `processarCargaXML`, `enviarEmailNotificacao`, `obterFeriadosBrasil`
- Variáveis: **sempre snake_case em português com prefixo de domínio** — ex: `nm_fundo`, `vl_pl_carteira`, `dt_posicao`
- Variáveis sem prefixo de domínio: snake_case descritivo em português — ex: `lista_fundos`, `dict_parametros`, `total_registros`
- Nunca usar inglês em nomes de variáveis, funções ou classes — nem em variáveis temporárias (`resultado`, não `result`; `registro`, não `item`)
- Estrutura `app/` com os submódulos padrão
- Chamar `inicializarAmbiente()` no início de `main.py`
- Usar `python-decouple` para todas as variáveis de configuração
- Segredos no **AWS Parameter Store** (HOM/PRD) ou variável de ambiente do SO (local) — nunca em arquivo
- `.env` enxuto: só pares `VARIAVEL=valor` e **um único bloco de comentário no fim**, listando as variáveis sensíveis e sua origem (variáveis de ambiente do SO no `.local`; paths do Parameter Store no `.hom` e `.prd`)
- Desenvolver com placeholder `DEFINIR-<VARIAVEL>-<AMBIENTE>` e **pedir os dados de acesso só no fim do desenvolvimento**, numa pergunta única — sem travar o trabalho se a pessoa não souber
- Validar as variáveis obrigatórias na inicialização (`validarVariaveisObrigatorias()`), falhando cedo e com mensagem clara
- Conexões de banco com funções explícitas `iniciar*` e `encerrar*`
- Usar `print()` para acompanhamento de execução
- Registrar status de processamento no banco de dados
- Criar `venv` em **todos os projetos** (ETL/Batch, API REST e Streamlit), sempre na raiz da pasta do projeto, um nível acima da pasta de código
- Ao adaptar um projeto existente, **excluir as pastas e arquivos da organização anterior** depois de validar e versionar a estrutura nova — a pasta deve terminar com a estrutura padrão e nada além dela

## O que deve ser evitado

- ORMs como SQLAlchemy ou Django ORM
- `async`/`await` e frameworks assíncronos
- Type hints e anotações de tipo
- Configuração de linting (flake8, black, pylint, mypy)
- Frameworks de teste (pytest, unittest)
- Docker ou containerização
- Criar arquivos README.md ou documentação extra salvo solicitação explícita
- Importações relativas (usar sempre caminhos absolutos com prefixo `app.`)
- Nomes em inglês em qualquer elemento de código interno (`data`, `result`, `value`, `response`, `item`, `temp`, `flag`, etc.)
- Arquivos `__init__.py` — desnecessários desde Python 3.3 (namespace packages)
- Instalar dependências no Python global da máquina — sempre use o `venv` do projeto
- Criar o `venv` dentro da pasta do código — ele fica sempre um nível acima, na raiz da pasta do projeto
- Terminar uma adaptação com a estrutura antiga convivendo com a nova — `src/`, `config.py`, ponto de entrada duplicado, `venv/` no lugar errado
- Renomear para `_old` / `backup` / `v1` em vez de excluir — o histórico do Git é o backup
- Comentário no `.env` que não seja o inventário final das variáveis sensíveis — nada de cabeçalho de bloco, justificativa de valor, instrução de `setx` ou explicação do que a variável é
- HashiCorp Vault e a biblioteca `hvac` — substituídos pelo AWS Parameter Store
- Access key / secret key da AWS no código ou em arquivo — a autenticação é pela IAM role da EC2
- Gravar senha ou usuário de banco em `.env` — mesmo em `.env.local`
