"""C4 — Acceso efectivo: informes directos + los de las carpetas asignadas.

Las reglas de Storage no pueden recorrer el árbol de carpetas (no tienen
bucles y leen como mucho 2 documentos de Firestore), así que el acceso de cada
usuario se calcula acá, ya expandido, y se guarda en `accesoEfectivo/{uid}`:

    reportIds   informes que puede ver (directos ∪ los de sus carpetas y subcarpetas)
    via         {rid: None (directo) | id de la carpeta asignada más cercana}
    opciones    {rid: opciones que se le aplican}: las de la asignación directa
                si existen; si no, las de la carpeta asignada más cercana
    carpetas    {fid: {name, parentId, clientVisible}}: las carpetas que el
                usuario navega. Nunca incluye una antecesora de sus raíces.
                Las ocultas van sin nombre: solo sirven para ubicar su contenido
                en la carpeta visible más cercana.
    raices      raíces de su navegación, en orden alfabético
    carpetaIds  las claves de `carpetas`, para buscar quién ve una carpeta

`calcular_acceso` es pura (sin Firestore). `recalcular` lee lo necesario y
escribe solo si algo cambió, así no se disparan avisos ni escrituras de más.
Solo escriben `accesoEfectivo` las Cloud Functions (las reglas lo niegan al
navegador).
"""

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

COLECCION = "accesoEfectivo"
# Firestore acepta hasta 30 valores en `in` y `array-contains-any`.
TANDA = 30
CAMPOS = ("reportIds", "via", "opciones", "carpetas", "raices", "carpetaIds")


def _visible(carpeta):
    return (carpeta or {}).get("clientVisible") is not False


def cadena(folders, fid):
    """[fid, padre, abuelo, …] hasta la raíz o una carpeta inexistente. Corta
    los ciclos de `parentId` (datos corruptos)."""
    out, vistos = [], set()
    while fid and fid in folders and fid not in vistos:
        vistos.add(fid)
        out.append(fid)
        fid = (folders[fid] or {}).get("parentId")
    return out


def subarbol(folders, raices):
    """Las carpetas de `raices` y todas sus descendientes (BFS con visitados)."""
    hijos = {}
    for fid, carpeta in folders.items():
        hijos.setdefault((carpeta or {}).get("parentId"), []).append(fid)
    vistos, cola = set(), [f for f in raices if f in folders]
    while cola:
        fid = cola.pop(0)
        if fid in vistos:
            continue
        vistos.add(fid)
        cola.extend(hijos.get(fid, []))
    return vistos


def calcular_acceso(user_access, folders, reports):
    """Acceso efectivo de un usuario.

    `user_access`: el doc `userAccess/{uid}` (o None). `folders`: {fid: carpeta},
    todas. `reports`: {rid: informe} con al menos los directos y los de las
    carpetas asignadas (los demás se ignoran). Las carpetas y los informes que
    no están (borrados) se ignoran.
    """
    ua = user_access or {}
    folders = folders or {}
    reports = reports or {}
    options = ua.get("options") or {}
    folder_options = ua.get("folderOptions") or {}
    asignadas = {f for f in (ua.get("folderIds") or []) if f in folders}
    directos = {r for r in (ua.get("reportIds") or []) if r in reports}

    via, opciones, cercanas = {}, {}, {}
    for rid, rep in reports.items():
        camino = cadena(folders, (rep or {}).get("folderId"))
        cercana = next((f for f in camino if f in asignadas), None)
        if rid not in directos and not cercana:
            continue
        via[rid] = None if rid in directos else cercana
        cercanas[rid] = cercana
        if rid in options:
            opciones[rid] = dict(options.get(rid) or {})
        elif cercana:
            opciones[rid] = dict(folder_options.get(cercana) or {})
        else:
            opciones[rid] = {}

    # Raíces de la navegación: cada carpeta asignada que no está dentro de otra
    # asignada, y la carpeta visible más cercana de cada informe directo que no
    # cae en ninguna asignada (sin sus antecesoras).
    raices_asignadas = {f for f in asignadas
                        if not any(a in asignadas for a in cadena(folders, folders[f].get("parentId")))}
    incluidas = subarbol(folders, raices_asignadas)
    tope = set(raices_asignadas)
    for rid in via:
        if cercanas[rid]:
            continue
        camino = cadena(folders, (reports[rid] or {}).get("folderId"))
        visible = next((i for i, f in enumerate(camino) if _visible(folders[f])), None)
        if visible is None:
            continue   # solo carpetas ocultas encima: se ve en el inicio
        incluidas.update(camino[:visible + 1])
        tope.add(camino[visible])

    carpetas = {}
    for fid in incluidas:
        carpeta = folders[fid] or {}
        padre = carpeta.get("parentId")
        visible = _visible(carpeta)
        carpetas[fid] = {
            "name": str(carpeta.get("name") or "") if visible else "",
            "parentId": padre if (fid not in tope and padre in incluidas) else None,
            "clientVisible": visible,
        }

    def _visible_arriba(fid):
        vistos = set()
        actual = carpetas[fid]["parentId"]
        while actual and actual in carpetas and actual not in vistos:
            vistos.add(actual)
            if carpetas[actual]["clientVisible"]:
                return True
            actual = carpetas[actual]["parentId"]
        return False

    raices = sorted((f for f, c in carpetas.items() if c["clientVisible"] and not _visible_arriba(f)),
                    key=lambda f: (carpetas[f]["name"].casefold(), f))
    return {
        "reportIds": sorted(via),
        "via": via,
        "opciones": opciones,
        "carpetas": carpetas,
        "raices": raices,
        "carpetaIds": sorted(carpetas),
    }


