import datetime

from portal import avisos, permisos, plantillas
from tests.conftest import requiere_emuladores

pytestmark = requiere_emuladores

T0 = datetime.datetime(2026, 10, 9, 12, 0, tzinfo=datetime.timezone.utc)


def _base(db, rol="user"):
    db.collection("users").document("u1").set({"email": "cliente@empresa.com", "role": rol})
    db.collection("folders").document("f1").set({"name": "Clientes", "parentId": None})
    db.collection("folders").document("f2").set({"name": "Oculta", "parentId": "f1", "clientVisible": False})
    for i in range(1, 6):
        db.collection("reports").document(f"r{i}").set({"name": f"Informe {i}", "folderId": "f2"})


def _acceso(db, ids, opciones=None, **extra):
    """Escribe `userAccess/u1`, recalcula y devuelve el acceso efectivo, que es lo
    que recibe el trigger de avisos."""
    datos = {"reportIds": ids, "options": opciones or {
        r: {"grantedByEmail": "admin@equipos.com.uy"} for r in ids}, **extra}
    db.collection("userAccess").document("u1").set(datos)
    return permisos.recalcular(db, "u1")[1]


def test_ids_nuevos():
    assert avisos.ids_nuevos({"reportIds": ["a"]}, {"reportIds": ["a", "b", "b"]}) == ["b"]
    assert avisos.ids_nuevos({}, {"reportIds": ["a"]}) == ["a"]
    assert avisos.ids_nuevos({"reportIds": ["a", "b"]}, {"reportIds": ["a"]}) == []


def test_listo_para_enviar():
    items = [(None, {"creadoEn": T0}), (None, {"creadoEn": T0 + datetime.timedelta(seconds=30)})]
    assert not avisos.listo_para_enviar(items, T0 + datetime.timedelta(minutes=1), 2)
    assert avisos.listo_para_enviar(items, T0 + datetime.timedelta(minutes=3), 2)


def test_habilitar_un_informe_manda_exactamente_un_correo(entorno, mailer):
    db, _ = entorno
    _base(db)
    despues = _acceso(db, ["r1"], {"r1": {"grantedByEmail": "admin@equipos.com.uy",
                                          "expiresAt": "2026-12-31"}})
    assert avisos.registrar_cambio(db, mailer, "ev1", "u1", {}, despues, ahora=T0) == ["r1"]
    # Reintento del mismo evento: no se vuelve a encolar.
    assert avisos.registrar_cambio(db, mailer, "ev1", "u1", {}, despues, ahora=T0) == []
    assert mailer.enviados == []  # todavía dentro de la ventana
    avisos.despachar(db, mailer, ahora=T0 + datetime.timedelta(minutes=3))
    [m] = mailer.enviados
    assert m["destino"] == "cliente@empresa.com"
    assert "Informe 1" in m["asunto"]
    assert "Carpeta: Clientes" in m["texto"]  # la carpeta oculta no se muestra
    assert "31/12/2026" in m["texto"]
    assert "admin@equipos.com.uy" in m["texto"]
    # Despachar de nuevo no repite.
    avisos.despachar(db, mailer, ahora=T0 + datetime.timedelta(minutes=10))
    assert len(mailer.enviados) == 1
    [fila] = [d.to_dict() for d in db.collection("mailLog").stream()]
    assert fila["estado"] == "enviado" and fila["reportId"] == "r1"


def test_quitar_o_cambiar_opciones_o_reasignar_no_avisa(entorno, mailer):
    db, _ = entorno
    _base(db)
    antes = {"reportIds": ["r1"], "options": {"r1": {}}}
    assert avisos.registrar_cambio(db, mailer, "e1", "u1", antes, {"reportIds": []}) == []
    assert avisos.registrar_cambio(db, mailer, "e2", "u1", antes,
                                   {"reportIds": ["r1"], "options": {"r1": {"noPrint": True}}}) == []
    assert avisos.registrar_cambio(db, mailer, "e3", "u1", antes, antes) == []


