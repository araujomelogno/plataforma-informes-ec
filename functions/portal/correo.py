"""Envío de correo por Google Workspace y su registro en Firestore.

Portado de `paneles` (`functions/panel_api/correo.py`): SMTP de Google
Workspace (`smtp.gmail.com:587`, STARTTLS) autenticando como
`notificaciones@equipos.com.uy` con una **contraseña de aplicación** que vive
en Secret Manager (`SMTP_PASSWORD`). Lo que cambia respecto de `paneles`:

- Las plantillas no viven acá sino en `plantillas.py` (con textos por defecto
  en código y overrides editables en `config/correos`).
- El registro va a Firestore (`mailLog`) en vez de Postgres, y se purga solo
  con una política TTL de Firestore sobre `expiraEn`.
- El nombre visible del remitente y el Reply-To se configuran por envío
  (Configuración → Correos).

Decisiones que se mantienen:

**Reintentar es acotado, y lo acota el tiempo.** Un fallo transitorio se
reintenta dentro de un presupuesto de segundos; uno permanente (credencial
rechazada, destinatario inválido) no, porque insistir no lo arregla.

**El envío se registra, salga o no.** Es lo que deja ver los fallidos con su
motivo y contar cuántos correos salen por día (tope de Workspace).

**La contraseña nunca se loguea, ni se devuelve, ni aparece en un mensaje de
error**: los errores de `smtplib` traen el código y el texto del servidor,
no las credenciales.
"""

import datetime
import smtplib
import socket
import ssl
import time
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid, parseaddr

from . import config

HOST_POR_DEFECTO = "smtp.gmail.com"
PUERTO_POR_DEFECTO = 587
USUARIO_POR_DEFECTO = "notificaciones@equipos.com.uy"
NOMBRE_POR_DEFECTO = "Equipos Consultores"

# Cuánto puede tardar un intento y cuánto el envío entero. Un admin espera la
# respuesta de la pantalla: más de unos segundos y vuelve a apretar el botón.
TIEMPO_POR_INTENTO_S = 8
PRESUPUESTO_S = 15
REINTENTOS = 2

COLECCION_LOG = "mailLog"

ENVIADO = "enviado"
FALLIDO = "fallido"
OMITIDO = "omitido"


class ErrorEnvio(RuntimeError):
    """El proveedor no pudo entregar. `transitorio` dice si vale reintentar."""

    def __init__(self, motivo, transitorio=False, intentos=1):
        super().__init__(motivo)
        self.motivo = motivo
        self.transitorio = transitorio
        self.intentos = intentos


def _entero(valor, por_defecto):
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return por_defecto


