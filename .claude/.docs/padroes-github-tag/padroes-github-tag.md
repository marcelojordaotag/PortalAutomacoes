---
name: padroes-github-tag
description: >-
   Padrões de versionamento e GitHub da TAG Invest para os projetos das áreas (não-TI) — modelo de
   branches (homolog / main / feature), nomes de branches, mensagens de commit, proteção de branch,
   fluxo de Pull Request e o que nunca versionar. Consulte SEMPRE que for versionar um projeto de área
   da TAG: clonar o repositório da org, criar ou nomear branches, salvar uma versão (commit), enviar para o
   GitHub (push), abrir um Pull Request, publicar em homologação, configurar a proteção de branch,
   montar o .gitignore, ou orientar um usuário (em geral não-técnico) a guardar/publicar o trabalho.
   Vale mesmo quando o usuário não cita "Git" ou "GitHub" explicitamente — pedidos como "salve uma
   versão disso", "guarda isso", "manda pra homologação", "abre uma revisão" devem seguir estas
   convenções. O Claude executa as ações de Git em nome do usuário e comunica cada passo em
   linguagem simples.
---

# Padrões de GitHub e Versionamento da TAG Invest

Fluxo de versionamento dos **projetos das áreas (não-TI)**. O público é **não-técnico**: o Claude
**executa as ações de Git em nome do usuário** e o usuário só aprova. Sempre comunique cada passo em
**linguagem simples**, traduzindo qualquer termo técnico.

---

## Antes de tudo (regra de ordem — ANTES de gerar qualquer código)

1. **Verifique o `gh` no início de *cada* sessão** — instalação **e** autenticação. É automático:
   **nunca pergunte ao usuário** se ele tem o `gh`, apenas cheque. Se faltar algo, conduza o passo a
   passo da seção "Verificação do `gh`" abaixo.
2. **Confirme que está dentro do clone do projeto** (`git remote get-url origin`) — é dele que sai o
   caminho do repositório na org `taginvest`. **Nunca pergunte a URL ao usuário.** Se não houver clone,
   o repositório vem do **link que a TI passa** (ver "Onde fica o repositório").