# ── Lectura y escritura ──────────────────────────────────────────────

def leer_carpetas(db):
    return {s.id: (s.to_dict() or {}) for s in db.collection("folders").stream()}


def _tandas(valores):
    valores = list(dict.fromkeys(v for v in valores if v))
    for i in range(0, len(valores), TANDA):
        yield valores[i:i + TANDA]


def leer_informes(db, user_access, folders):
    """Los informes directos y los de los subárboles de las carpetas asignadas."""
    ua = user_access or {}
    informes = {}
    refs = [db.collection("reports").document(r) for r in dict.fromkeys(ua.get("reportIds") or []) if r]
    for snap in (db.get_all(refs) if refs else []):
        if snap.exists:
            informes[snap.id] = snap.to_dict() or {}
    for tanda in _tandas(subarbol(folders, ua.get("folderIds") or [])):
        consulta = db.collection("reports").where(filter=FieldFilter("folderId", "in", tanda))
        for snap in consulta.stream():
            informes[snap.id] = snap.to_dict() or {}
    return informes


def recalcular(db, uid, folders=None):
    """Recalcula `accesoEfectivo/{uid}` y lo escribe si cambió. Devuelve
    `(cambio, acceso)`. Si el usuario ya no existe (ni `users` ni `userAccess`),
    borra su acceso efectivo."""
    ua_snap = db.collection("userAccess").document(uid).get()
    ref = db.collection(COLECCION).document(uid)
    if not ua_snap.exists and not db.collection("users").document(uid).get().exists:
        actual = ref.get()
        if actual.exists:
            ref.delete()
            return True, None
        return False, None
    ua = ua_snap.to_dict() or {}
    if folders is None:
        folders = leer_carpetas(db)
    acceso = calcular_acceso(ua, folders, leer_informes(db, ua, folders))
    actual = ref.get()
    previo = (actual.to_dict() or {}) if actual.exists else None
    if previo is not None and all(previo.get(k) == acceso[k] for k in CAMPOS):
        return False, acceso
    ref.set({**acceso, "calculadoEn": firestore.SERVER_TIMESTAMP})
    return True, acceso


def leer_acceso(db, uid):
    snap = db.collection(COLECCION).document(uid).get()
    return (snap.to_dict() or {}) if snap.exists else {}


# ── A quién recalcular ───────────────────────────────────────────────

def _uids(consulta):
    return {s.id for s in consulta.stream()}


def usuarios_con_carpetas(db, fids):
    """Usuarios con alguna de `fids` en `userAccess.folderIds`."""
    uids = set()
    for tanda in _tandas(fids):
        uids |= _uids(db.collection("userAccess").where(
            filter=FieldFilter("folderIds", "array_contains_any", tanda)))
    return uids