def test_admin_con_aviso_activado_recibe(entorno, mailer):
    db, _ = entorno
    _base(db, rol="admin")
    db.collection("config").document("correos").set({"ventanaAgrupadoMin": 0})
    despues = _acceso(db, ["r1"], {"r1": {"notificar": True, "grantedByEmail": "otro@equipos.com.uy"}})
    assert avisos.registrar_cambio(db, mailer, "e1", "u1", {}, despues) == ["r1"]
    [m] = mailer.enviados
    assert m["destino"] == "cliente@empresa.com" and "Informe 1" in m["asunto"]


def test_admin_sin_aviso_no_recibe_ni_registra(entorno, mailer):
    db, _ = entorno
    _base(db, rol="admin")
    db.collection("config").document("correos").set({"ventanaAgrupadoMin": 0})
    despues = _acceso(db, ["r1"], {"r1": {"notificar": False}})
    assert avisos.registrar_cambio(db, mailer, "e1", "u1", {}, despues) == []
    assert mailer.enviados == []
    assert list(db.collection("mailLog").stream()) == []


def test_no_notificar(entorno, mailer):
    db, _ = entorno
    _base(db)
    despues = _acceso(db, ["r1"], {"r1": {"notificar": False}})
    assert avisos.registrar_cambio(db, mailer, "e1", "u1", {}, despues) == []
    avisos.despachar(db, mailer, ahora=T0 + datetime.timedelta(hours=1))
    assert mailer.enviados == []
    assert list(db.collection("mailLog").stream()) == []  # ni siquiera un intento


def test_cinco_informes_en_30_segundos_un_solo_correo(entorno, mailer):
    db, _ = entorno
    _base(db)
    ids = []
    for i in range(1, 6):
        antes = {"reportIds": list(ids)}
        ids.append(f"r{i}")
        despues = _acceso(db, list(ids))
        avisos.registrar_cambio(db, mailer, f"ev{i}", "u1", antes, despues,
                                ahora=T0 + datetime.timedelta(seconds=6 * i))
    avisos.despachar(db, mailer, ahora=T0 + datetime.timedelta(minutes=1))
    assert mailer.enviados == []
    avisos.despachar(db, mailer, ahora=T0 + datetime.timedelta(minutes=3))
    [m] = mailer.enviados
    for i in range(1, 6):
        assert f"• Informe {i}" in m["texto"]


def test_tildar_y_destildar_no_manda_nada(entorno, mailer):
    db, _ = entorno
    _base(db)
    despues = _acceso(db, ["r1"])
    avisos.registrar_cambio(db, mailer, "e1", "u1", {}, despues, ahora=T0)
    _acceso(db, [])  # el admin lo destildó enseguida
    avisos.despachar(db, mailer, ahora=T0 + datetime.timedelta(minutes=3))
    assert mailer.enviados == []
    [fila] = [d.to_dict() for d in db.collection("mailLog").stream()]
    assert fila["estado"] == "omitido"


def test_ventana_cero_manda_en_el_momento_y_plantilla_apagada_omite(entorno, mailer):
    db, _ = entorno
    _base(db)
    db.collection("config").document("correos").set({"ventanaAgrupadoMin": 0})
    avisos.registrar_cambio(db, mailer, "e1", "u1", {}, _acceso(db, ["r1"]))
    assert len(mailer.enviados) == 1
    db.collection("config").document("correos").set(
        {"ventanaAgrupadoMin": 0, "plantillas": {plantillas.NUEVO_INFORME: {"activo": False}}})
    avisos.registrar_cambio(db, mailer, "e2", "u1", {"reportIds": ["r1"]}, _acceso(db, ["r1", "r2"]))
    assert len(mailer.enviados) == 1
    estados = sorted(d.to_dict()["estado"] for d in db.collection("mailLog").stream())
    assert estados == ["enviado", "omitido"]