3. **Planeje e pergunte o essencial** — **mesmo sem o modo de planejamento ligado** (ver "Conversa com
   o usuário"). Não comece a codar antes de alinhar o plano.
4. **Atualize sempre antes de qualquer ação** (`git fetch --all --prune`) — obrigatório **antes de
   criar branch, commitar, dar push ou abrir PR**. Nunca parta de uma cópia desatualizada; confira
   também se `homolog` mudou desde a última vez.
5. **Crie a branch da feature SEMPRE a partir de `homolog`** (sugira o nome). Trabalhe **sempre dentro
   dela** — nunca direto em `homolog` ou `main`.

> O envio ao GitHub (`push`) e o Pull Request acontecem **só no fim**, com permissão do usuário
> (ver "Fluxo de trabalho"). Nunca escreva código fora de uma `feature/*`.

---

## Verificação do `gh` (início de cada sessão)

O `gh` é a ferramenta que permite ao Claude abrir Pull Requests e conversar com o GitHub em nome do
usuário. **No começo de toda sessão**, rode as duas checagens — sem perguntar nada antes:

```bash
gh --version
```

```bash
gh auth status
```

Se as duas passarem, siga o trabalho normalmente e **não mencione o assunto**. Se alguma falhar,
conduza o usuário (não-técnico) pelo passo a passo abaixo, **um passo por vez**, esperando ele
confirmar antes de seguir para o próximo. Explique o "para quê" de cada passo em linguagem simples.

### Caso A — `gh` não está instalado

> *"Antes de começar, precisamos instalar uma ferramenta do GitHub chamada `gh`. É ela que me deixa
> guardar seu trabalho na nuvem e pedir a revisão da TI por você. Leva menos de um minuto."*

1. **Instalar.** Rode o comando abaixo (o Claude pode executar por você):

   ```bash
   winget install --id GitHub.cli
   ```

2. **Fechar e reabrir o programa.** Peça para o usuário **fechar o Claude Code (ou o terminal) e
   abrir de novo** — só assim o computador "enxerga" a ferramenta nova.
3. **Conferir.** Rode `gh --version`. Se aparecer um número de versão, deu certo.
4. Se o `winget` não existir na máquina, oriente baixar o instalador em
   **https://cli.github.com** (botão de download para Windows), abrir o arquivo e clicar em
   *Next / Install* até o fim — e então voltar ao passo 2.

Se a instalação falhar (bloqueio de firewall, falta de permissão de administrador), **pare e avise
que é preciso acionar a TI** — não tente contornar.

### Caso B — `gh` instalado, mas não autenticado

> *"A ferramenta já está instalada, só falta você entrar na sua conta do GitHub — é como fazer login
> num site. Vou abrir o processo e te guiar."*

1. **Iniciar o login:**

   ```bash
   gh auth login
   ```

2. **Responder as perguntas na tela** (use as setas ↑ ↓ e a tecla **Enter**), nesta ordem:
   - *What account do you want to log into?* → **GitHub.com**
   - *What is your preferred protocol for Git operations?* → **HTTPS**
   - *Authenticate Git with your GitHub credentials?* → **Yes**
   - *How would you like to authenticate?* → **Login with a web browser**
3. **Copiar o código de 8 caracteres** que aparece na tela (algo como `A1B2-C3D4`) e apertar
   **Enter** — o navegador abre sozinho.
4. **No navegador:** entrar com a conta **GitHub da TAG**, colar o código e clicar em
   **Authorize / Continue**.
5. **Voltar ao Claude Code** e conferir:

   ```bash
   gh auth status
   ```

   Deve aparecer *"Logged in to github.com as <seu-usuário>"*. Pronto.

> **Nunca** peça, digite ou guarde a senha do usuário, nem crie/cole tokens de acesso em arquivos do
> projeto. O login acontece **no navegador, pelo próprio usuário** — o Claude apenas conduz.
> Se o usuário não tiver conta do GitHub da TAG, **acione a TI**: criação de conta é responsabilidade dela.

---

## Conversa com o usuário — planejar antes de fazer

Mesmo que o usuário **não** tenha ligado o modo de planejamento, antes de construir qualquer coisa:

- Faça um **plano** curto do que será feito.
- **Pergunte o essencial** sobre o sistema/funcionalidade: objetivo, de onde vêm os dados, o que a
  tela/relatório deve mostrar, regras importantes e o que significa "estar pronto".
- Só comece a desenvolver **depois de alinhar o plano** com o usuário.

---

## Princípios

1. **O Claude faz o Git pelo usuário**, em linguagem natural.
2. **`homolog` e `main` são protegidas:** só recebem mudanças via PR **aprovado pela TI**.
3. **Um trabalho, uma branch** (`feature/*`) — o trabalho inteiro, não um pedaço dele.
4. **Sempre há um "antes"** (`/rewind` + histórico do GitHub).
5. **Nada sensível entra no Git.**

---

## Modelo de branches (projetos das áreas)

| Branch | Papel | Regra |
|--------|-------|-------|
| `feature/*` | O trabalho pedido pelo usuário, do começo ao fim — inclusive mudanças de tipos diferentes que ele exigir. | Criada **sempre a partir de `homolog`**; PR de volta para `homolog` **aprovado pela TI**. |
| `homolog` | **Base estável = versão publicada em homologação.** É de onde as `feature/*` saem. | Protegida. Recebe `feature/*` **só via PR aprovado pela TI**. |
| `main` | Produção. | Protegida. **A TI é quem abre e aprova o PR de `homolog` → `main`** — a área não faz esse passo. |

**Fluxo:**

```
feature/* (de homolog)  ──PR (TI aprova)──▶  homolog (homologação)  ──PR aberto e aprovado pela TI──▶  main (produção)
```

> As features **começam a partir da base estável (`homolog`)** — sem exceção — e voltam para ela via PR
> aprovado pela TI.

### Uma branch por trabalho — não por tipo de mudança

A `feature/*` cobre a demanda toda: função nova **+** reorganização de pastas **+** renomeação **+**
preenchimento de `.env` — tudo na mesma branch, mesmo misturando tipos de mudança diferentes.

**Nunca abra uma segunda branch porque o tipo de mudança mudou.** Refactoring, mover pastas, renomear
arquivo, ajustar o que já existia e consertar o que quebrou no caminho são parte do mesmo trabalho, não
motivo para uma `feature/*` nova. Exemplo: **adaptar um projeto existente ao padrão** mexe no código e
reorganiza a pasta inteira — é um trabalho só, uma branch só.

Enquanto a branch **não foi para PR**, tudo que o usuário pedir entra nela — mesmo que soe como outro
assunto. Não devolva ao usuário a decisão de classificar o pedido como "mesmo trabalho" ou "trabalho
novo".

**Nasce branch nova quando a anterior já virou PR** — aquela está fechada. Aí sim: `git fetch` e nova
`feature/*` a partir da `homolog` atualizada.

Dividir por tipo de mudança faria o usuário acompanhar vários PRs e várias aprovações da TI para uma
demanda única — é isso que esta regra evita.

### Sobre a `main` (produção)

- A área **nunca** abre PR para a `main` e **nunca** faz merge nela.
- **A abertura do PR de `homolog` → `main` e a aprovação são feitas pela TI.** É a TI quem decide
  quando o que está em homologação vai para produção.
- Se o usuário pedir "colocar em produção", explique isso e ofereça **avisar a TI** — não tente
  abrir o PR para `main`.

---

## Onde fica o repositório (organização `taginvest`)

Todos os projetos vivem na organização **`taginvest`** no GitHub — **nunca** na conta pessoal de quem
desenvolve.

**A TI cria o repositório e passa o link — sempre.** A área não cria repositório e não define o nome
dele: quando um projeto novo começa, peça o repo à TI e depois **apenas clone**. O Claude **nunca** roda
`gh repo create`.

### O Claude descobre o caminho sozinho — não pergunte a URL

Dentro da pasta clonada, o endereço do repositório já está gravado. Basta:

```bash
git remote get-url origin
```

O resultado (`https://github.com/taginvest/<repo>.git`) já dá o dono e o nome. O `gh` usa isso
automaticamente: rodando de dentro da pasta do projeto, `gh pr create` **já sabe** para qual
repositório abrir o PR. O usuário não precisa saber nem digitar endereço nenhum.

---

## Padrão de nomes de branches

Kebab-case, sem acento, minúsculo. O nome descreve **o trabalho como um todo** (o objetivo), não a
mudança individual — e o Claude **sugere 2–3 nomes** para o usuário escolher (ou usa o dele, ajustado
ao padrão).

- **`feature/*`** — criada a partir de **`homolog`**; PR para **`homolog`** (gate da TI).

Exemplo: `feature/dashboard-carteiras` cobre criar a tela, reorganizar as pastas e ajustar a query —
e **não** `feature/ajusta-query` + `feature/move-pastas`. Se o trabalho crescer e passar a incluir algo
que o nome não previa, **não renomeie a branch nem crie outra** — o nome não precisa cobrir cada
detalhe.

As branches fixas (`homolog`, `main`) nunca são renomeadas.

---

## Fluxo de trabalho de uma feature (passo a passo)

0. **Checar o `gh`** (instalado e autenticado) — início de cada sessão.
1. **Planejar + perguntar o essencial** (obrigatório, mesmo sem modo de planejamento).
2. **Atualizar** (`git fetch --all --prune`) e checar mudanças nas outras branches — **sempre, antes de
   qualquer ação de Git**.
3. **Criar a `feature/<nome>` a partir de `homolog`** (localmente), com a `homolog` recém-atualizada.
4. **Desenvolver o pedido inteiro, nessa mesma branch** — inclusive reorganizar pastas, renomear
   arquivos e ajustar o que já existia, se o trabalho exigir — com **commits locais a cada etapa
   concluída**.
5. **Ao terminar as tarefas da feature, PERGUNTAR** se pode **subir para o GitHub** (`push`) — em
   linguagem simples. **Só com o "sim"**, faça `git fetch` de novo e o push.
6. Em seguida, **PERGUNTAR** se pode **abrir o PR para `homolog`** (explique o que é PR e o que
   é merge). Com o "sim": abra o PR **com descrição das mudanças/novas funcionalidades**. O merge em
   `homolog` **depende de aprovação da TI**.
7. **Publicar em homologação** = ter o PR da `feature/*` → `homolog` **aprovado pela TI**.
8. **Produção (`main`)** não faz parte deste fluxo: **a TI abre e aprova** o PR de `homolog` → `main`.

### Ao terminar a feature — como perguntar (para leigos)

Primeiro, o envio ao GitHub:

> *"Terminei o que você pediu. Posso **subir isso para o GitHub**? Na prática, é guardar seu trabalho
> na nuvem, para não se perder. Posso seguir?"*

Depois do "sim" (push), o Pull Request:

> *"Quer que eu **abra um pedido de revisão (PR)** para juntar seu trabalho na `homolog`? O **PR** é o
> pedido de juntar seu trabalho ao projeto; o **merge** é essa junção acontecendo — e ela só é feita
> depois que a **TI aprovar**."*

### Como acompanhar o PR para `homolog` (para não-técnico)

`homolog` é **protegida** — a junção só acontece com **aprovação da TI**:

1. Abra o link do Pull Request (o Claude te manda) ou vá na aba **"Pull requests"**.
2. Veja o resumo das mudanças.
3. **Aguarde a TI revisar e aprovar.** Só depois o botão de **"Merge"** fica liberado.
4. Com a aprovação, confirma-se o merge e pode-se **"Delete branch"** para limpar.

### Descrição do PR (sempre)

Todo PR deve trazer, na descrição, um resumo claro em português: **o que mudou**, **quais
funcionalidades novas** e **como ver/testar**. Nunca abra um PR com descrição vazia.

O PR faz à TI **um único pedido**: cadastrar os parâmetros do Parameter Store (ver "Validações antes
de abrir o PR"). Nada além disso — se o texto do PR estiver pedindo para a TI preencher, completar ou
ajustar alguma coisa, é sinal de que o PR foi aberto cedo demais.

---

## Validações antes de abrir o PR (projetos Python)

Antes de abrir o PR, o Claude confere:

1. **Nenhum valor pendente nos `.env`.** Percorrer os arquivos `env/.env.local`, `.env.hom` e
   `.env.prd` e checar se alguma variável não sensível (região e path do Parameter Store, host, porta,
   schema, URL, path, ID de pasta — ver "O que vai no `.env`" na doc de padrões Python) está **vazia
   ou com placeholder `DEFINIR-<VARIAVEL>-<AMBIENTE>`**. Placeholder conta como pendência. **Se
   houver, bloquear a abertura do PR** e avisar o usuário quais variáveis e em qual arquivo faltam,
   para que ele obtenha os valores e preencha antes de seguir.

   O PR significa "o código está pronto para subir", e isso inclui a configuração. Esses valores são
   dados de configuração, não segredos: quem obtém e preenche é a área, durante o desenvolvimento —
   nunca a TI, na revisão.

   **Commit e PR têm travas diferentes.** Placeholder pode ficar em commit na branch, para não
   interromper o trabalho. PR aberto com placeholder, não: se algum desses valores ainda não existe,
   **o PR não é aberto** — o trabalho fica na branch, com o placeholder, até o valor chegar. Abrir o
   PR e listar essas variáveis como pendência transfere para a revisão um problema que é do
   desenvolvimento.

2. **A descrição do PR pede à TI exatamente uma coisa: cadastrar os parâmetros sensíveis no Parameter
   Store.** Nunca o valor — só o nome, o caminho e o tipo, para a TI bater o olho e saber o que
   precisa existir cadastrado antes de aprovar. Usar sempre este formato, com o cabeçalho
   `## AWS Parameter Store` e uma tabela com caminho (HOM e PRD) e tipo:

   ```markdown
   ## AWS Parameter Store

   | Variável | Caminho HOM | Caminho PRD | Tipo |
   |----------|-------------|-------------|------|
   | BANCO_GST_USUARIO | /hom/gestao-monitoramento-offshore/BANCO_GST_USUARIO | /prd/gestao-monitoramento-offshore/BANCO_GST_USUARIO | String |
   | BANCO_GST_SENHA | /hom/gestao-monitoramento-offshore/BANCO_GST_SENHA | /prd/gestao-monitoramento-offshore/BANCO_GST_SENHA | SecureString |
   ```

   Essa seção entra em **todo PR de projeto Python**, mesmo que a lista de variáveis não tenha mudado
   nesta etapa — é o que a TI usa para conferir o que precisa cadastrar/validar no Parameter Store.

   **Nunca liste no PR variável que mora no `.env`** — `AWS_REGIAO`, `AWS_PARAMETER_STORE_PATH`,
   `BANCO_{SIGLA}_HOST`, `BANCO_{SIGLA}_PORTA`, `BANCO_{SIGLA}_NOME`, paths, e-mails, IDs de pasta.
   Elas já estão preenchidas e versionadas com o código (validação 1). Incluí-las no pedido sugere que
   falta alguém preenchê-las, e a TI não edita arquivo do repositório: ela cadastra parâmetro na AWS,
   aprova o PR e atualiza o ambiente.
3. **`requirements.txt` obrigatório.** Confirmar que o projeto tem o arquivo `requirements.txt` na raiz.
   **Se não existir, bloquear o PR** e gerar o arquivo antes de seguir.

---

## Mensagens de commit

Frase curta, no imperativo, em português, descrevendo o que mudou. Uma ideia por commit.

```
adiciona filtro de data no dashboard de carteiras
corrige cálculo de PL quando não há posição
```

Evite mensagens genéricas (`ajustes`, `wip`, `update`, `teste`).

**É no commit, e não na branch, que as mudanças se separam.** A branch é o trabalho todo; cada commit
é uma etapa dele — a função nova num commit, a reorganização de pastas em outro. É isso que mantém o
histórico legível e faz o `/rewind` voltar a um ponto útil.

---

## Proteção das branches

**`homolog` e `main` são protegidas: só recebem mudanças por Pull Request, e o PR é aprovado
exclusivamente pela TI.** Nada entra nessas duas branches sem essa aprovação.

Isso é tudo o que a área precisa saber. A configuração em si é responsabilidade da TI e **não é um
arquivo do projeto** — não existe `CODEOWNERS` aqui, e o Claude não deve criar nem alterar regras de
proteção.

---

## O que NUNCA commitar

- **Segredos**: senhas, tokens, credenciais (ex.: `service_account.json`).
- **Dados reais**: posições, carteiras, extratos, cadastro de clientes, bases exportadas do banco ou
  de sistema — **em qualquer formato** (`.xlsx`, `.csv`, `.xml`, `.json`, `.pdf`).
- **Binários pesados**: dumps, executáveis, arquivos grandes que só crescem.

### Arquivos de apoio **podem** ser versionados

O que a regra acima proíbe é **dado**, não **arquivo**. Projetos de área quase sempre dependem de
arquivos de apoio para funcionar — um `.json` de parametrização, um `.csv` de de-para, um `.xml` de
layout, uma planilha modelo, um logo. Esses **entram no repositório**: sem eles o projeto não roda, e
deixá-los de fora obriga cada pessoa a reconstruir o ambiente na mão.

| | Apoio — versiona | Dado — não versiona |
|---|---|---|
| Conteúdo | parametrização, de-para, layout, template, exemplo fictício | posição, carteira, cliente, valores reais |
| Muda quando | o código muda | a cada execução |
| Tamanho | pequeno e estável | grande, cresce sozinho |
| Se sumir | o projeto para de funcionar | é só reprocessar ou baixar de novo |

Convenção: arquivo de apoio fica **dentro do projeto** (ex.: `app/assets/`); entrada e saída de
processamento ficam em `dados/`, que o `.gitignore` cobre.

**Na dúvida, pergunte ao usuário antes de commitar** — sobretudo se o arquivo tiver nome de cliente,
CPF, valor ou data de posição no conteúdo ou no nome. Um de-para de 40 linhas é apoio; a mesma
planilha com o PL de cada carteira é dado.

> **Os três `.env` são versionados** — `env/.env.local`, `.env.hom` e `.env.prd`. Por construção
> nenhum deles contém segredo: usuário e senha vivem em variável de ambiente do SO (local) e no
> Parameter Store (HOM/PRD), e o que sobra é configuração. É isso que permite ao PR chegar com a
> configuração pronta e ao próximo desenvolvedor rodar o projeto sem reconstruir o ambiente na mão.
>
> A contrapartida é que **uma senha colada num `.env` vai para o GitHub**. Antes de qualquer commit,
> confira: se aparecer valor em `BANCO_{SIGLA}_USUARIO`, `BANCO_{SIGLA}_SENHA`, `SECRET_JWT` ou
> qualquer token dentro desses arquivos, **pare e avise o usuário** — o valor sai do arquivo e vai
> para onde é o lugar dele.

Se houver risco de versionar dado real, **pare e avise o usuário**. O `.gitignore` do projeto cobre
os casos previsíveis, mas ele não sabe o que tem dentro de um arquivo — a conferência antes do commit
continua sendo necessária.

`.gitignore` mínimo:

```gitignore
# A pasta env/ inteira é versionada: .env.local, .env.hom e .env.prd têm só
# configuração (host, porta, schema, região, path do Parameter Store), nunca
# segredo — usuário e senha ficam em variável de ambiente do SO e no Parameter Store.

# Segredos e credenciais
**/credenciais/
service_account.json

# Dados de execução — entrada e saída do processamento.
# Arquivo de apoio (parametrização, de-para, layout, template) NÃO fica aqui:
# fica dentro do projeto e é versionado normalmente.
dados/
entrada/
saida/

# Binários pesados
*.zip
*.exe
*.dmp
*.bak

# Python
__pycache__/
*.pyc
venv/

# IDE e editor
.idea/
.vscode/
```

---

## Rede de segurança (oriente o usuário)

- **`/rewind`** — desfaz mudanças recentes.
- Todo commit enviado fica no histórico do GitHub: sempre há um "antes".

---

## Quando envolver a TI

> A divisão completa de responsabilidades entre área e TI está no `CLAUDE.md` (§ Quem faz o quê —
> área x TI). Aqui vai só a lista de gatilhos práticos para acionar a TI durante o versionamento.

- **aprovar o PR de uma `feature/*`** (`feature/*` → `homolog`);
- **cadastrar ou atualizar os parâmetros sensíveis no Parameter Store** — é o **único** pedido que o
  PR faz à TI; valor de `.env` não entra nessa conversa;
- **abrir e aprovar o PR de produção** (`homolog` → `main`) — é sempre a TI que faz os dois;
- **criar o repositório** na org `taginvest` e **dar acesso à equipe da área**;
- **criar conta do GitHub** ou resolver bloqueio na instalação/autenticação do `gh`;
- diante de qualquer **falha ou risco de segurança**.

---

## Glossário sem jargão

| Termo | Em português simples |
|-------|----------------------|
| Repositório | A pasta do projeto guardada na nuvem (GitHub). |
| Organização (org) | A conta da empresa no GitHub — a nossa é a **`taginvest`**, onde ficam todos os projetos. |
| Clonar | Baixar para o computador uma cópia do projeto que está na nuvem. |
| `origin` | O apelido do endereço do projeto na nuvem, gravado dentro da pasta clonada. |
| Commit | Uma fotografia/versão salva do projeto. |
| Branch | Um rascunho paralelo seguro. |
| `homolog` | A versão publicada em homologação; base de onde as features saem. |
| `main` | A versão em produção. Só a TI abre e aprova o PR que chega nela. |
| `feature/*` | O rascunho do trabalho pedido — **um por trabalho, não um por mudança** — criado **sempre** a partir de `homolog`. |
| Push | Enviar as mudanças para o GitHub (guardar na nuvem). |
| Pull Request (PR) | Pedido para juntar o trabalho de uma branch em outra. |
| Merge | Juntar (mesclar) as mudanças de uma branch na outra. |
| `gh` | Ferramenta do GitHub que deixa o Claude abrir PRs e falar com o GitHub por você. |
