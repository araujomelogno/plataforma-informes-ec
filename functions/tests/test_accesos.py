import smtplib

import pytest

from portal import accesos, correo, plantillas
from tests.conftest import Actor, MailerFalso, requiere_emuladores

pytestmark = requiere_emuladores


def _log(db):
    return [d.to_dict() for d in db.collection("mailLog").stream()]


def test_alta_crea_cuenta_ficha_y_manda_bienvenida(entorno, admin, mailer):
    db, cuentas = entorno
    r = accesos.crear_usuario(db, cuentas, mailer, accesos.exigir_admin(db, admin),
                              "  Cliente@Empresa.com ")
    assert r["estado"] == "creado" and r["correo"]["enviado"]
    assert "enlace" not in r  # el correo salió: el enlace no vuelve
    cuenta = cuentas.get_user_by_email("cliente@empresa.com")
    ficha = db.collection("users").document(cuenta.uid).get().to_dict()
    assert ficha["role"] == "user"
    assert ficha["creadoPor"] == "admin@equipos.com.uy"
    assert ficha["creadoPorUid"] == admin.uid
    assert "createdAt" in ficha
    [enviado] = mailer.enviados
    assert enviado["destino"] == "cliente@empresa.com"
    assert "resetPassword" in enviado["texto"] or "oobCode" in enviado["texto"]
    [fila] = _log(db)
    assert fila["estado"] == "enviado" and fila["tipo"] == plantillas.BIENVENIDA
    # Ni el enlace ni nada parecido a una clave queda en Firestore.
    assert "oobCode" not in str(fila) and "enlace" not in fila


def test_no_admin_recibe_permission_denied_y_no_se_crea_nada(entorno, mailer):
    db, cuentas = entorno
    cuenta = cuentas.create_user(email="cliente@x.com", password="secreto123")
    db.collection("users").document(cuenta.uid).set({"email": "cliente@x.com", "role": "user"})
    with pytest.raises(accesos.ErrorPortal) as e:
        accesos.exigir_admin(db, Actor(cuenta.uid, "cliente@x.com"))
    assert e.value.codigo == "permission-denied"
    with pytest.raises(accesos.ErrorPortal) as e:
        accesos.exigir_admin(db, None)
    assert e.value.codigo == "unauthenticated"


def test_email_existente_no_crea_ni_toca_la_clave(entorno, admin, mailer):
    db, cuentas = entorno
    actor = accesos.exigir_admin(db, admin)
    accesos.crear_usuario(db, cuentas, mailer, actor, "cliente@empresa.com")
    antes = cuentas.get_user_by_email("cliente@empresa.com")
    r = accesos.crear_usuario(db, cuentas, mailer, actor, "cliente@empresa.com")
    assert r["estado"] == "ya_existia" and not r["fichaRecreada"]
    assert len(mailer.enviados) == 1  # solo el del primer alta
    despues = cuentas.get_user_by_email("cliente@empresa.com")
    assert antes.tokens_valid_after_timestamp == despues.tokens_valid_after_timestamp


def test_cuenta_sin_ficha_se_recrea(entorno, admin, mailer):
    db, cuentas = entorno
    cuentas.create_user(email="borrado@empresa.com", password="secreto123")
    r = accesos.crear_usuario(db, cuentas, mailer, accesos.exigir_admin(db, admin),
                              "borrado@empresa.com")
    assert r["estado"] == "ya_existia" and r["fichaRecreada"]
    assert db.collection("users").document(r["uid"]).get().exists


def test_si_el_smtp_falla_el_alta_igual_queda_y_vuelve_el_enlace(entorno, admin):
    db, cuentas = entorno
    falla = correo.ErrorEnvio("Workspace rechazó la credencial (535).", False, 1)
    r = accesos.crear_usuario(db, cuentas, MailerFalso(error=falla),
                              accesos.exigir_admin(db, admin), "c@empresa.com")
    assert r["estado"] == "creado"
    assert not r["correo"]["enviado"]
    assert "Workspace rechazó la credencial" in r["correo"]["detalle"]
    assert r["enlace"].startswith("http")
    [fila] = _log(db)
    assert fila["estado"] == "fallido" and "535" in fila["motivo"]
    assert r["enlace"] not in str(fila)


def test_email_invalido(entorno, admin, mailer):
    db, cuentas = entorno
    with pytest.raises(accesos.ErrorPortal) as e:
        accesos.crear_usuario(db, cuentas, mailer, accesos.exigir_admin(db, admin), "no-es-email")
    assert e.value.codigo == "invalid-argument"


def test_reenviar_acceso_registra_quien_y_cuando(entorno, admin, mailer):
    db, cuentas = entorno
    actor = accesos.exigir_admin(db, admin)
    alta = accesos.crear_usuario(db, cuentas, mailer, actor, "c@empresa.com")
    r = accesos.reenviar_acceso(db, cuentas, mailer, actor, uid=alta["uid"])
    assert r["correo"]["enviado"]
    assert r["plantilla"] == plantillas.BIENVENIDA  # nunca ingresó
    ficha = db.collection("users").document(alta["uid"]).get().to_dict()
    assert ficha["reenvios"] == 1
    assert ficha["ultimoReenvio"]["porEmail"] == "admin@equipos.com.uy"
    assert len(mailer.enviados) == 2
    with pytest.raises(accesos.ErrorPortal) as e:
        accesos.reenviar_acceso(db, cuentas, mailer, actor, uid="no-existe")
    assert e.value.codigo == "not-found"


def test_restablecer_responde_igual_y_tiene_tope(entorno, admin, mailer):
    db, cuentas = entorno
    actor = accesos.exigir_admin(db, admin)
    accesos.crear_usuario(db, cuentas, mailer, actor, "c@empresa.com")
    mailer.enviados.clear()
    assert accesos.solicitar_restablecimiento(db, cuentas, mailer, "nadie@x.com") == {"ok": True}
    assert mailer.enviados == []
    for _ in range(5):
        assert accesos.solicitar_restablecimiento(db, cuentas, mailer, "C@empresa.com") == {"ok": True}
    assert len(mailer.enviados) == 3  # RESTABLECER_POR_HORA
    assert all("contraseña nueva" in m["asunto"] for m in mailer.enviados)


def test_info_y_prueba(entorno, admin, mailer):
    db, cuentas = entorno
    actor = accesos.exigir_admin(db, admin)
    info = accesos.info_correo(db, mailer)
    assert info["enviados24h"] == 0 and info["disponible"] == info["cupoDiario"]
    assert set(info["catalogo"]["claves"]) == set(plantillas.CLAVES)
    r = accesos.enviar_prueba(db, mailer, actor, plantillas.NUEVO_INFORME,
                              asunto="Probando {{informe}}", cuerpo="{{informe}}")
    assert r["correo"]["enviado"]
    assert mailer.enviados[-1]["asunto"].startswith("[PRUEBA] Probando")
    assert mailer.enviados[-1]["destino"] == "admin@equipos.com.uy"
    with pytest.raises(accesos.ErrorPortal):
        accesos.enviar_prueba(db, mailer, actor, plantillas.BIENVENIDA,
                              asunto="x", cuerpo="sin enlace")
    assert accesos.info_correo(db, mailer)["enviados24h"] == 1
