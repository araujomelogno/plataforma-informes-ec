from portal import permisos
from tests.conftest import requiere_emuladores

# Árbol de prueba:
#   Clientes (c) / Cliente X (x) / Estudio 1 (e1) / Ola 2 (o2) / Detalle (d)
#                               / Oculta (h, clientVisible False) / Sub (hs)
#   Clientes (c) / Cliente Y (y) / Estudio 3 (e3)
#   Suelta (s)
FOLDERS = {
    "c":  {"name": "Clientes", "parentId": None},
    "x":  {"name": "Cliente X", "parentId": "c"},
    "e1": {"name": "Estudio 1", "parentId": "x"},
    "o2": {"name": "Ola 2", "parentId": "e1"},
    "d":  {"name": "Detalle", "parentId": "o2"},
    "h":  {"name": "Oculta", "parentId": "e1", "clientVisible": False},
    "hs": {"name": "Sub", "parentId": "h"},
    "y":  {"name": "Cliente Y", "parentId": "c"},
    "e3": {"name": "Estudio 3", "parentId": "y"},
    "s":  {"name": "Suelta", "parentId": None},
}
REPORTS = {
    "rx":  {"folderId": "x"},
    "re1": {"folderId": "e1"},
    "ro2": {"folderId": "o2"},
    "rd":  {"folderId": "d"},
    "rh":  {"folderId": "h"},
    "rhs": {"folderId": "hs"},
    "re3": {"folderId": "e3"},
    "rs":  {"folderId": "s"},
    "rr":  {"folderId": None},
    "rz":  {"folderId": "borrada"},
}


def calc(ua, folders=FOLDERS, reports=REPORTS):
    return permisos.calcular_acceso(ua, folders, reports)


def test_carpeta_con_subcarpetas_a_tres_niveles():
    a = calc({"folderIds": ["e1"], "folderOptions": {"e1": {"noPrint": True}}})
    assert a["reportIds"] == sorted(["re1", "ro2", "rd", "rh", "rhs"])
    assert all(a["via"][r] == "e1" for r in a["reportIds"])
    assert a["opciones"]["rd"] == {"noPrint": True}


def test_directo_mas_carpeta_gana_la_asignacion_directa():
    a = calc({"reportIds": ["ro2", "rs"], "options": {"ro2": {"watermark": False, "expiresAt": "2027-01-01"}},
              "folderIds": ["e1"], "folderOptions": {"e1": {"watermark": True}}})
    assert a["via"]["ro2"] is None and a["via"]["re1"] == "e1" and a["via"]["rs"] is None
    assert a["opciones"]["ro2"] == {"watermark": False, "expiresAt": "2027-01-01"}
    assert a["opciones"]["re1"] == {"watermark": True}
    # Directo sin opciones propias: toma las de la carpeta que también se lo da.
    b = calc({"reportIds": ["ro2"], "folderIds": ["e1"], "folderOptions": {"e1": {"noCopy": True}}})
    assert b["opciones"]["ro2"] == {"noCopy": True} and b["via"]["ro2"] is None


def test_dos_carpetas_anidadas_gana_la_mas_cercana_y_hay_una_sola_raiz():
    a = calc({"folderIds": ["x", "o2"],
              "folderOptions": {"x": {"noPrint": True, "grantedAt": "1"}, "o2": {"noCopy": True, "grantedAt": "2"}}})
    assert a["via"]["rd"] == "o2" and a["via"]["ro2"] == "o2" and a["via"]["re1"] == "x"
    assert a["opciones"]["rd"] == {"noCopy": True, "grantedAt": "2"}
    assert a["raices"] == ["x"]
    assert a["carpetas"]["o2"]["parentId"] == "e1"


def test_carpetas_e_informes_inexistentes_se_ignoran():
    a = calc({"reportIds": ["rz", "no-existe"], "folderIds": ["borrada", "e3"]})
    assert a["reportIds"] == ["re3", "rz"]   # rz existe aunque su carpeta no
    assert a["via"]["rz"] is None
    assert "borrada" not in a["carpetas"]
    assert a["raices"] == ["e3"]


def test_ciclo_en_parent_id_no_cuelga():
    folders = {"a": {"name": "A", "parentId": "b"}, "b": {"name": "B", "parentId": "a"}}
    a = calc({"folderIds": ["a"]}, folders, {"r": {"folderId": "b"}})
    assert a["reportIds"] == ["r"] and a["via"]["r"] == "a"
    b = calc({"reportIds": ["r"]}, folders, {"r": {"folderId": "b"}})
    assert b["reportIds"] == ["r"] and b["raices"] == ["b"]


def test_usuario_sin_user_access():
    a = calc(None)
    assert a == {"reportIds": [], "via": {}, "opciones": {}, "carpetas": {}, "raices": [], "carpetaIds": []}


