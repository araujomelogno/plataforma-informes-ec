"""R5/R8/R9 — Aviso por correo cuando un usuario gana acceso a un informe.

Hay dos vías que encolan el mismo aviso, y una sola lo manda:

1. **En el momento** (`avisar_ahora`, callable `avisarAsignacion`): el panel,
   después de habilitar informes (desde Permisos, desde el modal "Usuarios"
   del informe o desde la tabla de usuarios, que lleva a Permisos), espera unos
   segundos por si se habilitan más y llama a la función, que encola y manda
   **un solo correo** con la lista en ese momento. El admin ve el resultado.
2. **Respaldo** (`registrar_cambio`, trigger de `userAccess/{uid}`): por cada
   id nuevo en `reportIds` encola el aviso. Si el panel no llegó a mandarlo
   (pestaña cerrada, red caída, cualquier vía futura que no pase por el panel),
   la función programada `despacharAvisos` lo manda cuando vence la ventana de
   respaldo (`config/correos.ventanaAgrupadoMin`, 2 min por defecto; con 0 lo
   manda el mismo trigger).

**Sin duplicados:** las dos vías encolan con el mismo id,
`avisosPendientes/{uid}-{reportId}-{grantedAt}` (la fecha de la asignación que
graba el panel), con `create()`, que falla si ya existe. Y el despacho reclama
los pendientes en una transacción: si el panel y la función programada miran
el mismo grupo a la vez, solo uno lo manda.

Se respeta `options[id].notificar == false` (casilla "Avisar al usuario por
correo" destildada). Los admins también pueden tener informes asignados ("Mis
informes") y reciben el aviso si se dejó tildada la casilla (para ellos viene
destildada).

Al despachar se vuelve a leer `userAccess/{uid}`: si el admin destildó el
informe antes del envío, ese informe no se avisa (y si no queda ninguno, no
sale correo). También se toman ahí la caducidad y la carpeta, que suelen
escribirse un instante después de habilitar el informe.
"""

import datetime

from google.api_core import exceptions as gexc
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from . import config, correo, envio, plantillas

COLECCION = "avisosPendientes"

PENDIENTE = "pendiente"
PROCESANDO = "procesando"

# Ventana de agrupado por defecto (minutos). Se cambia en Configuración →
# Correos (`config/correos.ventanaAgrupadoMin`); 0 = mandar en el momento.
VENTANA_POR_DEFECTO_MIN = 2
# Aunque el admin siga habilitando informes, el aviso no espera más que esto.
MULTIPLO_ESPERA_MAXIMA = 5


def _ahora():
    return datetime.datetime.now(datetime.timezone.utc)


def ventana_min(config_correos):
    valor = (config_correos or {}).get("ventanaAgrupadoMin")
    try:
        valor = int(valor)
    except (TypeError, ValueError):
        return VENTANA_POR_DEFECTO_MIN
    return max(0, min(valor, 60))


def ids_nuevos(antes, despues):
    """Los `reportId` que están en `despues` y no estaban en `antes`, en orden."""
    previos = set((antes or {}).get("reportIds") or [])
    vistos, nuevos = set(), []
    for rid in (despues or {}).get("reportIds") or []:
        if rid not in previos and rid not in vistos:
            vistos.add(rid)
            nuevos.append(rid)
    return nuevos


def _quiere_aviso(opciones, rid):
    return ((opciones or {}).get(rid) or {}).get("notificar") is not False


_MINIMO = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)


def clave_aviso(uid, rid, opciones, respaldo=None):
    """Id del aviso en la cola: el mismo para el panel y para el trigger.

    Sale de la fecha de la asignación (`options[rid].grantedAt`, que el panel
    graba en cada asignación): volver a asignar más tarde es otra asignación
    (otro aviso), pero las dos vías que ven la misma asignación coinciden.
    Sin `grantedAt` (asignaciones escritas por otra vía) se usa `respaldo`.
    """
    granted = str(((opciones or {}).get(rid) or {}).get("grantedAt") or "").strip()
    if granted:
        limpio = "".join(c if c.isalnum() else "_" for c in granted)[:40]
        return f"{uid}-{rid}-{limpio}"
    return respaldo or f"{uid}-{rid}"


