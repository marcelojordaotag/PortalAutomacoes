# Portal de Automações | TAG Investimentos

Portal web interno que reúne as ferramentas de automação da área de operações (Backoffice). Cada ferramenta é uma página do portal, com a identidade visual da TAG, login próprio e um menu lateral. É feito em **Streamlit** e usa **MySQL** como banco, **Gmail** e **Google Drive** pela API do Google, e **Slack** para avisos.

## Ferramentas

| Ferramenta | Endereço | O que faz |
|---|---|---|
| **Solicitação de extratos** | `/extratos` | Monta e envia os e-mails de pedido de extratos aos cotistas (com revisão antes do envio), confere as respostas e salva os anexos no Drive, uma pasta por fundo. |
| **Mesa de Boletas** | `/boletas` | Concilia as boletas da TAG com a base da XP e mantém o quadro de controle de erros. |
| **Registro de Solicitações** | `/solicitacoes` | Conclusão das demandas ao processamento, histórico, painel de prazos (SLA) e e-mail de conclusão. |
| **Registro Solicitações de Fechamento** | `/processos-externos` | Para outras áreas abrirem solicitações ao processamento e acompanharem o andamento. |
| **Rentabilidade e Cotas** | `/rentabilidade` | Conferência do PL com a cota e monitor da rentabilidade diária (API Britech). |
| **Transactions Offshore** | `/transactions-offshore` | Trata os arquivos de transações de Bradesco Miami, BTG US e Morgan Stanley, lidos do Drive, e monta o e-mail do Daily Report. |
| **Crava Cotas** | `/crava-cotas` | Busca de informações do backoffice (pré-processamento) via Playwright. |
| **Conciliação de Caixa** | `/caixa` | Diferenças de caixa TAG x administradora. Hoje **desativada** no menu (`APPS_DESATIVADOS` em `main.py`). |
| **Conta, Usuários e Acessos** | `/conta`, `/usuarios`, `/acessos` | Troca de senha, gestão de usuários e relatório de uso (os dois últimos, só para administradores). |

Cada ferramenta tem a sua versão em `app/utilitarias/versoes.py` (formato `MAIOR.MENOR.CORREÇÃO` e data), mostrada no topo da página. Ao alterar um app, suba só a linha dele.

## Como o portal funciona

- **Login e segurança:** usuários e senhas próprios, gerenciados por um administrador dentro do portal. A senha é guardada só como hash (PBKDF2-SHA256 com sal e "pimenta"), há bloqueio por tentativas, vínculo do computador, sessão com cookie e autenticador (2FA). Cada pessoa só vê as ferramentas liberadas para ela. Veja `app/seguranca/controle_acesso.py`.
- **Banco de dados (MySQL):** cadastros, solicitações, rodadas de extratos, controle de erros e usuários ficam em tabelas com prefixo `portal_` (`app/database/esquema.sql`). O acesso usa um pool de conexões (`app/database/db.py`).
- **Conexão com o Google:** logo depois do login do portal, cada pessoa conecta a própria conta Google (Gmail e Drive). A conexão **vale 24 horas**; depois disso, é preciso conectar de novo. O portal guarda só o token, cifrado, e nunca a senha do Google. Quem prefere pode "continuar sem conectar", mas as telas que usam Gmail ou Drive não funcionam sem ela.
- **E-mail:** o envio, a conferência de envios e a leitura das respostas usam a API do Gmail (`app/utilitarias/email_gmail.py`). A conferência olha só as respostas às conversas dos e-mails que nós enviamos.
- **Arquivos no Drive** (`app/utilitarias/drive_google.py`):
  - o Offshore **lê** o histórico e o modelo de um Drive compartilhado;
  - o extratos **grava** em `<Drive de extratos>/<ano>/<MM>- <Mês>/<pasta do fundo>/`, usando a data de referência da rodada para escolher o ano e o mês. As pastas que faltam são criadas, e um arquivo repetido (mesmo nome e tamanho) não é duplicado.