def usuarios_con_informe(db, rid):
    """Usuarios que tienen el informe directo o en su acceso efectivo."""
    return (_uids(db.collection("userAccess").where(filter=FieldFilter("reportIds", "array_contains", rid)))
            | _uids(db.collection(COLECCION).where(filter=FieldFilter("reportIds", "array_contains", rid))))


def usuarios_que_ven_carpeta(db, fid):
    return _uids(db.collection(COLECCION).where(filter=FieldFilter("carpetaIds", "array_contains", fid)))


def al_cambiar_informe(db, rid, antes, despues):
    """Trigger de `reports/{rid}`. Solo importa si se creó, se borró o cambió
    de carpeta (renombrar no recalcula nada). Devuelve los uid recalculados."""
    carpeta = lambda d: (d or {}).get("folderId") or None  # noqa: E731
    if antes is not None and despues is not None and carpeta(antes) == carpeta(despues):
        return set()
    folders = leer_carpetas(db)
    camino = set(cadena(folders, carpeta(antes))) | set(cadena(folders, carpeta(despues)))
    uids = usuarios_con_carpetas(db, camino) | usuarios_con_informe(db, rid)
    for uid in sorted(uids):
        recalcular(db, uid, folders)
    return uids


RELEVANTES_CARPETA = ("parentId", "name", "clientVisible")


def al_cambiar_carpeta(db, fid, antes, despues):
    """Trigger de `folders/{fid}`. Importa si se creó, se borró o cambió
    `parentId`, `name` o `clientVisible`. Recalcula a quienes tienen asignada la
    carpeta o una antecesora (antes y después) y a quienes la ven por un informe
    directo. Si se borró, la quita de `folderIds`/`folderOptions` (C9). Devuelve
    los uid recalculados."""
    if (antes is not None and despues is not None
            and all((antes or {}).get(k) == (despues or {}).get(k) for k in RELEVANTES_CARPETA)):
        return set()
    folders = leer_carpetas(db)
    padre = lambda d: (d or {}).get("parentId")  # noqa: E731
    camino = {fid} | set(cadena(folders, padre(antes))) | set(cadena(folders, padre(despues)))
    uids = usuarios_con_carpetas(db, camino) | usuarios_que_ven_carpeta(db, fid)
    if despues is None:
        for uid in usuarios_con_carpetas(db, [fid]):
            db.collection("userAccess").document(uid).update({
                "folderIds": firestore.ArrayRemove([fid]),
                f"folderOptions.{fid}": firestore.DELETE_FIELD,
            })
    for uid in sorted(uids):
        recalcular(db, uid, folders)
    return uids


# ── Todos (reconciliación diaria, callable y migración) ──────────────

def recalcular_todos(db, uid=None):
    """Recalcula a un usuario o a todos. Devuelve `{total, cambiados}`."""
    folders = leer_carpetas(db)
    if uid:
        uids = {uid}
    else:
        uids = (_uids(db.collection("users")) | _uids(db.collection("userAccess"))
                | _uids(db.collection(COLECCION)))
    cambiados = []
    for u in sorted(uids):
        cambio, _ = recalcular(db, u, folders)
        if cambio:
            cambiados.append(u)
    return {"total": len(uids), "cambiados": len(cambiados), "uidsCambiados": cambiados[:200]}


def verificar(db):
    """Diferencias entre `userAccess` y `accesoEfectivo` (migración, C10): cada
    `userAccess/{uid}` tiene su `accesoEfectivo/{uid}`, y sus `reportIds` que
    existen están todos en `accesoEfectivo.reportIds`."""
    diferencias = []
    for snap in db.collection("userAccess").stream():
        ids = [r for r in dict.fromkeys((snap.to_dict() or {}).get("reportIds") or []) if r]
        efectivo = db.collection(COLECCION).document(snap.id).get()
        if not efectivo.exists:
            diferencias.append({"uid": snap.id, "sinAccesoEfectivo": True, "faltan": ids})
            continue
        tiene = set((efectivo.to_dict() or {}).get("reportIds") or [])
        faltan = [r for r in ids if r not in tiene]
        if faltan:
            existen = {s.id for s in db.get_all([db.collection("reports").document(r) for r in faltan]) if s.exists}
            faltan = [r for r in faltan if r in existen]
        if faltan:
            diferencias.append({"uid": snap.id, "sinAccesoEfectivo": False, "faltan": faltan})
    return diferencias