def _encolar(db, uid, rid, opciones, origen, ahora, event_id=None):
    """Crea el aviso pendiente. False si ya estaba (otra vía o un reintento)."""
    clave = clave_aviso(uid, rid, opciones,
                        respaldo=f"{event_id}-{rid}" if event_id else None)
    try:
        db.collection(COLECCION).document(clave).create({
            "uid": uid,
            "reportId": rid,
            "eventId": event_id,
            "origen": origen,
            "estado": PENDIENTE,
            "grantedByEmail": ((opciones or {}).get(rid) or {}).get("grantedByEmail"),
            "creadoEn": ahora,
            "expiraEn": ahora + datetime.timedelta(days=config.DIAS_DE_REGISTRO),
        })
    except gexc.AlreadyExists:
        return False
    return True


# ── 1. Trigger (respaldo) ────────────────────────────────────────────

def registrar_cambio(db, mailer, event_id, uid, antes, despues, ahora=None):
    """Encola los avisos de un cambio en `userAccess/{uid}`. Devuelve la lista
    de `reportId` encolados (vacía si no hay nada que avisar o si el panel ya
    los había encolado)."""
    nuevos = ids_nuevos(antes, despues)
    if not nuevos:
        return []
    opciones = (despues or {}).get("options") or {}
    nuevos = [rid for rid in nuevos if _quiere_aviso(opciones, rid)]
    if not nuevos:
        return []
    ficha = db.collection("users").document(uid).get()
    if not ficha.exists:
        return []

    ahora = ahora or _ahora()
    encolados = [rid for rid in nuevos
                 if _encolar(db, uid, rid, opciones, "trigger", ahora, event_id)]

    if encolados:
        cfg = envio.leer_config(db)
        if ventana_min(cfg) == 0:
            despachar(db, mailer, ahora=ahora, uid=uid, forzar=True,
                      config_correos=cfg)
    return encolados


# ── 2. Despacho ──────────────────────────────────────────────────────

def _pendientes(db, uid=None):
    consulta = db.collection(COLECCION).where(
        filter=FieldFilter("estado", "==", PENDIENTE))
    if uid:
        consulta = consulta.where(filter=FieldFilter("uid", "==", uid))
    grupos = {}
    for snap in consulta.stream():
        datos = snap.to_dict() or {}
        grupos.setdefault(datos.get("uid"), []).append((snap.reference, datos))
    return grupos


def listo_para_enviar(items, ahora, ventana):
    """El grupo sale cuando pasó la ventana desde el último informe habilitado
    (nadie sigue tildando), o cuando el primero ya esperó demasiado."""
    fechas = [d.get("creadoEn") for _, d in items if d.get("creadoEn")]
    if not fechas:
        return True
    espera = datetime.timedelta(minutes=ventana)
    return (ahora - max(fechas) >= espera
            or ahora - min(fechas) >= espera * MULTIPLO_ESPERA_MAXIMA)


def _reclamar(db, refs):
    """Pasa a `procesando` los que sigan pendientes, en una transacción: si el
    trigger (ventana 0) y la función programada miran el mismo grupo a la vez,
    solo uno lo manda."""
    transaccion = db.transaction()

    @firestore.transactional
    def _paso(tx):
        snaps = [r.get(transaction=tx) for r in refs]
        tomados = []
        for snap in snaps:
            if snap.exists and (snap.to_dict() or {}).get("estado") == PENDIENTE:
                tx.update(snap.reference, {"estado": PROCESANDO})
                tomados.append((snap.reference, snap.to_dict()))
        return tomados

    return _paso(transaccion)


