"""CRAVA COTAS: abre o pré-processamento do backoffice via Playwright e copia as informações do card.

Roda como processo separado (`python navegador.py`), como o importador do boletador. O login fica
guardado no perfil do navegador entre execuções. Para cada dia (D-2 e depois D-3): abre o card
"Importar Crava Cotas Fundos Completos", confere o Progresso, filtra "Posição indisponível", copia a tabela e
fecha o modal. O resultado vai para dados/crava_cotas/tabela.json (a página do app lê esse arquivo).
Se tudo foi copiado e conferido, o navegador fecha sozinho; com avisos ou falhas, fica aberto até o usuário fechar.
"""
import json
import re
from datetime import datetime
from pathlib import Path

URL_PRE_PROCESSAMENTO = "https://backoffice.taginvest.com.br/pre-processamento"
PERFIL_NAVEGADOR = Path.home() / ".crava_cotas_perfil"  # guarda o login entre execuções
TEMPO_MAX_LOGIN = 300  # segundos esperando o usuário logar
TEMPO_LOGIN_AUTOMATICO = 90  # no aviso agendado ninguém loga: se o login salvo expirou, desiste cedo
ARQUIVO_TABELA = Path(__file__).resolve().parents[3] / "dados" / "crava_cotas" / "tabela.json"  # lido pela página
JS_LER_TABELA = r"""() => {
    const texto = (el) => (el ? el.innerText.replace(/\s+/g, " ").trim() : "");
    return [...document.querySelectorAll("table.p-datatable-table")]
        .filter((tabela) => tabela.querySelector("thead").textContent.toLowerCase().includes("id exec"))
        .flatMap((tabela) => [...tabela.querySelectorAll("tbody tr")]).map((tr) => {
        const td = tr.querySelectorAll("td");
        const spans = td[1] ? td[1].querySelectorAll("span") : [];
        return [texto(td[0]), texto(spans[0]), texto(spans[1]), texto(td[2]), texto(td[3])];
    }).filter((linha) => linha[0]);
}"""
JS_DIAGNOSTICO = r"""() => [...document.querySelectorAll("table")].map((t) =>
    (t.className || "?") + " | linhas=" + t.querySelectorAll("tbody tr").length + " | cab=" + (t.querySelector("thead") ? t.querySelector("thead").textContent.replace(/\s+/g, " ").trim().slice(0, 80) : "-")
).join(" ;; ")"""
DIAS = ["D-2", "D-3"]  # processados nesta ordem
COLUNAS_TABELA = ["ID Exec.", "Fundo", "CNPJ", "Valor da Cota", "Status"]
TITULO_CARD = "Importar Crava Cotas Fundos Completos"
STATUS_FILTRO = "Posição indisponível"


def esperarCarregar(pagina_atual, ms=1500):
    """Espera a rede acalmar e dá uma pausa, para o Angular terminar de desenhar a tela antes do próximo clique."""
    try:
        pagina_atual.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass  # algumas telas mantêm requisições abertas; a pausa abaixo cobre
    pagina_atual.wait_for_timeout(ms)


def esperarTabelaEstavel(pagina_atual, tentativas=15):
    """Espera o número de linhas da tabela parar de mudar (filtro e carga terminados). Devolve True se estabilizou."""
    anterior = -1
    for _ in range(tentativas):
        total = len(pagina_atual.evaluate(JS_LER_TABELA))
        if total > 0 and total == anterior:
            return True
        anterior = total
        pagina_atual.wait_for_timeout(1000)
    return False


def lerProgresso(modal):
    """Percentual do bloco "Progresso" do card (0 a 100), ou None se o bloco não for encontrado."""
    rotulo = modal.get_by_text("Progresso", exact=True).first
    try:
        rotulo.wait_for(state="visible", timeout=5000)
        texto = rotulo.locator("xpath=following-sibling::div[1]").inner_text(timeout=3000)
    except Exception:
        return None
    achado = re.search(r"(\d+(?:[.,]\d+)?)\s*%", texto)
    return float(achado.group(1).replace(",", ".")) if achado else None


