"""CRAVA COTAS, aba Britech: abre o Chrome comum na tela de login da Britech para o usuário entrar.

O Chrome abre sem Playwright, só com a porta de depuração ligada. O login é manual e o navegador fica aberto;
depois o Playwright pode se conectar a ele (conectarBritech) para baixar o item, sem abrir outro navegador.
"""
import os
import subprocess
from pathlib import Path

URL_BRITECH = "https://tag.britech.com.br/PAS/Login/LoginInit.aspx?ReturnUrl=%2fPAS%2f"
PERFIL_NAVEGADOR = Path.home() / ".britech_perfil"  # guarda o login entre execuções
PORTA_DEPURACAO = 9223
CAMINHOS_CHROME = [
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
]


def abrirBritech():
    """Abre o Chrome comum na tela de login. Devolve False se não achar o Chrome instalado."""
    chrome = next((caminho for caminho in CAMINHOS_CHROME if caminho.exists()), None)
    if chrome is None:
        return False
    subprocess.Popen([str(chrome), f"--remote-debugging-port={PORTA_DEPURACAO}",
                      f"--user-data-dir={PERFIL_NAVEGADOR}", URL_BRITECH])
    return True


def conectarBritech(gerenciador_playwright):
    """Conecta o Playwright ao Chrome aberto por abrirBritech e devolve o contexto (com a sessão já logada)."""
    navegador = gerenciador_playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{PORTA_DEPURACAO}")
    return navegador.contexts[0]