class Workspace:
    """SMTP de Google Workspace: 587 con STARTTLS, o 465 con SSL."""

    nombre = "workspace"

    def __init__(self, clave, host=HOST_POR_DEFECTO, puerto=PUERTO_POR_DEFECTO,
                 usuario=USUARIO_POR_DEFECTO, tiempo=TIEMPO_POR_INTENTO_S,
                 presupuesto=PRESUPUESTO_S, reintentos=REINTENTOS,
                 smtp=None, reloj=time.monotonic, esperar=time.sleep):
        self.clave = clave
        self.host = host
        self.puerto = int(puerto)
        self.usuario = usuario
        self.tiempo = tiempo
        self.presupuesto = presupuesto
        self.reintentos = reintentos
        # Para las pruebas: una fábrica `(host, puerto, timeout, ssl) -> conexión`
        # que imita a smtplib. En producción es smtplib.
        self._smtp = smtp
        self._reloj = reloj
        self._esperar = esperar

    @classmethod
    def desde_entorno(cls, entorno=None):
        import os
        entorno = os.environ if entorno is None else entorno
        return cls(
            clave=(entorno.get("SMTP_PASSWORD") or "").strip(),
            host=(entorno.get("SMTP_HOST") or HOST_POR_DEFECTO).strip(),
            puerto=_entero(entorno.get("SMTP_PORT") or PUERTO_POR_DEFECTO,
                           PUERTO_POR_DEFECTO),
            usuario=(entorno.get("SMTP_USUARIO") or USUARIO_POR_DEFECTO).strip(),
            tiempo=_entero(entorno.get("SMTP_TIEMPO_S") or TIEMPO_POR_INTENTO_S,
                           TIEMPO_POR_INTENTO_S),
            presupuesto=_entero(entorno.get("SMTP_PRESUPUESTO_S") or PRESUPUESTO_S,
                                PRESUPUESTO_S),
        )

    # ── El mensaje ──

    def mensaje(self, destino, asunto, texto, nombre=None, reply_to=None):
        msg = EmailMessage()
        # El remitente es siempre la cuenta autenticada: Workspace rechaza (o
        # reescribe) un From que no sea la cuenta o un alias suyo. Lo único
        # configurable es el nombre visible.
        msg["From"] = formataddr((nombre or NOMBRE_POR_DEFECTO, self.usuario))
        msg["To"] = destino
        msg["Subject"] = asunto
        msg["Date"] = formatdate(localtime=False)
        msg["Message-ID"] = make_msgid(domain=self.usuario.split("@")[-1])
        if reply_to:
            msg["Reply-To"] = reply_to
        msg.set_content(texto)
        return msg

    # ── La conexión ──

    def _conectar(self, timeout):
        if self._smtp is not None:
            return self._smtp(self.host, self.puerto, timeout, self.puerto == 465)
        contexto = ssl.create_default_context()
        if self.puerto == 465:
            return smtplib.SMTP_SSL(self.host, self.puerto, timeout=timeout,
                                    context=contexto)
        conexion = smtplib.SMTP(self.host, self.puerto, timeout=timeout)
        conexion.ehlo()
        conexion.starttls(context=contexto)
        conexion.ehlo()
        return conexion

    def _un_intento(self, msg, timeout):
        conexion = self._conectar(timeout)
        try:
            conexion.login(self.usuario, self.clave)
            conexion.send_message(msg)
        finally:
            try:
                conexion.quit()
            except Exception:  # noqa: BLE001 — cerrar no puede tapar el resultado
                pass

    @staticmethod
    def _clasificar(error):
        """`(motivo, transitorio)`. El motivo no lleva credenciales: smtplib
        reporta el código y el texto del servidor, nada más."""
        if isinstance(error, smtplib.SMTPAuthenticationError):
            return (f"Workspace rechazó la credencial ({error.smtp_code}). "
                    "Revisá SMTP_USUARIO y que SMTP_PASSWORD sea una contraseña "
                    "de aplicación vigente.", False)
        if isinstance(error, smtplib.SMTPRecipientsRefused):
            respuestas = list(error.recipients.values())
            codigos = [c for c, _ in respuestas]
            transitorio = all(400 <= c < 500 for c in codigos) if codigos else False
            detalle = "; ".join(
                f"{c} {t.decode('utf-8', 'replace') if isinstance(t, bytes) else t}"
                for c, t in respuestas)
            return (f"El servidor rechazó el destinatario: {detalle[:200]}", transitorio)
        if isinstance(error, smtplib.SMTPSenderRefused):
            return (f"El servidor rechazó el remitente ({error.smtp_code}). "
                    "SMTP_USUARIO tiene que ser la cuenta autenticada.",
                    400 <= error.smtp_code < 500)
        if isinstance(error, smtplib.SMTPResponseException):
            texto = error.smtp_error
            if isinstance(texto, bytes):
                texto = texto.decode("utf-8", "replace")
            return (f"El servidor respondió {error.smtp_code}: {str(texto)[:200]}",
                    400 <= error.smtp_code < 500)
        if isinstance(error, (smtplib.SMTPServerDisconnected,
                              smtplib.SMTPConnectError)):
            return (f"Se cortó la conexión con {_texto_de_error(error)}.", True)
        if isinstance(error, (socket.timeout, TimeoutError)):
            return ("El servidor de correo no respondió a tiempo.", True)
        if isinstance(error, OSError):
            return (f"No se pudo llegar al servidor de correo: "
                    f"{_texto_de_error(error)}", True)
        return (f"Error inesperado al enviar: {_texto_de_error(error)}", False)

    def enviar(self, destino, asunto, texto, nombre=None, reply_to=None):
        """Manda el mensaje. Devuelve `{intentos, ms}` o levanta `ErrorEnvio`."""
        if not self.clave:
            raise ErrorEnvio(
                "Falta SMTP_PASSWORD (la contraseña de aplicación de "
                f"{self.usuario}, en Secret Manager).", transitorio=False,
                intentos=0)
        msg = self.mensaje(destino, asunto, texto, nombre, reply_to)
        desde = self._reloj()
        limite = desde + self.presupuesto
        intentos, ultimo = 0, None
        while intentos <= self.reintentos:
            restante = limite - self._reloj()
            if restante <= 0.5:
                break
            intentos += 1
            try:
                self._un_intento(msg, min(self.tiempo, restante))
                return {"intentos": intentos,
                        "ms": int((self._reloj() - desde) * 1000)}
            except Exception as error:  # noqa: BLE001 — se clasifica abajo
                motivo, transitorio = self._clasificar(error)
                ultimo = ErrorEnvio(motivo, transitorio, intentos)
                if not transitorio:
                    raise ultimo from error
                # Espera corta y creciente, sin pasarse del presupuesto.
                pausa = min(0.5 * intentos, max(0.0, limite - self._reloj() - 1))
                if pausa > 0 and intentos <= self.reintentos:
                    self._esperar(pausa)
        if ultimo is None:
            ultimo = ErrorEnvio("Se agotó el tiempo para enviar el correo.",
                                True, intentos)
        raise ultimo


