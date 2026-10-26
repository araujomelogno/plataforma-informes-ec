"""Cloud Functions del Portal de Informes (2ª gen, Python).

Funciones:

- `crearUsuario` (callable, solo admin) — alta sin contraseña + correo de
  bienvenida con el enlace para fijarla (R1, R2, R4).
- `reenviarAcceso` (callable, solo admin) — nuevo enlace + correo (R3).
- `infoCorreo` (callable, solo admin) — plantillas por defecto, variables y
  cupo diario (R4, R6, R7).
- `enviarPrueba` (callable, solo admin) — correo de prueba de una plantilla
  al admin que lo pide (R10).
- `solicitarRestablecimiento` (callable, público) — "¿Olvidaste tu
  contraseña?" por Workspace; responde igual exista o no la cuenta (R11).
- `avisarAsignacion` (callable, solo admin) — el panel la llama al habilitar
  informes: manda el aviso "Nuevo informe" en el momento (R5, R8, R9).
- `notificarAcceso` (trigger de `userAccess/{uid}`) — respaldo: encola el
  aviso si el panel no llegó a mandarlo (mismo id: no duplica).
- `despacharAvisos` (programada, cada minuto) — manda los avisos de respaldo
  cuando vence la ventana.

Ver `docs/DESPLIEGUE_alta_usuarios_correo.md`.
"""

import firebase_admin
from firebase_admin import auth, firestore
from firebase_functions import firestore_fn, https_fn, options, scheduler_fn

from portal import accesos, avisos, config, correo

options.set_global_options(
    region=config.REGION,
    memory=options.MemoryOption.MB_256,
    # Tope de instancias: acota el costo ante un pico o un abuso.
    max_instances=10,
)

# La contraseña de aplicación de `notificaciones@equipos.com.uy` (Secret
# Manager). Se declara solo en las funciones que mandan correo.
SECRETOS = ["SMTP_PASSWORD"]

# La app de Firebase Admin se inicializa al importar: el SDK de funciones la
# necesita para verificar el token de cada callable antes de llamarnos. No usa
# credenciales hasta el primer uso, así que el deploy (que importa este módulo
# para descubrir las funciones) no se ve afectado.
firebase_admin.initialize_app()


def _db():
    return firestore.client()


def _cuentas():
    return auth


def _mailer():
    return correo.Workspace.desde_entorno()


def _error(error):
    codigos = {
        "unauthenticated": https_fn.FunctionsErrorCode.UNAUTHENTICATED,
        "permission-denied": https_fn.FunctionsErrorCode.PERMISSION_DENIED,
        "invalid-argument": https_fn.FunctionsErrorCode.INVALID_ARGUMENT,
        "not-found": https_fn.FunctionsErrorCode.NOT_FOUND,
        "failed-precondition": https_fn.FunctionsErrorCode.FAILED_PRECONDITION,
    }
    return https_fn.HttpsError(
        codigos.get(error.codigo, https_fn.FunctionsErrorCode.INTERNAL),
        error.mensaje)


def _datos(req):
    return req.data if isinstance(req.data, dict) else {}


@https_fn.on_call(secrets=SECRETOS, timeout_sec=60)
def crearUsuario(req: https_fn.CallableRequest) -> dict:  # noqa: N802
    db = _db()
    try:
        actor = accesos.exigir_admin(db, req.auth)
        return accesos.crear_usuario(db, _cuentas(), _mailer(), actor,
                                     _datos(req).get("email"))
    except accesos.ErrorPortal as error:
        raise _error(error)


@https_fn.on_call(secrets=SECRETOS, timeout_sec=60)
def reenviarAcceso(req: https_fn.CallableRequest) -> dict:  # noqa: N802
    db = _db()
    datos = _datos(req)
    try:
        actor = accesos.exigir_admin(db, req.auth)
        return accesos.reenviar_acceso(db, _cuentas(), _mailer(), actor,
                                       uid=datos.get("uid"), email=datos.get("email"))
    except accesos.ErrorPortal as error:
        raise _error(error)


@https_fn.on_call(secrets=SECRETOS)
def infoCorreo(req: https_fn.CallableRequest) -> dict:  # noqa: N802
    db = _db()
    try:
        accesos.exigir_admin(db, req.auth)
        return accesos.info_correo(db, _mailer())
    except accesos.ErrorPortal as error:
        raise _error(error)


@https_fn.on_call(secrets=SECRETOS, timeout_sec=60)
def enviarPrueba(req: https_fn.CallableRequest) -> dict:  # noqa: N802
    db = _db()
    datos = _datos(req)
    try:
        actor = accesos.exigir_admin(db, req.auth)
        return accesos.enviar_prueba(
            db, _mailer(), actor, datos.get("plantilla"),
            asunto=datos.get("asunto"), cuerpo=datos.get("cuerpo"),
            remitente_nombre=datos.get("remitenteNombre"),
            reply_to=datos.get("replyTo"))
    except accesos.ErrorPortal as error:
        raise _error(error)


@https_fn.on_call(secrets=SECRETOS, timeout_sec=60)
def solicitarRestablecimiento(req: https_fn.CallableRequest) -> dict:  # noqa: N802
    # Público a propósito (el que olvidó la contraseña no tiene sesión). La
    # respuesta es siempre la misma y hay un tope de pedidos por dirección.
    return accesos.solicitar_restablecimiento(_db(), _cuentas(), _mailer(),
                                              _datos(req).get("email"))


@https_fn.on_call(secrets=SECRETOS, timeout_sec=60)
def avisarAsignacion(req: https_fn.CallableRequest) -> dict:  # noqa: N802
    """El panel la llama después de habilitar informes: manda el aviso «Nuevo
    informe» en el momento (el trigger queda de respaldo, sin duplicar)."""
    db = _db()
    datos = _datos(req)
    try:
        accesos.exigir_admin(db, req.auth)
        uid = str(datos.get("uid") or "").strip()
        ids = datos.get("reportIds") or []
        if not uid or not isinstance(ids, list) or not ids:
            raise accesos.ErrorPortal("invalid-argument", "Faltan uid o reportIds.")
        return avisos.avisar_ahora(db, _mailer(), uid, [str(x) for x in ids][:200])
    except accesos.ErrorPortal as error:
        raise _error(error)


@firestore_fn.on_document_written(document="userAccess/{uid}",
                                  secrets=SECRETOS, timeout_sec=120)
def notificarAcceso(event: firestore_fn.Event) -> None:  # noqa: N802
    cambio = event.data
    antes = cambio.before.to_dict() if cambio and cambio.before and cambio.before.exists else {}
    despues = cambio.after.to_dict() if cambio and cambio.after and cambio.after.exists else {}
    avisos.registrar_cambio(_db(), _mailer(), event.id, event.params["uid"],
                            antes, despues)


@scheduler_fn.on_schedule(schedule="every 1 minutes", secrets=SECRETOS,
                          timeout_sec=300, max_instances=1)
def despacharAvisos(event: scheduler_fn.ScheduledEvent) -> None:  # noqa: N802
    avisos.despachar(_db(), _mailer())
