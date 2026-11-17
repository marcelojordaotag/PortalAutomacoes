"""IDs das carteiras Britech (antes: dados/britech/ids_cliente.xlsx). Usado pelas páginas Britech e Conciliação de Caixa."""
from app.database.db import consultarTodos


def listarIdsCarteiras():
    """Lista de IDs (str), na ordem de cadastro."""
    lista_linhas = consultarTodos("SELECT id_cliente FROM portal_tb_britech_carteira ORDER BY nr_ordem, id_cliente")
    return [linha["id_cliente"] for linha in lista_linhas]
