"""Mandar una plantilla y dejar registro. Nunca levanta: informa.

Es la regla R2 de la spec: el correo es una comodidad, no un punto de falla.
Quien llama (alta, reenvío, aviso) sigue adelante pase lo que pase acá y
decide qué mostrar con `{enviado, detalle}`.
"""

from . import correo, plantillas

DOC_CONFIG = ("config", "correos")


def leer_config(db):
    snap = db.collection(DOC_CONFIG[0]).document(DOC_CONFIG[1]).get()
    return (snap.to_dict() or {}) if snap.exists else {}


def enviar_plantilla(db, mailer, clave, destinatario, valores, disparado_por,
                     config_correos=None, log_id=None, prefijo_asunto="",
                     respetar_interruptor=True, **extra_log):
    """Arma la plantilla `clave`, la manda y registra el resultado.

    Devuelve `{enviado, estado, detalle, logId}`. `detalle` es el motivo en
    criollo, apto para mostrarle al admin (sin credenciales ni enlaces).
    """
    if config_correos is None:
        config_correos = leer_config(db)
    efectiva = plantillas.plantilla_efectiva(config_correos, clave)
    if (respetar_interruptor and clave in plantillas.CON_INTERRUPTOR
            and not efectiva["activo"]):
        log_id = correo.registrar(
            db, clave, destinatario, correo.OMITIDO, doc_id=log_id,
            motivo="La plantilla está desactivada en Configuración → Correos.",
            disparado_por=disparado_por, **extra_log)
        return {"enviado": False, "estado": correo.OMITIDO, "logId": log_id,
                "detalle": "La plantilla está desactivada."}

    asunto, texto = plantillas.armar(config_correos, clave, valores)
    nombre, reply_to = plantillas.remitente(config_correos)
    try:
        resultado = mailer.enviar(destinatario, prefijo_asunto + asunto, texto,
                                  nombre=nombre, reply_to=reply_to)
    except correo.ErrorEnvio as error:
        log_id = correo.registrar(
            db, clave, destinatario, correo.FALLIDO, doc_id=log_id,
            motivo=error.motivo, intentos=error.intentos,
            disparado_por=disparado_por, **extra_log)
        return {"enviado": False, "estado": correo.FALLIDO, "logId": log_id,
                "detalle": error.motivo}
    except Exception as error:  # noqa: BLE001 — un bug no puede romper el alta
        motivo = f"Error inesperado al enviar: {type(error).__name__}"
        log_id = correo.registrar(
            db, clave, destinatario, correo.FALLIDO, doc_id=log_id,
            motivo=motivo, disparado_por=disparado_por, **extra_log)
        return {"enviado": False, "estado": correo.FALLIDO, "logId": log_id,
                "detalle": motivo}

    log_id = correo.registrar(
        db, clave, destinatario, correo.ENVIADO, doc_id=log_id,
        intentos=resultado.get("intentos"), duracion_ms=resultado.get("ms"),
        disparado_por=disparado_por, **extra_log)
    return {"enviado": True, "estado": correo.ENVIADO, "logId": log_id,
            "detalle": f"Se envió el correo a {destinatario}."}
