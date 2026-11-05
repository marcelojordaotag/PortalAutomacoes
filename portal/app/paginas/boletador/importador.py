"""Importação da base da TAG (boletador) via Playwright.

Roda como processo separado (`python importador.py`), chamado pelo app. Assim o Playwright
síncrono não convive com o event loop do Streamlit, e o processo abre sem carregar
streamlit/pandas/plotly.

Códigos de saída: 0 ok | 2 tempo esgotado no login | 3 erro ou navegador fechado.
O caminho do arquivo baixado é impresso na saída com o prefixo MARCADOR_ARQUIVO.
"""
import os
import sys
from pathlib import Path

URL_BOLETADOR = os.environ.get("BOLETADOR_PRC_URL", "")
PERFIL_NAVEGADOR = Path.home() / ".boletador_perfil"  # guarda o login entre execuções
TEMPO_MAX_LOGIN = 300  # segundos esperando o usuário logar
PASTA_DESTINO = Path(__file__).resolve().parents[3] / "dados" / "boletador" / "downloads_boletador"
MARCADOR_ARQUIVO = "ARQUIVO::"  # o subprocesso imprime o caminho do arquivo com esse prefixo


def importarBase(url=None, data_inicial=None, data_final=None):
    """Abre o boletador, espera o login, navega até Ordens e baixa a base.

    Se `url` for informada, ela vale no lugar de BOLETADOR_PRC_URL.
    `data_inicial` e `data_final` (dd/mm/aaaa) preenchem o período da operação antes de exportar."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    with sync_playwright() as gerenciador_playwright:
        opcoes = dict(user_data_dir=str(PERFIL_NAVEGADOR), headless=False, no_viewport=True)
        try:
            contexto = gerenciador_playwright.chromium.launch_persistent_context(channel="chrome", **opcoes)
        except Exception:
            contexto = gerenciador_playwright.chromium.launch_persistent_context(**opcoes)  # Chromium do Playwright

        try:
            pagina_atual = contexto.pages[0] if contexto.pages else contexto.new_page()
            pagina_atual.goto(url or URL_BOLETADOR)

            # O login termina quando o ícone de menu aparece na tela
            icone_menu = pagina_atual.locator('i.material-icons[title="Menu"]')
            try:
                icone_menu.wait_for(state="visible", timeout=TEMPO_MAX_LOGIN * 1000)
            except PlaywrightTimeoutError:
                sys.exit(2)

            # Se uma URL específica foi pedida e o login redirecionou para outra tela, volta para ela
            if url and not pagina_atual.url.startswith(url):
                pagina_atual.goto(url)

            # Dá 3 segundos para o Angular carregar a tela inicial
            pagina_atual.wait_for_timeout(3000)

            download = pagina_atual.locator('button[title="Exportar"]').first

            # Se o botão Exportar não estiver na tela inicial, navega para Cadastros > Ordens
            if not download.is_visible():
                ordens = pagina_atual.locator('a:text-is("Ordens"):visible').first
                if not ordens.is_visible():  # só abre "Cadastros" se o submenu ainda estiver fechado
                    pagina_atual.locator("#itemCadastros").click()
                ordens.click()
                pagina_atual.wait_for_timeout(3000)  # Angular carregar a tabela

            # Preenche o período da operação, quando informado
            if data_inicial and data_final:
                campo_inicial = pagina_atual.locator("#dtOperacaoDe")
                campo_final = (
                    pagina_atual.locator('#dtOperacaoAte, input[name="dtOperacaoAte"]')
                    .or_(pagina_atual.locator('xpath=//label[contains(., "Período Final da Operação")]/following::input[1]'))
                    .first
                )
                for campo, valor in ((campo_inicial, data_inicial), (campo_final, data_final)):
                    campo.click()
                    campo.fill(valor)
                    campo.press("Enter")
                    pagina_atual.keyboard.press("Escape")  # fecha o calendário
                pagina_atual.locator("body").click(position={"x": 5, "y": 5})
                # Aplica o filtro, se a tela tiver botão de pesquisa
                pesquisar = pagina_atual.locator('button[title="Pesquisar"]').first
                if pesquisar.is_visible():
                    pesquisar.click()
                pagina_atual.wait_for_timeout(3000)

            # 1. Espera o botão Exportar (ícone archive) ficar visível
            download.wait_for(state="visible", timeout=15000)

            print("Botão encontrado! Tentando clicar via JavaScript...")

            # 2. Prepara o Playwright para o download
            with pagina_atual.expect_download(timeout=120000) as download_info:
                # 3. O clique via JavaScript (ignora qualquer bloqueio visual da tela)
                download.evaluate("botao => botao.click()")

            print("Clique funcionou! Aguardando o download terminar...")
            arquivo = download_info.value

            # 4. Espera a tela de loading sumir
            indicador_espera = pagina_atual.locator("#cover-spin")
            try:
                indicador_espera.wait_for(state="hidden", timeout=120000)
            except Exception:
                pass  # se der erro aqui, o loading já sumiu

            # 5. Salva o arquivo na pasta de destino
            PASTA_DESTINO.mkdir(parents=True, exist_ok=True)
            caminho_completo = PASTA_DESTINO / arquivo.suggested_filename
            arquivo.save_as(caminho_completo)

            # 6. Devolve o caminho para o app principal (lido pelo stdout)
            print(f"{MARCADOR_ARQUIVO}{caminho_completo}", flush=True)

        except SystemExit:
            raise
        except Exception as erro:
            print(f"Erro durante a execução do Playwright: {erro}", file=sys.stderr, flush=True)
            sys.exit(3)
        finally:
            try:
                contexto.close()  # fecha o navegador em qualquer cenário
            except Exception:
                pass


if __name__ == "__main__":
    argumentos = sys.argv[1:] + [None, None, None]
    importarBase(argumentos[0], argumentos[1], argumentos[2])
