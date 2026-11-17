"""Autenticador (2FA por TOTP): gera o segredo e o QR code, cifra o segredo e confere o código de 6 dígitos.

Compatível com Google Authenticator, Microsoft Authenticator, Authy etc. O segredo de cada usuário fica em tb_usuario_2fa,
cifrado com uma chave derivada do PORTAL_SEGREDO (a mesma proteção das senhas): só o banco não basta para usar o segredo.
"""
import base64
import hashlib
import io

import pyotp
import qrcode
from cryptography.fernet import Fernet, InvalidToken

EMISSOR = "Portal Automações"
JANELA = 1  # aceita o código anterior e o seguinte (±30 s): tolera diferença de relógio do celular


def _fernet(ds_segredo_servidor):
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"totp|" + ds_segredo_servidor).digest()))


def novoSegredo():
    return pyotp.random_base32()


def cifrar(ds_segredo, ds_segredo_servidor):
    return _fernet(ds_segredo_servidor).encrypt(ds_segredo.encode()).decode()


def decifrar(ds_cifrado, ds_segredo_servidor):
    try:
        return _fernet(ds_segredo_servidor).decrypt(ds_cifrado.encode()).decode()
    except InvalidToken:
        return None


def uriProvisionamento(ds_segredo, nm_usuario):
    return pyotp.TOTP(ds_segredo).provisioning_uri(name=nm_usuario, issuer_name=EMISSOR)


def qrPng(ds_segredo, nm_usuario):
    buffer = io.BytesIO()
    qrcode.make(uriProvisionamento(ds_segredo, nm_usuario)).save(buffer, format="PNG")
    return buffer.getvalue()


def codigoConfere(ds_segredo, ds_codigo):
    ds_codigo = "".join(ch for ch in (ds_codigo or "") if ch.isdigit())
    return len(ds_codigo) == 6 and pyotp.TOTP(ds_segredo).verify(ds_codigo, valid_window=JANELA)
