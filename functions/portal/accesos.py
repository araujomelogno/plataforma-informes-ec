"""Alta de usuarios sin contraseña, reenvío de acceso y autoservicio.

Como en `paneles` (`usuarios.py`): la cuenta se crea con una clave al azar que
no se guarda ni se devuelve, y la persona entra por un enlace de
restablecimiento generado con el Admin SDK. El enlace sale por correo desde
`notificaciones@`; si el correo falla, el alta igual queda hecha y el enlace
vuelve **una sola vez** en la respuesta para que el admin lo pase por otro
canal. El enlace no se guarda en Firestore ni se loguea.
"""

import datetime
import hashlib
import re
import secrets

from firebase_admin import auth as fb_auth
from google.cloud import firestore

from . import config, correo, envio, plantillas


class ErrorPortal(Exception):
    """Error que se le devuelve al front. `codigo` es un código de
    `HttpsError` (`permission-denied`, `invalid-argument`, ...)."""

    def __init__(self, codigo, mensaje):
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje


_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def normalizar_email(email):
    return str(email or "").strip().lower()


def email_valido(email):
    return bool(_EMAIL.match(email or "")) and len(email) <= 254


def clave_al_azar():
    """Clave inicial de una cuenta nueva. No se guarda, no se loguea y no se
    devuelve: la persona entra por el enlace de restablecimiento."""
    return secrets.token_urlsafe(24)


# ── Quién llama ──────────────────────────────────────────────────────

def exigir_admin(db, auth_ctx):
    """Verifica el rol leyendo `users/{uid}` con el Admin SDK (no se confía en
    nada que mande el cliente). Devuelve `{uid, email}` del admin."""
    if auth_ctx is None or not getattr(auth_ctx, "uid", None):
        raise ErrorPortal("unauthenticated", "Tenés que iniciar sesión.")
    snap = db.collection("users").document(auth_ctx.uid).get()
    datos = (snap.to_dict() or {}) if snap.exists else {}
    if datos.get("role") != "admin":
        raise ErrorPortal("permission-denied",
                          "Solo un administrador puede hacer esto.")
    token = getattr(auth_ctx, "token", None) or {}
    email = token.get("email") or datos.get("email") or None
    return {"uid": auth_ctx.uid, "email": email}


def _disparado_por(actor):
    return {"tipo": "admin", "uid": actor["uid"], "email": actor.get("email")}


# ── El enlace ────────────────────────────────────────────────────────

def generar_enlace(cuentas, email):
    """`(enlace, motivo)`. El enlace puede ser `None`: Firebase puede fallar
    al generarlo (dominio no autorizado, por ejemplo) y eso no invalida el
    alta. El motivo no incluye el enlace."""
    try:
        ajustes = fb_auth.ActionCodeSettings(url=config.PORTAL_URL)
        return cuentas.generate_password_reset_link(email, ajustes), None
    except Exception as error:  # noqa: BLE001
        print(f"[accesos] no se pudo generar el enlace: {type(error).__name__}: "
              f"{str(error)[:200]}")
        return None, ("No se pudo generar el enlace de acceso "
                      f"({type(error).__name__}). Revisá que el dominio de "
                      "PORTAL_URL esté autorizado en Authentication.")


def _mandar_acceso(db, mailer, clave, email, enlace, motivo_sin_enlace,
                   valores, disparado_por, **extra_log):
    if not enlace:
        correo.registrar(db, clave, email, correo.FALLIDO,
                         motivo=motivo_sin_enlace, disparado_por=disparado_por,
                         **extra_log)
        return {"enviado": False, "detalle": motivo_sin_enlace}
    valores = {"email": email, "enlace": enlace,
               "url_portal": config.PORTAL_URL, **valores}
    resultado = envio.enviar_plantilla(db, mailer, clave, email, valores,
                                       disparado_por, **extra_log)
    return {"enviado": resultado["enviado"], "detalle": resultado["detalle"]}


# ── Alta ─────────────────────────────────────────────────────────────

def _ficha_nueva(email, actor):
    return {
        "email": email,
        "role": "user",
        "createdAt": firestore.SERVER_TIMESTAMP,
        "creadoPor": actor.get("email"),
        "creadoPorUid": actor["uid"],
    }