def test_ninguna_antecesora_de_una_raiz():
    a = calc({"folderIds": ["e1"]})
    assert a["raices"] == ["e1"]
    assert a["carpetas"]["e1"] == {"name": "Estudio 1", "parentId": None, "clientVisible": True}
    for antecesora in ("c", "x"):
        assert antecesora not in a["carpetas"]
    nombres = " ".join(c["name"] for c in a["carpetas"].values())
    assert "Clientes" not in nombres and "Cliente X" not in nombres
    assert a["carpetaIds"] == sorted(a["carpetas"])


def test_informe_directo_con_su_carpeta_como_raiz():
    a = calc({"reportIds": ["re3", "rr"]})
    assert a["raices"] == ["e3"]
    assert set(a["carpetas"]) == {"e3"}
    assert a["carpetas"]["e3"]["parentId"] is None
    assert "y" not in a["carpetas"] and "c" not in a["carpetas"]


def test_informe_directo_en_carpeta_oculta_sube_a_la_visible_mas_cercana():
    a = calc({"reportIds": ["rhs"]})
    # Sub (hs) es visible: es la raíz; Oculta (h) y Estudio 1 no se incluyen.
    assert a["raices"] == ["hs"] and set(a["carpetas"]) == {"hs"}
    b = calc({"reportIds": ["rh"]})
    # rh está en Oculta (h): la visible más cercana es Estudio 1, que es la raíz.
    assert b["raices"] == ["e1"]
    assert b["carpetas"]["h"] == {"name": "", "parentId": "e1", "clientVisible": False}
    assert "x" not in b["carpetas"]


def test_carpeta_oculta_asignada_no_es_raiz_y_su_contenido_va_al_inicio():
    a = calc({"folderIds": ["h"]})
    assert a["reportIds"] == ["rh", "rhs"]
    assert a["carpetas"]["h"] == {"name": "", "parentId": None, "clientVisible": False}
    assert a["raices"] == ["hs"]   # su subcarpeta visible aparece en el inicio
    assert "Oculta" not in str(a["carpetas"])


def test_subcarpeta_oculta_dentro_de_una_raiz_no_sube_mas_arriba():
    a = calc({"folderIds": ["e1"]})
    assert a["carpetas"]["h"]["parentId"] == "e1" and a["carpetas"]["h"]["name"] == ""
    assert a["carpetas"]["hs"]["parentId"] == "h"
    assert a["raices"] == ["e1"]


def test_raices_en_orden_alfabetico():
    a = calc({"reportIds": ["rs"], "folderIds": ["e3", "e1"]})
    assert a["raices"] == ["e1", "e3", "s"]


# ── Con emuladores: recálculo y triggers ──

def _arbol(db):
    for fid, f in FOLDERS.items():
        db.collection("folders").document(fid).set(f)
    for rid, r in REPORTS.items():
        db.collection("reports").document(rid).set({"name": f"Informe {rid}", **({"folderId": r["folderId"]} if r["folderId"] else {})})
    db.collection("users").document("u1").set({"email": "u1@x.uy", "role": "user"})
    db.collection("users").document("u2").set({"email": "u2@x.uy", "role": "user"})


def _efectivo(db, uid):
    return db.collection("accesoEfectivo").document(uid).get().to_dict()


@requiere_emuladores
def test_recalcular_escribe_solo_si_cambia(entorno):
    db, _ = entorno
    _arbol(db)
    db.collection("userAccess").document("u1").set({"folderIds": ["e1"], "reportIds": ["re3"]})
    cambio, acceso = permisos.recalcular(db, "u1")
    assert cambio and "rd" in acceso["reportIds"] and "re3" in acceso["reportIds"]
    t0 = _efectivo(db, "u1")["calculadoEn"]
    assert permisos.recalcular(db, "u1") == (False, acceso)
    assert _efectivo(db, "u1")["calculadoEn"] == t0