def diagnostico(pagina_atual, contexto):
    """Texto com url, abas e tabelas vistas, para entender uma leitura vazia."""
    return (f"url={pagina_atual.url} | abas={len(contexto.pages)} | frames={len(pagina_atual.frames)} || "
            + (pagina_atual.evaluate(JS_DIAGNOSTICO) or "nenhuma tabela na página"))


def gravarArquivo(dias, concluido):
    """Grava o estado atual para a página do app: um resultado por dia e se a rodada terminou."""
    ARQUIVO_TABELA.parent.mkdir(parents=True, exist_ok=True)
    ARQUIVO_TABELA.write_text(
        json.dumps({"lido_em": datetime.now().isoformat(sep=" ", timespec="seconds"), "concluido": concluido,
                    "colunas": COLUNAS_TABELA, "dias": dias}, ensure_ascii=False),
        encoding="utf-8",
    )


def resultadoDia(situacao, progresso=None, linhas=None, detalhe=""):
    """situacao: ok | sem_card | sem_valores | sem_posicao_indisponivel | erro."""
    return {"situacao": situacao, "progresso": progresso, "linhas": linhas or [], "diagnostico": detalhe}


def resultadoConferido(dias, rotulo):
    """Relê o arquivo e confirma que o dia foi gravado como "ok" com todas as linhas copiadas."""
    try:
        gravado = json.loads(ARQUIVO_TABELA.read_text(encoding="utf-8"))["dias"][rotulo]
    except Exception:
        return False
    return gravado["situacao"] == "ok" and len(gravado["linhas"]) == len(dias[rotulo]["linhas"]) > 0


def lerExecucoes(pagina_atual, contexto, modal, PlaywrightTimeoutError):
    """Dentro do modal do card: confere o progresso e, se houver valores, copia a tabela de execuções filtrada."""
    progresso = lerProgresso(modal)
    if progresso == 0:  # nada para buscar ainda
        print("Progresso 0%: sem valores para buscar.", flush=True)
        return resultadoDia("sem_valores", 0)

    # Aba Execuções e filtro de status: "Posição indisponível" costuma já vir marcado
    modal.locator("div.aba", has_text="Execuções").first.click()
    esperarCarregar(pagina_atual)
    if modal.locator(".p-multiselect-chip", has_text=STATUS_FILTRO).count() == 0:
        dropdown = modal.locator("div.p-multiselect-dropdown").first
        dropdown.click()
        item = pagina_atual.locator('li[role="option"]').filter(has_text=STATUS_FILTRO).first
        try:
            item.wait_for(state="visible", timeout=10000)
        except PlaywrightTimeoutError:
            print(f'Item "{STATUS_FILTRO}" não encontrado.', flush=True)
        else:
            item.click()
        dropdown.click()  # fecha a lista (Escape fecharia o modal inteiro)
        esperarCarregar(pagina_atual, 2000)  # o filtro recarrega a tabela

    esperarTabelaEstavel(pagina_atual)
    linhas = pagina_atual.evaluate(JS_LER_TABELA)
    if linhas:
        print(f"{len(linhas)} linhas copiadas.", flush=True)
        return resultadoDia("ok", progresso, linhas)
    # Progresso > 0, mas o filtro não trouxe nenhum item "Posição indisponível": avisa e segue, sem quebrar
    print(f'Filtro "{STATUS_FILTRO}" sem itens.', flush=True)
    return resultadoDia("sem_posicao_indisponivel", progresso, [], diagnostico(pagina_atual, contexto))