def crear_usuario(db, cuentas, mailer, actor, email):
    """R1 — crea cuenta + `users/{uid}` + enlace + correo de bienvenida.

    Respuesta: `{uid, email, estado, correo: {enviado, detalle}, enlace?}`.
    `estado` es `creado` o `ya_existia`. El enlace solo vuelve si el correo
    no salió (para mostrarlo una vez y copiarlo).
    """
    email = normalizar_email(email)
    if not email_valido(email):
        raise ErrorPortal("invalid-argument", "El email no es válido.")

    try:
        existente = cuentas.get_user_by_email(email)
    except fb_auth.UserNotFoundError:
        existente = None

    if existente is None:
        try:
            cuenta = cuentas.create_user(email=email, password=clave_al_azar(),
                                         email_verified=False)
        except fb_auth.EmailAlreadyExistsError:
            # Carrera: otro admin lo creó recién.
            existente = cuentas.get_user_by_email(email)
        else:
            db.collection("users").document(cuenta.uid).set(
                _ficha_nueva(email, actor))
            enlace, motivo = generar_enlace(cuentas, email)
            resultado = _mandar_acceso(
                db, mailer, plantillas.BIENVENIDA, email, enlace, motivo,
                {"admin": actor.get("email") or ""}, _disparado_por(actor),
                uid=cuenta.uid)
            respuesta = {"uid": cuenta.uid, "email": email, "estado": "creado",
                         "correo": resultado}
            if not resultado["enviado"] and enlace:
                respuesta["enlace"] = enlace
            return respuesta

    # Ya existía en Auth: no se crea otra cuenta ni se toca la clave. Si le
    # falta la ficha (un usuario borrado desde el panel conserva su cuenta de
    # Auth), se recrea para que "Reenviar acceso" le sirva para entrar.
    ref = db.collection("users").document(existente.uid)
    ficha_recreada = False
    if not ref.get().exists:
        ref.set(_ficha_nueva(email, actor))
        ficha_recreada = True
    return {"uid": existente.uid, "email": email, "estado": "ya_existia",
            "fichaRecreada": ficha_recreada,
            "correo": {"enviado": False,
                       "detalle": "La cuenta ya existía: no se envió nada. "
                                  "Usá «Reenviar acceso» si necesita entrar."}}


# ── Reenviar acceso ──────────────────────────────────────────────────

def _nunca_ingreso(cuenta):
    """¿La persona nunca entró al portal? Un último ingreso pegado a la
    creación no cuenta: el alta vieja (`accounts:signUp`) y el emulador lo
    marcan como ingreso al crear la cuenta."""
    meta = getattr(cuenta, "user_metadata", None)
    if not meta:
        return True
    if getattr(meta, "last_refresh_timestamp", None):
        return False
    ultimo = getattr(meta, "last_sign_in_timestamp", None)
    creada = getattr(meta, "creation_timestamp", None) or 0
    return not ultimo or (ultimo - creada) < 5000


def reenviar_acceso(db, cuentas, mailer, actor, uid=None, email=None):
    """R3 — nuevo enlace + correo. Si la persona nunca ingresó va la plantilla
    de bienvenida; si ya ingresó alguna vez, la de restablecer."""
    try:
        if uid:
            cuenta = cuentas.get_user(uid)
        else:
            cuenta = cuentas.get_user_by_email(normalizar_email(email))
    except (fb_auth.UserNotFoundError, ValueError):
        raise ErrorPortal("not-found",
                          "No existe una cuenta de acceso para ese usuario.")
    destino = normalizar_email(cuenta.email)
    if not destino:
        raise ErrorPortal("failed-precondition", "La cuenta no tiene email.")

    clave = plantillas.BIENVENIDA if _nunca_ingreso(cuenta) else plantillas.RESTABLECER
    enlace, motivo = generar_enlace(cuentas, destino)
    valores = {"admin": actor.get("email") or ""}
    resultado = _mandar_acceso(db, mailer, clave, destino, enlace, motivo,
                               valores, _disparado_por(actor), uid=cuenta.uid,
                               reenvio=True)

    # Queda registrado quién lo pidió y cuándo (además del mailLog).
    ref = db.collection("users").document(cuenta.uid)
    try:
        ref.update({
            "ultimoReenvio": {"porUid": actor["uid"], "porEmail": actor.get("email"),
                              "en": firestore.SERVER_TIMESTAMP,
                              "plantilla": clave,
                              "enviado": resultado["enviado"]},
            "reenvios": firestore.Increment(1),
        })
    except Exception:  # noqa: BLE001 — sin ficha (usuario borrado): no se crea acá
        pass

    respuesta = {"uid": cuenta.uid, "email": destino, "plantilla": clave,
                 "correo": resultado}
    if not resultado["enviado"] and enlace:
        respuesta["enlace"] = enlace
    return respuesta


# ── "¿Olvidaste tu contraseña?" (R11) ────────────────────────────────