def test_un_fallo_de_envio_no_revierte_el_permiso(entorno):
    from tests.conftest import MailerFalso
    from portal import correo
    db, _ = entorno
    _base(db)
    db.collection("config").document("correos").set({"ventanaAgrupadoMin": 0})
    mailer = MailerFalso(error=correo.ErrorEnvio("caído", True, 3))
    avisos.registrar_cambio(db, mailer, "e1", "u1", {}, _acceso(db, ["r1"]))
    assert db.collection("userAccess").document("u1").get().to_dict()["reportIds"] == ["r1"]
    [fila] = [d.to_dict() for d in db.collection("mailLog").stream()]
    assert fila["estado"] == "fallido" and fila["intentos"] == 3


# ── Aviso en el momento (panel → avisarAsignacion) ──

def _acceso_con_fecha(db, ids, granted="2026-10-26T12:00:00.000Z", notificar=True):
    opciones = {r: {"grantedByEmail": "admin@equipos.com.uy", "grantedAt": granted,
                    "notificar": notificar} for r in ids}
    datos = {"reportIds": ids, "options": opciones}
    db.collection("userAccess").document("u1").set(datos)
    return permisos.recalcular(db, "u1")[1]


def test_panel_manda_en_el_momento_y_el_trigger_no_duplica(entorno, mailer):
    db, _ = entorno
    _base(db)
    despues = _acceso_con_fecha(db, ["r1", "r2"])
    r = avisos.avisar_ahora(db, mailer, "u1", ["r1", "r2"], ahora=T0)
    assert r["estado"] == "enviado" and sorted(r["informes"]) == ["r1", "r2"]
    [m] = mailer.enviados
    assert "• Informe 1" in m["texto"] and "• Informe 2" in m["texto"]
    # El trigger llega después (mismo grantedAt → mismo id): no encola ni manda.
    assert avisos.registrar_cambio(db, mailer, "ev9", "u1", {}, despues, ahora=T0) == []
    avisos.despachar(db, mailer, ahora=T0 + datetime.timedelta(hours=1))
    assert len(mailer.enviados) == 1
    # Llamar de nuevo desde el panel tampoco repite.
    assert avisos.avisar_ahora(db, mailer, "u1", ["r1"], ahora=T0)["estado"] == "ya_enviado"
    assert len(mailer.enviados) == 1


def test_trigger_primero_y_panel_despues_un_solo_correo(entorno, mailer):
    db, _ = entorno
    _base(db)
    despues = _acceso_con_fecha(db, ["r1"])
    assert avisos.registrar_cambio(db, mailer, "ev1", "u1", {}, despues, ahora=T0) == ["r1"]
    r = avisos.avisar_ahora(db, mailer, "u1", ["r1"], ahora=T0)
    assert r["estado"] == "enviado"
    avisos.despachar(db, mailer, ahora=T0 + datetime.timedelta(hours=1))
    assert len(mailer.enviados) == 1


def test_reasignar_mas_tarde_es_otro_aviso(entorno, mailer):
    db, _ = entorno
    _base(db)
    _acceso_con_fecha(db, ["r1"], granted="2026-10-26T12:00:00.000Z")
    avisos.avisar_ahora(db, mailer, "u1", ["r1"], ahora=T0)
    _acceso_con_fecha(db, ["r1"], granted="2026-10-27T09:00:00.000Z")
    avisos.avisar_ahora(db, mailer, "u1", ["r1"], ahora=T0)
    assert len(mailer.enviados) == 2


def test_panel_respeta_no_avisar_y_accesos_quitados(entorno, mailer):
    db, _ = entorno
    _base(db)
    _acceso_con_fecha(db, ["r1"], notificar=False)
    assert avisos.avisar_ahora(db, mailer, "u1", ["r1"])["estado"] == "sin_aviso"
    _acceso_con_fecha(db, [])
    assert avisos.avisar_ahora(db, mailer, "u1", ["r1"])["estado"] == "sin_aviso"
    assert mailer.enviados == []
    assert list(db.collection("mailLog").stream()) == []


def test_panel_con_smtp_caido_informa_fallido(entorno):
    from portal import correo
    from tests.conftest import MailerFalso
    db, _ = entorno
    _base(db)
    _acceso_con_fecha(db, ["r1"])
    r = avisos.avisar_ahora(db, MailerFalso(error=correo.ErrorEnvio("caído", True, 3)), "u1", ["r1"])
    assert r["estado"] == "fallido" and r["detalle"] == "caído"
    assert db.collection("userAccess").document("u1").get().to_dict()["reportIds"] == ["r1"]