def processarDia(pagina_atual, contexto, rotulo, PlaywrightTimeoutError):
    """Atalho de data -> card -> modal -> leitura -> fecha o modal. Devolve o resultado do dia."""
    pagina_atual.locator("button.btn-atalho-data", has_text=rotulo).first.click()
    esperarCarregar(pagina_atual)
    card = pagina_atual.locator("div.card-atividade").filter(has=pagina_atual.get_by_text(TITULO_CARD, exact=True)).first
    try:
        card.wait_for(state="visible", timeout=10000)  # dá tempo de a lista de atividades carregar
    except PlaywrightTimeoutError:
        print(f'{rotulo}: card "{TITULO_CARD}" não encontrado.', flush=True)
        return resultadoDia("sem_card")
    card.click()
    esperarCarregar(pagina_atual)

    # O card abre um modal; a leitura é toda dentro dele (a página de trás tem botões iguais)
    modal = pagina_atual.locator("div.p-dialog").filter(has_text=TITULO_CARD).first
    modal.wait_for(state="visible", timeout=10000)
    try:
        return lerExecucoes(pagina_atual, contexto, modal, PlaywrightTimeoutError)
    finally:
        modal.locator("button.p-dialog-close-button").first.click()  # fecha o modal (também se a leitura falhar)
        modal.wait_for(state="hidden", timeout=10000)
        esperarCarregar(pagina_atual, 1000)


def carregarDiasGravados():
    """Resultados já gravados (o modo automático atualiza só o dia dele e preserva os outros)."""
    try:
        return json.loads(ARQUIVO_TABELA.read_text(encoding="utf-8")).get("dias", {})
    except Exception:
        return {}


def abrirPreProcessamento(rotulos=DIAS, automatico=False):
    """Abre a tela de pré-processamento e copia os dias pedidos.

    Manual (botão do app): fecha o navegador só se tudo foi copiado e conferido; com avisos, fica aberto.
    Automático (aviso agendado): preserva os outros dias, espera menos pelo login e sempre fecha o navegador.
    Devolve os resultados dos dias lidos."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    with sync_playwright() as gerenciador_playwright:
        opcoes = dict(user_data_dir=str(PERFIL_NAVEGADOR), headless=False, no_viewport=True)
        try:
            contexto = gerenciador_playwright.chromium.launch_persistent_context(channel="chrome", **opcoes)
        except Exception:
            contexto = gerenciador_playwright.chromium.launch_persistent_context(**opcoes)  # Chromium do Playwright

        dias = carregarDiasGravados() if automatico else {}
        gravarArquivo(dias, concluido=False)  # limpa a leitura anterior; a página mostra "buscando"
        pagina_atual = contexto.pages[0] if contexto.pages else contexto.new_page()
        pagina_atual.goto(URL_PRE_PROCESSAMENTO)

        # O login termina quando o menu "Cockpit" aparece; então abre o menu e vai em Pré-Processamento
        cockpit = pagina_atual.locator('p-accordion-header:has-text("Cockpit")').first
        cockpit.wait_for(state="visible", timeout=(TEMPO_LOGIN_AUTOMATICO if automatico else TEMPO_MAX_LOGIN) * 1000)
        esperarCarregar(pagina_atual)
        cockpit.click()
        pagina_atual.wait_for_timeout(800)  # animação do menu
        pagina_atual.locator('a.sidemenu-link[href="/pre-processamento"]').first.click()

        todos_ok = True
        lidos = {}
        for rotulo in rotulos:
            try:
                data = pagina_atual.locator("button.btn-atalho-data", has_text=rotulo).first.locator(".btn-atalho-data-data").inner_text().strip()
            except Exception:
                data = ""  # só enfeita a mensagem do Slack
            try:
                dias[rotulo] = processarDia(pagina_atual, contexto, rotulo, PlaywrightTimeoutError)
            except Exception as erro:  # um dia com problema não impede o próximo nem deixa a página "buscando" para sempre
                print(f"{rotulo}: erro durante a leitura: {erro}", flush=True)
                dias[rotulo] = resultadoDia("erro", detalhe=str(erro).splitlines()[0][:300])
            dias[rotulo]["data"] = data
            lidos[rotulo] = dias[rotulo]
            gravarArquivo(dias, concluido=rotulo == rotulos[-1])  # a página atualiza a cada dia pronto
            todos_ok = todos_ok and resultadoConferido(dias, rotulo)

        if todos_ok or automatico:
            contexto.close()  # tudo copiado e conferido (ou rodando sozinho): fecha; o login fica salvo no perfil
        else:
            contexto.wait_for_event("close", timeout=0)  # avisos e falhas: fica aberto para você ver a tela
        return lidos


if __name__ == "__main__":
    abrirPreProcessamento()