def _bajo_el_limite(db, email, ahora=None):
    """Hasta `RESTABLECER_POR_HORA` pedidos por dirección y por hora."""
    ahora = ahora or datetime.datetime.now(datetime.timezone.utc)
    clave = hashlib.sha256(email.encode("utf-8")).hexdigest()
    ref = db.collection("limitesCorreo").document(clave)
    transaccion = db.transaction()

    @firestore.transactional
    def _paso(tx):
        snap = ref.get(transaction=tx)
        previos = (snap.to_dict() or {}).get("pedidos", []) if snap.exists else []
        hace_una_hora = ahora - datetime.timedelta(hours=1)
        recientes = [t for t in previos if t and t > hace_una_hora]
        if len(recientes) >= config.RESTABLECER_POR_HORA:
            return False
        tx.set(ref, {"pedidos": recientes + [ahora],
                     "expiraEn": ahora + datetime.timedelta(days=1)})
        return True

    return _paso(transaccion)


def solicitar_restablecimiento(db, cuentas, mailer, email):
    """Responde siempre lo mismo, exista o no la cuenta (anti-enumeración).
    Solo envía si la cuenta existe y tiene ficha en el portal."""
    email = normalizar_email(email)
    if not email_valido(email):
        return {"ok": True}
    if not _bajo_el_limite(db, email):
        return {"ok": True}
    try:
        cuenta = cuentas.get_user_by_email(email)
    except fb_auth.UserNotFoundError:
        return {"ok": True}
    if not db.collection("users").document(cuenta.uid).get().exists:
        return {"ok": True}
    enlace, motivo = generar_enlace(cuentas, email)
    _mandar_acceso(db, mailer, plantillas.RESTABLECER, email, enlace, motivo,
                   {}, {"tipo": "autoservicio"}, uid=cuenta.uid)
    return {"ok": True}


# ── Configuración → Correos ──────────────────────────────────────────

def info_correo(db, mailer):
    """Catálogo de plantillas + cupo diario (para Configuración y la
    validación de la importación masiva)."""
    try:
        enviados = correo.enviados_ultimas_24h(db)
    except Exception as error:  # noqa: BLE001 — falta el índice, por ejemplo
        print(f"[accesos] no se pudo contar el cupo: {type(error).__name__}: "
              f"{str(error)[:200]}")
        enviados = None
    disponible = (max(0, config.CUPO_DIARIO - enviados)
                  if enviados is not None else None)
    return {
        "catalogo": plantillas.catalogo(),
        "enviados24h": enviados,
        "cupoDiario": config.CUPO_DIARIO,
        "disponible": disponible,
        "cuenta": getattr(mailer, "usuario", None),
        "smtpConfigurado": bool(getattr(mailer, "clave", "")),
        "urlPortal": config.PORTAL_URL,
    }


def enviar_prueba(db, mailer, actor, clave, asunto=None, cuerpo=None,
                  remitente_nombre=None, reply_to=None):
    """R10 — manda la plantilla (la guardada o la que se está editando) al
    admin que la pide, con datos de ejemplo."""
    if clave not in plantillas.CLAVES:
        raise ErrorPortal("invalid-argument", "Plantilla desconocida.")
    destino = normalizar_email(actor.get("email"))
    if not email_valido(destino):
        raise ErrorPortal("failed-precondition", "Tu usuario no tiene un email válido.")

    cfg = envio.leer_config(db)
    if asunto is not None or cuerpo is not None:
        guardada = plantillas.plantilla_efectiva(cfg, clave)
        asunto = guardada["asunto"] if asunto is None else asunto
        cuerpo = guardada["cuerpo"] if cuerpo is None else cuerpo
        errores = plantillas.validar(clave, asunto, cuerpo)
        if errores:
            raise ErrorPortal("invalid-argument", " ".join(errores))
        cfg = dict(cfg)
        cfg["plantillas"] = dict(cfg.get("plantillas") or {})
        cfg["plantillas"][clave] = {"asunto": asunto, "cuerpo": cuerpo}
    if remitente_nombre is not None:
        cfg["remitenteNombre"] = remitente_nombre
    if reply_to is not None:
        cfg["replyTo"] = reply_to

    valores = dict(plantillas.EJEMPLO)
    valores["email"] = destino
    valores["url_portal"] = config.PORTAL_URL
    resultado = envio.enviar_plantilla(
        db, mailer, clave, destino, valores, _disparado_por(actor),
        config_correos=cfg, prefijo_asunto="[PRUEBA] ",
        respetar_interruptor=False, prueba=True)
    return {"correo": {"enviado": resultado["enviado"],
                       "detalle": resultado["detalle"]}, "destinatario": destino}