# ── Avisos vencidos y descarte ──

def test_avisos_viejos_vencen_y_no_se_suman_a_uno_nuevo(entorno, mailer):
    db, _ = entorno
    _base(db)
    viejo = _acceso_con_fecha(db, ["r1"], granted="2026-10-20T12:00:00.000Z")
    # Encolado hace 4 días por el trigger y nunca enviado (programada caída).
    avisos.registrar_cambio(db, mailer, "ev1", "u1", {}, viejo,
                            ahora=T0 - datetime.timedelta(days=4))
    # Hoy se le asigna otro informe desde el panel: el correo NO incluye r1.
    db.collection("userAccess").document("u1").update({
        "reportIds": ["r1", "r2"],
        "options.r2": {"grantedAt": "2026-10-26T12:00:00.000Z", "notificar": True}})
    permisos.recalcular(db, "u1")
    r = avisos.avisar_ahora(db, mailer, "u1", ["r2"], ahora=T0)
    assert r["estado"] == "enviado" and r["informes"] == ["r2"]
    [m] = mailer.enviados
    assert "Informe 1" not in m["texto"]
    estados = {d.to_dict()["reportId"]: d.to_dict()["estado"]
               for d in db.collection("avisosPendientes").stream()}
    assert estados == {"r1": "vencido", "r2": "enviado"}


def test_la_programada_no_manda_avisos_vencidos(entorno, mailer):
    db, _ = entorno
    _base(db)
    viejo = _acceso_con_fecha(db, ["r1", "r2"])
    avisos.registrar_cambio(db, mailer, "ev1", "u1", {}, viejo,
                            ahora=T0 - datetime.timedelta(days=4))
    assert avisos.despachar(db, mailer, ahora=T0) == []
    assert mailer.enviados == []


def test_descartar_pendientes(entorno, mailer):
    db, _ = entorno
    _base(db)
    avisos.registrar_cambio(db, mailer, "ev1", "u1", {}, _acceso(db, ["r1", "r2"]), ahora=T0)
    assert avisos.descartar_pendientes(db, {"uid": "a", "email": "admin@e.com"}) == {"descartados": 2}
    avisos.despachar(db, mailer, ahora=T0 + datetime.timedelta(minutes=5))
    assert mailer.enviados == []
    assert db.collection("userAccess").document("u1").get().to_dict()["reportIds"] == ["r1", "r2"]


# ── Carpetas asignadas (C8) ──

def _arbol_carpetas(db, n=5):
    """Clientes / Cliente X / Estudio 1 / Ola 2, con `n` informes en Ola 2."""
    db.collection("users").document("u1").set({"email": "cliente@empresa.com", "role": "user"})
    for fid, nombre, padre in (("c", "Clientes", None), ("x", "Cliente X", "c"),
                               ("e1", "Estudio 1", "x"), ("o2", "Ola 2", "e1")):
        db.collection("folders").document(fid).set({"name": nombre, "parentId": padre})
    for i in range(1, n + 1):
        db.collection("reports").document(f"r{i}").set({"name": f"Informe {i}", "folderId": "o2"})


def _carpeta(db, fid="e1", notificar=True, granted="2026-10-26T12:00:00.000Z", **extra):
    datos = {"folderIds": [fid], "folderOptions": {fid: {
        "grantedAt": granted, "grantedByEmail": "admin@equipos.com.uy", "notificar": notificar}}, **extra}
    db.collection("userAccess").document("u1").set(datos)