- **Trava de envio em duplicidade:** o modal de envio do extratos avisa e pede uma confirmação a mais se o e-mail já saiu nas últimas 24 horas.

### Tela de teste do extratos

`/extratos?teste` abre o extratos com um **cadastro fictício**. Os e-mails saem de verdade, mas sempre e só para o endereço de teste, sem cópia, com `[TESTE]` no assunto. Para testar o recebimento, responda a um desses e-mails com um PDF e use *Conferir envios e respostas*: o anexo é salvo numa pasta de teste do Drive. Nada vai para o banco nem para o Drive da empresa.

## Estrutura

```
portal/
├── main.py                  # ponto de entrada: login, menu e páginas
├── iniciar.py / iniciar.bat # prepara o ambiente e sobe o portal (Windows)
├── requirements.txt
├── env/                     # .env.local, .env.hom, .env.prd (só configuração, sem segredos)
└── app/
    ├── ambiente/            # config_ambiente.py: APP_ENV, .env e Parameter Store
    ├── database/            # db.py, esquema.sql, criar_esquema.py, backup_banco.py e um módulo por assunto
    ├── api/                 # clientes de APIs externas (Britech)
    ├── seguranca/           # controle_acesso.py: login, sessão, 2FA
    ├── utilitarias/         # tema, versões, email_gmail.py, drive_google.py
    ├── assets/              # logos e arquivos de apoio
    └── paginas/             # uma pasta por ferramenta
        ├── extratos/  boletador/  solicitacoes/  processos_externos/
        ├── britech/  bradesco_miami/  crava_cotas/  conciliacao_caixa/  acessos/
```

## Ambientes e configuração

A variável `APP_ENV` escolhe o ambiente: **`local`**, **`hom`** ou **`prd`**. A configuração vem, em ordem de prioridade, de: variável do sistema, **AWS Parameter Store** (só hom e prd) e `env/.env.<ambiente>`. Os três arquivos `.env` são versionados e **não têm segredo**. O que é segredo fica em:

- **local:** `env/.env.segredo` (fora do git) ou variáveis do sistema;
- **hom e prd:** Parameter Store, autenticado pela função IAM do servidor (sem chave de acesso em arquivo).

Variáveis do projeto (só os nomes):

| Grupo | Variáveis |
|---|---|
| Ambiente | `APP_ENV`, `AWS_REGIAO`, `AWS_PARAMETER_STORE_PATH` |
| Banco | `BANCO_BKO_HOST`, `BANCO_BKO_PORTA`, `BANCO_BKO_NOME`, `BANCO_BKO_USUARIO`, `BANCO_BKO_SENHA` |
| Sessão e segurança | `PORTAL_SEGREDO`, `PORTAL_SESSAO_MIN`, `PORTAL_GRACA_SEG`, `PORTAL_MAX_FALHAS`, `PORTAL_BLOQUEIO_MIN`, `PORTAL_COOKIE_SECURE` |
| Google | `PATH_CREDENCIAIS_GMAIL`, `URL_PORTAL`, `GOOGLE_SESSAO_HORAS` |
| Drive | `DRIVE_BKO_PASTA_HISTORICO`, `DRIVE_BKO_ARQUIVO_MODELO`, `DRIVE_BKO_PASTA_EXTRATOS`, `DRIVE_BKO_PASTA_EXTRATOS_TESTE` (opcional) |
| E-mails de Solicitações | `EMAIL_PARA_SOLICITACOES`, `EMAIL_CC_SOLICITACOES` |
| APIs | `API_PRC_URL`, `BOLETADOR_PRC_URL` |
| Slack | `SLACK_WEBHOOK_AUT2`, `SLACK_CAMPO`, `SLACK_BOT_TOKEN_CRAVA_COTAS`, `SLACK_CANAL_CRAVA_COTAS` |
| Servidor (opcionais) | `PLAYWRIGHT_BROWSERS_PATH`, `PORTAL_DADOS`, `MYSQLDUMP_CAMINHO` |

