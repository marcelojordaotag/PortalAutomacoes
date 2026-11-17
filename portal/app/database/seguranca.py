"""Acesso ao banco para o login do portal: usuários, sessões, dispositivos e log de acessos.

As funções devolvem e recebem as MESMAS estruturas (dicts com os mesmos campos e formatos de data em texto) que o
código de app/seguranca já usava quando tudo ficava em JSON. Erros de banco sobem como exceção: quem chama decide.
"""
import json
from datetime import datetime, timedelta

from app.database.db import abrirTransacao, consultarTodos, consultarUm


def _textoIso(dt_valor, separador="T"):
    return dt_valor.isoformat(sep=separador, timespec="seconds") if dt_valor else None


def _dataDoTexto(tx_data):
    return datetime.fromisoformat(tx_data) if tx_data else None


def _jsonOuNulo(valor):
    if valor is None:
        return None
    return json.loads(valor) if isinstance(valor, (str, bytes)) else valor


# ---------------------------------------------------------------- usuários
def _usuarioDoBanco(linha):
    dic_usuario = {
        "usuario": linha["nm_usuario"], "nome": linha["nm_nome"], "perfil": linha["nm_perfil"], "ativo": bool(linha["ic_ativo"]),
        "apps": _jsonOuNulo(linha["js_apps"]), "salt": linha["ds_salt"], "hash": linha["ds_hash"],
        "iteracoes": linha["qt_iteracoes"], "pimenta": bool(linha["ic_pimenta"]), "trocar_senha": bool(linha["ic_trocar_senha"]),
        "falhas": linha["qt_falhas"], "bloqueios": linha["qt_bloqueios"], "bloqueado_ate": _textoIso(linha["dt_bloqueado_ate"]),
        "criado_em": _textoIso(linha["dt_criado"], " "), "ultimo_acesso": _textoIso(linha["dt_ultimo_acesso"], " "),
    }
    dic_bloqueio = _jsonOuNulo(linha["js_bloqueio_dispositivo"])
    if dic_bloqueio:
        dic_usuario["bloqueio_dispositivo"] = dic_bloqueio
    return dic_usuario


def carregarUsuarios():
    return [_usuarioDoBanco(linha) for linha in consultarTodos("SELECT * FROM portal_tb_usuario ORDER BY dt_criado, nm_usuario")]


def salvarUsuarios(lista_usuarios):
    """A lista passa a ser a verdade: contas que não estão nela são apagadas (mesma regra de quando era o arquivo)."""
    sql_gravar = """
        INSERT INTO portal_tb_usuario (nm_usuario, nm_nome, nm_perfil, ic_ativo, js_apps, ds_salt, ds_hash, qt_iteracoes, ic_pimenta,
                                ic_trocar_senha, qt_falhas, qt_bloqueios, dt_bloqueado_ate, js_bloqueio_dispositivo, dt_criado, dt_ultimo_acesso)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE nm_nome=VALUES(nm_nome), nm_perfil=VALUES(nm_perfil), ic_ativo=VALUES(ic_ativo), js_apps=VALUES(js_apps),
            ds_salt=VALUES(ds_salt), ds_hash=VALUES(ds_hash), qt_iteracoes=VALUES(qt_iteracoes), ic_pimenta=VALUES(ic_pimenta),
            ic_trocar_senha=VALUES(ic_trocar_senha), qt_falhas=VALUES(qt_falhas), qt_bloqueios=VALUES(qt_bloqueios),
            dt_bloqueado_ate=VALUES(dt_bloqueado_ate), js_bloqueio_dispositivo=VALUES(js_bloqueio_dispositivo),
            dt_criado=VALUES(dt_criado), dt_ultimo_acesso=VALUES(dt_ultimo_acesso)"""
    with abrirTransacao() as cursor:
        cursor.execute("SELECT nm_usuario FROM portal_tb_usuario")
        conjunto_existentes = {linha["nm_usuario"] for linha in cursor.fetchall()}
        for usuario in lista_usuarios:
            cursor.execute(sql_gravar, (
                usuario["usuario"], usuario["nome"], usuario["perfil"], int(usuario.get("ativo", True)),
                json.dumps(usuario["apps"], ensure_ascii=False) if usuario.get("apps") is not None else None,
                usuario["salt"], usuario["hash"], int(usuario.get("iteracoes", 0)), int(bool(usuario.get("pimenta"))),
                int(bool(usuario.get("trocar_senha"))), int(usuario.get("falhas", 0)), int(usuario.get("bloqueios", 0)),
                _dataDoTexto(usuario.get("bloqueado_ate")),
                json.dumps(usuario["bloqueio_dispositivo"], ensure_ascii=False) if usuario.get("bloqueio_dispositivo") else None,
                _dataDoTexto(usuario.get("criado_em")), _dataDoTexto(usuario.get("ultimo_acesso")),
            ))
        for nm_usuario in conjunto_existentes - {usuario["usuario"] for usuario in lista_usuarios}:
            cursor.execute("DELETE FROM portal_tb_usuario WHERE nm_usuario=%s", (nm_usuario,))
            cursor.execute("DELETE FROM portal_tb_usuario_2fa WHERE nm_usuario=%s", (nm_usuario,))
            cursor.execute("DELETE FROM portal_tb_acesso_log WHERE nm_usuario=%s", (nm_usuario,))