def test_asignar_carpeta_con_cinco_informes_un_correo(entorno, mailer):
    db, _ = entorno
    _arbol_carpetas(db)
    _carpeta(db)
    r = avisos.avisar_ahora(db, mailer, "u1", folder_id="e1", ahora=T0)
    assert r["estado"] == "enviado" and len(r["informes"]) == 5
    [m] = mailer.enviados
    for i in range(1, 6):
        assert f"• Informe {i}" in m["texto"]
    # La ruta arranca en la raíz del usuario: nunca "Clientes" ni "Cliente X".
    assert "carpeta: Estudio 1 / Ola 2" in m["texto"]
    assert "Cliente X" not in m["texto"] and "Clientes" not in m["texto"]
    # El trigger de accesoEfectivo llega después: mismo id (grantedAt de la carpeta), no duplica.
    efectivo = permisos.leer_acceso(db, "u1")
    assert avisos.registrar_cambio(db, mailer, "ev1", "u1", {}, efectivo, ahora=T0) == []
    avisos.despachar(db, mailer, ahora=T0 + datetime.timedelta(hours=1))
    assert len(mailer.enviados) == 1


def test_subir_tres_informes_a_la_carpeta_un_correo(entorno, mailer):
    db, _ = entorno
    _arbol_carpetas(db, n=0)
    _carpeta(db)
    antes = permisos.recalcular(db, "u1")[1]
    for i in range(1, 4):
        db.collection("reports").document(f"r{i}").set({"name": f"Informe {i}", "folderId": "o2"})
        permisos.al_cambiar_informe(db, f"r{i}", None, {"folderId": "o2"})
        despues = permisos.leer_acceso(db, "u1")
        avisos.registrar_cambio(db, mailer, f"ev{i}", "u1", antes, despues,
                                ahora=T0 + datetime.timedelta(seconds=20 * i))
        antes = despues
    avisos.despachar(db, mailer, ahora=T0 + datetime.timedelta(minutes=1))
    assert mailer.enviados == []
    avisos.despachar(db, mailer, ahora=T0 + datetime.timedelta(minutes=4))
    [m] = mailer.enviados
    for i in range(1, 4):
        assert f"• Informe {i}" in m["texto"]


def test_carpeta_sin_aviso_no_manda_nada(entorno, mailer):
    db, _ = entorno
    _arbol_carpetas(db)
    _carpeta(db, notificar=False)
    assert avisos.avisar_ahora(db, mailer, "u1", folder_id="e1", ahora=T0)["estado"] == "sin_aviso"
    efectivo = permisos.leer_acceso(db, "u1")
    assert avisos.registrar_cambio(db, mailer, "ev1", "u1", {}, efectivo, ahora=T0) == []
    db.collection("reports").document("r9").set({"name": "Informe 9", "folderId": "o2"})
    permisos.al_cambiar_informe(db, "r9", None, {"folderId": "o2"})
    assert avisos.registrar_cambio(db, mailer, "ev2", "u1", efectivo, permisos.leer_acceso(db, "u1"), ahora=T0) == []
    avisos.despachar(db, mailer, ahora=T0 + datetime.timedelta(hours=1))
    assert mailer.enviados == []
    assert list(db.collection("mailLog").stream()) == []


def test_directo_que_ademas_llega_por_carpeta_no_se_avisa_dos_veces(entorno, mailer):
    db, _ = entorno
    _arbol_carpetas(db, n=2)
    db.collection("userAccess").document("u1").set({"reportIds": ["r1"], "options": {
        "r1": {"grantedAt": "2026-10-20T12:00:00.000Z", "notificar": True}}})
    assert avisos.avisar_ahora(db, mailer, "u1", ["r1"], ahora=T0)["estado"] == "enviado"
    antes = permisos.leer_acceso(db, "u1")
    db.collection("userAccess").document("u1").update({
        "folderIds": ["e1"], "folderOptions": {"e1": {"grantedAt": "2026-10-26T12:00:00.000Z", "notificar": True}}})
    despues = permisos.recalcular(db, "u1")[1]
    assert despues["via"]["r1"] is None and despues["via"]["r2"] == "e1"
    r = avisos.avisar_ahora(db, mailer, "u1", folder_id="e1", ahora=T0)
    assert r["informes"] == ["r2"]
    assert avisos.registrar_cambio(db, mailer, "ev1", "u1", antes, despues, ahora=T0) == []
    assert len(mailer.enviados) == 2 and "Informe 1" not in mailer.enviados[1]["texto"]