def _ruta_carpeta(db, folder_id, cache):
    """Ruta visible para el cliente ("A / B / C"): las carpetas ocultas no
    aparecen, igual que en su vista del portal."""
    partes, vistos = [], set()
    actual = folder_id
    while actual and actual not in vistos:
        vistos.add(actual)
        if actual not in cache:
            snap = db.collection("folders").document(actual).get()
            cache[actual] = (snap.to_dict() or {}) if snap.exists else None
        carpeta = cache[actual]
        if not carpeta:
            break
        if carpeta.get("clientVisible") is not False:
            partes.insert(0, str(carpeta.get("name") or "").strip())
        actual = carpeta.get("parentId")
    return " / ".join(p for p in partes if p)


def _fecha(iso):
    """'2026-12-31' → '31/12/2026'."""
    try:
        return datetime.date.fromisoformat(str(iso)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return ""


def _valores(db, uid, email, ids, opciones, items):
    cache = {}
    informes = []
    for rid in ids:
        snap = db.collection("reports").document(rid).get()
        if not snap.exists:
            continue
        rep = snap.to_dict() or {}
        informes.append({
            "id": rid,
            "nombre": str(rep.get("name") or "(sin nombre)"),
            "carpeta": _ruta_carpeta(db, rep.get("folderId"), cache),
            "vence": _fecha((opciones.get(rid) or {}).get("expiresAt") or ""),
        })
    admins = []
    for _, datos in items:
        quien = datos.get("grantedByEmail")
        if quien and quien not in admins:
            admins.append(quien)
    base = {"email": email, "url_portal": config.PORTAL_URL,
            "admin": ", ".join(admins)}
    if len(informes) == 1:
        inf = informes[0]
        return informes, {**base, "informe": inf["nombre"],
                          "carpeta": inf["carpeta"], "vence": inf["vence"]}
    lineas = []
    for inf in informes:
        extra = []
        if inf["carpeta"]:
            extra.append(f"carpeta: {inf['carpeta']}")
        if inf["vence"]:
            extra.append(f"disponible hasta: {inf['vence']}")
        lineas.append(inf["nombre"] + (f" ({' · '.join(extra)})" if extra else ""))
    return informes, {**base, "informe": lineas, "carpeta": "", "vence": ""}


def _cerrar(items, estado, **campos):
    for ref, _ in items:
        ref.update({"estado": estado, **campos})


def _despachar_grupo(db, mailer, uid, items, config_correos):
    acceso_snap = db.collection("userAccess").document(uid).get()
    acceso = (acceso_snap.to_dict() or {}) if acceso_snap.exists else {}
    vigentes = set(acceso.get("reportIds") or [])
    opciones = acceso.get("options") or {}
    ficha_snap = db.collection("users").document(uid).get()
    ficha = (ficha_snap.to_dict() or {}) if ficha_snap.exists else None

    if not ficha or not ficha.get("email"):
        _cerrar(items, correo.OMITIDO, motivo="Usuario inexistente o sin email.")
        return {"uid": uid, "estado": correo.OMITIDO, "detalle": "El usuario no existe o no tiene email."}

    ids, vistos = [], set()
    for _, datos in sorted(items, key=lambda x: x[1].get("creadoEn") or _MINIMO):
        rid = datos.get("reportId")
        if rid in vistos:
            continue
        vistos.add(rid)
        if rid in vigentes and _quiere_aviso(opciones, rid):
            ids.append(rid)

    email = str(ficha["email"]).strip().lower()
    disparado_por = {"tipo": "asignacion",
                     "eventIds": sorted({d.get("eventId") for _, d in items if d.get("eventId")})}
    if not ids:
        log_id = correo.registrar(
            db, plantillas.NUEVO_INFORME, email, correo.OMITIDO,
            motivo="El acceso se quitó (o se marcó «no avisar») antes del envío.",
            disparado_por=disparado_por, uid=uid,
            reportIds=sorted(vistos))
        _cerrar(items, correo.OMITIDO, mailLogId=log_id)
        return {"uid": uid, "estado": correo.OMITIDO, "email": email,
                "detalle": "El acceso se quitó o se marcó «no avisar» antes del envío."}

    informes, valores = _valores(db, uid, email, ids, opciones, items)
    if not informes:
        _cerrar(items, correo.OMITIDO, motivo="Los informes ya no existen.")
        return {"uid": uid, "estado": correo.OMITIDO, "detalle": "Los informes ya no existen."}

    resultado = envio.enviar_plantilla(
        db, mailer, plantillas.NUEVO_INFORME, email, valores, disparado_por,
        config_correos=config_correos, uid=uid,
        reportId=informes[0]["id"] if len(informes) == 1 else None,
        reportIds=[i["id"] for i in informes])
    _cerrar(items, resultado["estado"], mailLogId=resultado["logId"])
    return {"uid": uid, "estado": resultado["estado"], "email": email,
            "detalle": resultado["detalle"],
            "informes": [i["id"] for i in informes]}


def despachar(db, mailer, ahora=None, uid=None, forzar=False, config_correos=None):
    """Manda los avisos agrupados que estén listos. Devuelve un resumen."""
    ahora = ahora or _ahora()
    if config_correos is None:
        config_correos = envio.leer_config(db)
    ventana = ventana_min(config_correos)
    resumen = []
    for usuario, items in _pendientes(db, uid).items():
        if not usuario:
            continue
        if not forzar and not listo_para_enviar(items, ahora, ventana):
            continue
        tomados = _reclamar(db, [ref for ref, _ in items])
        if not tomados:
            continue
        try:
            resumen.append(_despachar_grupo(db, mailer, usuario, tomados,
                                            config_correos))
        except Exception as error:  # noqa: BLE001 — un usuario no frena al resto
            print(f"[avisos] falló el despacho de {usuario}: "
                  f"{type(error).__name__}: {str(error)[:200]}")
            _cerrar(tomados, correo.FALLIDO,
                    motivo=f"Error al preparar el aviso: {type(error).__name__}")
    return resumen


# ── 3. En el momento (panel → callable avisarAsignacion) ─────────────

def avisar_ahora(db, mailer, uid, report_ids, ahora=None):
    """Encola los informes recién habilitados a `uid` y manda el aviso ya.

    Solo considera los que siguen asignados y no tienen «no avisar». Devuelve
    `{estado, detalle, informes, email}`; `estado` es `enviado`, `fallido`,
    `omitido`, `sin_aviso` (nada que avisar) o `ya_enviado` (otra vía lo mandó
    o lo está mandando: no se repite).
    """
    ahora = ahora or _ahora()
    acceso_snap = db.collection("userAccess").document(uid).get()
    acceso = (acceso_snap.to_dict() or {}) if acceso_snap.exists else {}
    vigentes = set(acceso.get("reportIds") or [])
    opciones = acceso.get("options") or {}
    pedidos = [rid for rid in dict.fromkeys(report_ids or [])
               if rid in vigentes and _quiere_aviso(opciones, rid)]
    if not pedidos:
        return {"estado": "sin_aviso", "informes": [],
                "detalle": "No hay informes nuevos para avisar."}
    if not db.collection("users").document(uid).get().exists:
        return {"estado": "sin_aviso", "informes": [],
                "detalle": "El usuario no existe."}
    for rid in pedidos:
        _encolar(db, uid, rid, opciones, "panel", ahora)
    resumen = despachar(db, mailer, ahora=ahora, uid=uid, forzar=True)
    if not resumen:
        return {"estado": "ya_enviado", "informes": pedidos,
                "detalle": "El aviso ya se había enviado (o se está enviando)."}
    return resumen[0]
