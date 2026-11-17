"""Inicia o Portal TAG pelo venv do projeto (pasta irmã da pasta de código).

Cria o venv se não existir, instala as bibliotecas do requirements.txt e sobe o Streamlit.
Ambiente: variável APP_ENV (local | hom | prd); sem ela, usa local.
"""
import glob
import os
import subprocess
import sys
import venv

pasta_codigo = os.path.dirname(os.path.abspath(__file__))
pasta_venv = os.path.join(os.path.dirname(pasta_codigo), "venv")
arquivo_requirements = os.path.join(pasta_codigo, "requirements.txt")
python_venv = os.path.join(pasta_venv, "Scripts" if os.name == "nt" else "bin", "python.exe" if os.name == "nt" else "python")


def executar(*lista_argumentos):
    return subprocess.call([python_venv, *lista_argumentos], cwd=pasta_codigo)


def chromiumInstalado():
    pasta_base = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "ms-playwright"
    )
    return bool(glob.glob(os.path.join(pasta_base, "chromium-*")))


def bibliotecasPrincipaisOk():
    """True se o venv já tem o essencial instalado (mesmo que o pip não consiga aplicar as versões fixadas)."""
    return executar("-c", "import streamlit, pandas, mysql.connector, decouple") == 0


def erro():
    print("\nFalha na instalação. Verifique a internet e rode novamente.")
    return 1


def main():
    if sys.version_info[:2] != (3, 10):
        print(f"Atenção: o padrão da TAG usa Python 3.10.9 e esta máquina tem {sys.version.split()[0]}.")
        print("As versões fixadas no requirements.txt (ex.: pandas 1.5.3) podem não instalar. Peça o Python 3.10.9 à TI.")

    if not os.path.exists(python_venv):
        print(f"Criando ambiente virtual em {pasta_venv}...")
        venv.create(pasta_venv, with_pip=True)

    print("Conferindo bibliotecas...")
    if executar("-m", "pip", "install", "-q", "-r", arquivo_requirements) != 0:
        if not bibliotecasPrincipaisOk():
            return erro()
        print("Aviso: o pip não aplicou as versões fixadas (comum fora do Python 3.10); seguindo com as já instaladas.")

    if not chromiumInstalado():
        print("Instalando Chromium do Playwright...")
        if executar("-m", "playwright", "install", "chromium") != 0:
            return erro()

    os.environ.setdefault("APP_ENV", "local")
    return executar("-m", "streamlit", "run", "main.py", "--browser.gatherUsageStats", "false")


if __name__ == "__main__":
    codigo = main()
    if codigo:
        input("\nPressione Enter para sair...")
    sys.exit(codigo)