def _texto_de_error(error):
    return str(error)[:200] or type(error).__name__


# ── Registro de envíos (Firestore: mailLog) ──────────────────────────

def _ahora():
    return datetime.datetime.now(datetime.timezone.utc)


def fila_de_registro(tipo, destinatario, estado, motivo=None, intentos=0,
                     duracion_ms=None, disparado_por=None, **extra):
    """Los campos de un documento de `mailLog`. Nunca lleva el enlace ni
    credenciales: solo qué se mandó, a quién y cómo salió."""
    from google.cloud import firestore

    fila = {
        "tipo": tipo,
        "destinatario": (destinatario or "").strip().lower(),
        "estado": estado,
        "motivo": (motivo or None) and str(motivo)[:500],
        "intentos": int(intentos or 0),
        "duracionMs": duracion_ms,
        "disparadoPor": disparado_por or {"tipo": "sistema"},
        "creadoEn": firestore.SERVER_TIMESTAMP,
        # TTL de Firestore: el documento se borra solo pasado este momento.
        "expiraEn": _ahora() + datetime.timedelta(days=config.DIAS_DE_REGISTRO),
    }
    fila.update({k: v for k, v in extra.items() if v is not None})
    return fila


def registrar(db, tipo, destinatario, estado, doc_id=None, **campos):
    """Una fila por intento de envío, salga o no. Devuelve el id."""
    ref = (db.collection(COLECCION_LOG).document(doc_id) if doc_id
           else db.collection(COLECCION_LOG).document())
    ref.set(fila_de_registro(tipo, destinatario, estado, **campos))
    return ref.id


def enviados_ultimas_24h(db):
    """Cuántos correos salieron en las últimas 24 h (para el cupo diario)."""
    from google.cloud.firestore_v1.base_query import FieldFilter

    desde = _ahora() - datetime.timedelta(hours=24)
    consulta = (db.collection(COLECCION_LOG)
                .where(filter=FieldFilter("estado", "==", ENVIADO))
                .where(filter=FieldFilter("creadoEn", ">", desde)))
    resultado = consulta.count().get()
    return int(resultado[0][0].value)