A chave que cifra os tokens do Google não tem variável própria: no local fica em `dados/gmail/chave.key` e, em hom e prd, é derivada do `PORTAL_SEGREDO` (a variável `CHAVE_GMAIL` é opcional e, se existir, tem prioridade). Na subida, o portal confere as variáveis obrigatórias e falha com uma mensagem clara se faltar alguma.

## Como executar

Pré-requisitos: **Python 3.10** (padrão TAG; o `iniciar.py` avisa se for outra versão), acesso ao MySQL e, para o Boletador e o Crava Cotas, o Chromium do Playwright.

**Windows (desenvolvimento):** dê dois cliques em `portal/iniciar.bat`. Na primeira vez ele cria o `venv` (na pasta acima do código), instala as bibliotecas e o Chromium e sobe o portal com `APP_ENV=local`.

**Manualmente** (Windows ou Linux), dentro de `portal/`:

```bash
python -m venv ../venv
source ../venv/bin/activate        # Windows: ..\venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
export APP_ENV=local               # ou hom / prd
python -m streamlit run main.py
```

**Banco de dados**, dentro de `portal/`:

```bash
APP_ENV=local python -m app.database.criar_esquema   # cria o schema e as tabelas
APP_ENV=local python -m app.database.backup_banco    # backup com mysqldump (mantém 30 dias)
```

## Configurar o Google (Gmail e Drive)

1. No Google Cloud, ative a **Gmail API** e a **Drive API** e crie um cliente OAuth do tipo **Aplicativo da Web**.
2. Cadastre como URI de redirecionamento o endereço do portal (`URL_PORTAL`); em HTTPS no servidor, e `http://localhost:8501/` no local.
3. Libere os escopos `gmail.compose`, `gmail.readonly` e `drive`.
4. Coloque o `credentials.json` fora do repositório e aponte `PATH_CREDENCIAIS_GMAIL` para ele (no servidor, com permissão restrita).
5. Cada pessoa precisa ter acesso às pastas do Drive (Offshore: leitura; extratos: leitura e escrita).

## Como adicionar uma nova ferramenta

1. Crie `app/paginas/<nome>/pagina.py`.
2. Em `main.py`, crie a `st.Page`, acrescente uma entrada em `FERRAMENTAS` e em `CATEGORIAS` (o card da home, o menu e a busca saem dessa lista).
3. Crie a linha da ferramenta em `app/utilitarias/versoes.py` e use `app/utilitarias/tema.py` para manter o visual.
4. Libere a ferramenta aos usuários em *Usuários* (permissões por app).

## Padrões do projeto

- **Código:** siga `.claude/.docs/padroes-python-tag/` (funções em camelCase, variáveis em snake_case com prefixo de domínio, nomes em português, sem type hints).
- **Git:** siga `.claude/.docs/padroes-github-tag/` (`feature/*` a partir da `homolog`; PR para `homolog` e `main` só com aprovação da TI). Veja também o `CLAUDE.md`.
- **Segredos:** nunca no código, nos `.env` versionados nem no git. Documentos com variáveis (PDFs) não vão para o repositório.

## Limitações conhecidas para o servidor Linux

- **Crava Cotas, aba Britech:** abre o Chrome por um caminho do Windows; no Linux o botão não acha o navegador.
- **Backup do banco:** procura o `mysqldump.exe` em caminhos do Windows; no Linux funciona com o `mysqldump` no `PATH` ou com `MYSQLDUMP_CAMINHO`.
- **`iniciar.py` e `.bat`:** são para Windows; no Linux, suba com `python -m streamlit run main.py`.
- A pasta `dados/` (tokens do Google, backups, evidências) precisa ser **persistente** (pode ser apontada por `PORTAL_DADOS`).

## Contato

- **Responsável:** Marcelo Vinicius Jordão Almeida, marcelo.jordao@taginvest.com.br