@requiere_emuladores
def test_mover_y_subir_informes_recalcula(entorno):
    db, _ = entorno
    _arbol(db)
    db.collection("userAccess").document("u1").set({"folderIds": ["e1"]})
    db.collection("userAccess").document("u2").set({"folderIds": ["e3"]})
    permisos.recalcular(db, "u1")
    permisos.recalcular(db, "u2")
    # Informe nuevo en una subcarpeta de la asignada.
    db.collection("reports").document("nuevo").set({"name": "Nuevo", "folderId": "d"})
    assert permisos.al_cambiar_informe(db, "nuevo", None, {"folderId": "d"}) == {"u1"}
    assert "nuevo" in _efectivo(db, "u1")["reportIds"]
    # Moverlo fuera (a la carpeta de u2): lo pierde u1 y lo gana u2.
    db.collection("reports").document("nuevo").update({"folderId": "e3"})
    assert permisos.al_cambiar_informe(db, "nuevo", {"folderId": "d"}, {"folderId": "e3"}) == {"u1", "u2"}
    assert "nuevo" not in _efectivo(db, "u1")["reportIds"]
    assert "nuevo" in _efectivo(db, "u2")["reportIds"]
    # Renombrar un informe no recalcula nada.
    t0 = _efectivo(db, "u2")["calculadoEn"]
    assert permisos.al_cambiar_informe(db, "nuevo", {"folderId": "e3", "name": "a"},
                                       {"folderId": "e3", "name": "b"}) == set()
    assert _efectivo(db, "u2")["calculadoEn"] == t0
    # Borrarlo se lo quita.
    db.collection("reports").document("nuevo").delete()
    permisos.al_cambiar_informe(db, "nuevo", {"folderId": "e3"}, None)
    assert "nuevo" not in _efectivo(db, "u2")["reportIds"]


@requiere_emuladores
def test_mover_una_carpeta_bajo_una_asignada_la_da(entorno):
    db, _ = entorno
    _arbol(db)
    db.collection("userAccess").document("u1").set({"folderIds": ["e1"]})
    permisos.recalcular(db, "u1")
    assert "re3" not in _efectivo(db, "u1")["reportIds"]
    db.collection("folders").document("y").update({"parentId": "o2"})
    assert "u1" in permisos.al_cambiar_carpeta(db, "y", FOLDERS["y"], {**FOLDERS["y"], "parentId": "o2"})
    acceso = _efectivo(db, "u1")
    assert "re3" in acceso["reportIds"] and acceso["via"]["re3"] == "e1"
    assert acceso["carpetas"]["y"]["parentId"] == "o2"


@requiere_emuladores
def test_renombrar_carpeta_solo_reescribe_a_quien_la_ve(entorno):
    db, _ = entorno
    _arbol(db)
    db.collection("userAccess").document("u1").set({"reportIds": ["re3"]})   # ve Estudio 3 por un directo
    db.collection("userAccess").document("u2").set({"folderIds": ["e1"]})
    permisos.recalcular(db, "u1")
    permisos.recalcular(db, "u2")
    t2 = _efectivo(db, "u2")["calculadoEn"]
    db.collection("folders").document("e3").update({"name": "Estudio Tres"})
    assert permisos.al_cambiar_carpeta(db, "e3", FOLDERS["e3"], {**FOLDERS["e3"], "name": "Estudio Tres"}) == {"u1"}
    assert _efectivo(db, "u1")["carpetas"]["e3"]["name"] == "Estudio Tres"
    assert _efectivo(db, "u2")["calculadoEn"] == t2
    # Un cambio que no es de nombre, padre ni visibilidad no hace nada.
    assert permisos.al_cambiar_carpeta(db, "e3", {**FOLDERS["e3"], "createdAt": 1},
                                       {**FOLDERS["e3"], "createdAt": 2}) == set()


@requiere_emuladores
def test_borrar_carpeta_asignada_limpia_user_access_y_no_da_la_padre(entorno):
    db, _ = entorno
    _arbol(db)
    db.collection("userAccess").document("u1").set(
        {"folderIds": ["o2", "e3"], "folderOptions": {"o2": {"noPrint": True}, "e3": {}}})
    permisos.recalcular(db, "u1")
    # Como deleteFolder() del panel: el contenido pasa a la carpeta padre y se borra.
    db.collection("folders").document("d").update({"parentId": "e1"})
    db.collection("reports").document("ro2").update({"folderId": "e1"})
    db.collection("folders").document("o2").delete()
    permisos.al_cambiar_carpeta(db, "o2", FOLDERS["o2"], None)
    ua = db.collection("userAccess").document("u1").get().to_dict()
    assert ua["folderIds"] == ["e3"] and "o2" not in ua["folderOptions"]
    acceso = _efectivo(db, "u1")
    assert acceso["reportIds"] == ["re3"]
    assert "e1" not in acceso["carpetas"]


@requiere_emuladores
def test_recalcular_todos_y_verificar(entorno):
    db, _ = entorno
    _arbol(db)
    db.collection("userAccess").document("u1").set({"reportIds": ["re1", "borrado"]})
    assert permisos.verificar(db) == [{"uid": "u1", "sinAccesoEfectivo": True, "faltan": ["re1", "borrado"]}]
    r = permisos.recalcular_todos(db)
    assert r["total"] == 2 and r["cambiados"] == 2   # u2 no tiene userAccess: igual recibe su doc vacío
    assert permisos.verificar(db) == []
    assert _efectivo(db, "u2")["reportIds"] == []
    assert permisos.recalcular_todos(db)["cambiados"] == 0
