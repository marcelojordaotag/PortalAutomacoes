# CLAUDE.md — Orquestrador de Padrões TAG

Ponto de entrada do projeto. **SEMPRE que a interação envolver desenvolvimento** — criar ou alterar um
sistema, escrever ou mexer em código, começar um projeto, "construir", "ajustar", "criar tela/relatório"
— consulte e siga as documentações em **`.claude/.docs/`**, **mesmo que o pedido não cite "Git",
"versionamento" ou "padrão"**.

## Regra de ordem (antes de gerar qualquer código)

1. **Verifique o `gh` no início de cada sessão** — instalação (`gh --version`) **e** autenticação
   (`gh auth status`). Automático: **não pergunte ao usuário**. Se faltar qualquer um dos dois, conduza
   o **passo a passo para usuário não técnico** da seção "Verificação do `gh`" em
   **`.claude/.docs/padroes-github-tag/padroes-github-tag.md`** (instalar e autenticar) antes de seguir.
2. **Confirme o repositório pelo clone** (`git remote get-url origin`) — os projetos ficam na org
   **`taginvest`** e o caminho já está gravado na pasta clonada. **Nunca pergunte a URL ao usuário.**
3. **Planeje e pergunte o essencial** sobre o sistema/funcionalidade — **mesmo sem o modo de
   planejamento ligado**. Só codar depois de alinhar o plano.
4. **Versionamento primeiro** → siga a documentação **`.claude/.docs/padroes-github-tag/padroes-github-tag.md`**:
   **atualizar sempre** (`git fetch --all --prune`) **antes de qualquer ação de Git** e **criar a
   `feature/*` SEMPRE a partir de `homolog`** antes de escrever código. **Uma só `feature/*` para todo
   o trabalho pedido** — não abrir outra por tipo de mudança (função, refactor, pastas); branch nova só
   quando a anterior já foi para PR.
   O **`push` e o PR só no fim, com permissão do usuário**. Nunca escreva código fora de uma `feature/*`.
5. **Padrão da linguagem** → em trabalho Python, siga a documentação
   **`.claude/.docs/padroes-python-tag/padroes-python-tag.md`**.

## Roteamento

- Qualquer **desenvolvimento / versionamento** (clonar repositório, branch, commit, PR, publicar em
  homologação, salvar/enviar versão) → **`.claude/.docs/padroes-github-tag/padroes-github-tag.md`**.
- Qualquer **código Python** → **`.claude/.docs/padroes-python-tag/padroes-python-tag.md`**.

## Regras transversais da casa

- Nunca versionar nem expor senhas, tokens, credenciais ou dados sensíveis — nem no código, nem aqui,
  nem em arquivos commitados.
- **Os repositórios ficam na org `taginvest`, e é a TI que os cria e passa o link.** A área apenas
  clona — nunca rode `gh repo create`. Se o repo não existir ou o usuário não tiver acesso, acione a TI.
- **`homolog` (homologação) e `main` (produção) são protegidas: PR para essas branches é aprovado
  somente pela TI.**
- **`main` (produção): a abertura do PR (`homolog` → `main`) e a aprovação são feitas pela TI.** A área
  não abre PR para a `main` — se pedirem "subir para produção", explique isso e ofereça acionar a TI.
- Toda `feature/*` nasce de `homolog`, com a `homolog` recém-atualizada (`git fetch`).

## Quem faz o quê — área x TI

Os projetos das áreas são mantidos pelas **áreas de negócio**, não pela TI. A divisão é fixa,
independente da linguagem do projeto:

| Responsabilidade | Quem faz |
|------------------|----------|
| Escrever o código e manter o projeto | Área dona do projeto |
| Preencher os `env/.env.local`, `.env.hom`, `.env.prd` | Área dona do projeto |
| Definir as variáveis de ambiente do SO na própria máquina (local) | Área dona do projeto |
| Abrir o PR | Área dona do projeto |
| Cadastrar e atualizar os parâmetros no Parameter Store (HOM/PRD) | TI |
| Aprovar o PR e atualizar o ambiente | TI |

**A TI não mexe no código nem nos arquivos do projeto.** Ela detém os valores de infraestrutura
(host, schema, credenciais dos ambientes) e cadastra os parâmetros sensíveis na AWS — mas quem
escreve qualquer valor dentro do repositório é sempre a área.

Isso muda a forma de tratar um valor pendente: o caminho é **a área obter o valor com a TI e
preencher ela mesma**. Nunca escreva, nem no `.env`, nem no commit, nem no PR, nem na conversa, que a
TI "vai preencher", "vai completar o arquivo" ou "vai ver a pendência" — não vai. O que a TI faz com
uma credencial é cadastrá-la no Parameter Store.