# ---------------------------------------------------------------- autenticador (2FA / TOTP)
def buscarSegredo2fa(nm_usuario):
    linha = consultarUm("SELECT ds_segredo FROM portal_tb_usuario_2fa WHERE nm_usuario=%s", (nm_usuario,))
    return linha["ds_segredo"] if linha else None


def gravarSegredo2fa(nm_usuario, ds_segredo):
    with abrirTransacao() as cursor:
        cursor.execute("REPLACE INTO portal_tb_usuario_2fa (nm_usuario, ds_segredo, dt_criado) VALUES (%s,%s,%s)",
                       (nm_usuario, ds_segredo, datetime.now()))


def removerSegredo2fa(nm_usuario):
    with abrirTransacao() as cursor:
        cursor.execute("DELETE FROM portal_tb_usuario_2fa WHERE nm_usuario=%s", (nm_usuario,))


# ---------------------------------------------------------------- sessões (token do navegador)
def _sessaoDoBanco(linha):
    return {"hash": linha["ds_hash"], "usuario": linha["nm_usuario"], "criado_em": _textoIso(linha["dt_criado"]),
            "expira_em": _textoIso(linha["dt_expira"])}


def criarSessao(ds_hash, nm_usuario, tx_criado, tx_expira):
    with abrirTransacao() as cursor:
        cursor.execute("DELETE FROM portal_tb_sessao WHERE dt_expira <= %s", (datetime.now(),))  # descarta as expiradas
        cursor.execute("INSERT INTO portal_tb_sessao (ds_hash, nm_usuario, dt_criado, dt_expira) VALUES (%s,%s,%s,%s)",
                       (ds_hash, nm_usuario, _dataDoTexto(tx_criado), _dataDoTexto(tx_expira)))


def buscarSessao(ds_hash):
    lista_linhas = consultarTodos("SELECT * FROM portal_tb_sessao WHERE ds_hash=%s", (ds_hash,))
    return _sessaoDoBanco(lista_linhas[0]) if lista_linhas else None


def renovarSessaoBanco(ds_hash, tx_expira):
    with abrirTransacao() as cursor:
        cursor.execute("UPDATE portal_tb_sessao SET dt_expira=%s WHERE ds_hash=%s", (_dataDoTexto(tx_expira), ds_hash))


def removerSessao(ds_hash):
    with abrirTransacao() as cursor:
        cursor.execute("DELETE FROM portal_tb_sessao WHERE ds_hash=%s", (ds_hash,))


def removerSessoesUsuario(nm_usuario):
    with abrirTransacao() as cursor:
        cursor.execute("DELETE FROM portal_tb_sessao WHERE nm_usuario=%s", (nm_usuario,))


# ---------------------------------------------------------------- dispositivos (duas contas no mesmo computador)
def listarDispositivos():
    return [{"usuario": linha["nm_usuario"], "id": linha["ds_dispositivo"], "ip": linha["ds_ip"] or "", "host": linha["nm_host"] or "",
             "visto_em": _textoIso(linha["dt_visto"], " ")}
            for linha in consultarTodos("SELECT * FROM portal_tb_dispositivo")]


def registrarDispositivo(nm_usuario, ds_dispositivo, ds_ip, nm_host, tx_visto):
    with abrirTransacao() as cursor:
        cursor.execute(
            """INSERT INTO portal_tb_dispositivo (nm_usuario, ds_dispositivo, ds_ip, nm_host, dt_visto) VALUES (%s,%s,%s,%s,%s)
               ON DUPLICATE KEY UPDATE ds_ip=VALUES(ds_ip), nm_host=VALUES(nm_host), dt_visto=VALUES(dt_visto)""",
            (nm_usuario, ds_dispositivo, ds_ip, nm_host, _dataDoTexto(tx_visto)))


def removerDispositivosUsuario(nm_usuario):
    with abrirTransacao() as cursor:
        cursor.execute("DELETE FROM portal_tb_dispositivo WHERE nm_usuario=%s", (nm_usuario,))


# ---------------------------------------------------------------- log de acessos
def gravarAcesso(nm_evento, nm_usuario, ds_detalhe, ds_ip, nm_computador):
    with abrirTransacao() as cursor:
        cursor.execute(
            "INSERT INTO portal_tb_acesso_log (dt_evento, nm_evento, nm_usuario, ds_detalhe, ds_ip, nm_computador) VALUES (%s,%s,%s,%s,%s,%s)",
            (datetime.now().replace(microsecond=0), nm_evento, nm_usuario, ds_detalhe, ds_ip, nm_computador))


def apagarAcessosAntigos(qt_dias):
    with abrirTransacao() as cursor:
        cursor.execute("DELETE FROM portal_tb_acesso_log WHERE dt_evento < %s", (datetime.now() - timedelta(days=qt_dias),))


def listarAcessos(qt_dias):
    """Eventos dos últimos qt_dias dias, do mais recente para o mais antigo, no formato antigo do log."""
    lista_linhas = consultarTodos("SELECT * FROM portal_tb_acesso_log WHERE dt_evento >= %s ORDER BY dt_evento DESC, id_acesso DESC",
                                  (datetime.now() - timedelta(days=qt_dias),))
    return [{"quando": _textoIso(linha["dt_evento"], " "), "evento": linha["nm_evento"], "usuario": linha["nm_usuario"] or "",
             "detalhe": linha["ds_detalhe"] or "", "ip": linha["ds_ip"] or "", "computador": linha["nm_computador"] or ""}
            for linha in lista_linhas]
