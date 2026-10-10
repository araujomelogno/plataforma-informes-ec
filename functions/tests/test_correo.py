import smtplib

import pytest

from portal import correo


class ConexionFalsa:
    def __init__(self, errores):
        self.errores = errores
        self.enviados = []

    def login(self, usuario, clave):
        if self.errores:
            raise self.errores.pop(0)

    def send_message(self, msg):
        self.enviados.append(msg)

    def quit(self):
        pass


def _ws(errores, **kw):
    conexion = ConexionFalsa(errores)
    ws = correo.Workspace("clave-secreta", smtp=lambda *a: conexion,
                          esperar=lambda s: None, **kw)
    return ws, conexion


def test_envia_con_remitente_y_reply_to():
    ws, conexion = _ws([])
    r = ws.enviar("a@b.com", "Asunto", "Texto", nombre="Equipos", reply_to="r@e.com")
    assert r["intentos"] == 1
    msg = conexion.enviados[0]
    assert msg["From"] == "Equipos <notificaciones@equipos.com.uy>"
    assert msg["Reply-To"] == "r@e.com"


def test_credencial_rechazada_no_se_reintenta_ni_expone_la_clave():
    ws, _ = _ws([smtplib.SMTPAuthenticationError(535, b"bad")])
    with pytest.raises(correo.ErrorEnvio) as e:
        ws.enviar("a@b.com", "A", "T")
    assert "Workspace rechazó la credencial" in e.value.motivo
    assert "clave-secreta" not in e.value.motivo
    assert e.value.intentos == 1


def test_fallo_transitorio_se_reintenta():
    ws, conexion = _ws([smtplib.SMTPServerDisconnected("x")])
    r = ws.enviar("a@b.com", "A", "T")
    assert r["intentos"] == 2 and len(conexion.enviados) == 1


def test_sin_clave_falla_sin_intentar():
    ws = correo.Workspace("")
    with pytest.raises(correo.ErrorEnvio) as e:
        ws.enviar("a@b.com", "A", "T")
    assert "SMTP_PASSWORD" in e.value.motivo and e.value.intentos == 0
