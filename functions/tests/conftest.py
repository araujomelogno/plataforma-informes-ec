"""Pruebas del backend.

Las de lógica pura corren siempre. Las que tocan Firestore y Auth corren
contra los **emuladores** y se saltean si no están levantados:

    firebase emulators:exec --only firestore,auth --project demo-portal \
        "cd functions && venv/bin/python -m pytest -q"
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROYECTO = "demo-portal"
CON_EMULADORES = bool(os.environ.get("FIRESTORE_EMULATOR_HOST")
                      and os.environ.get("FIREBASE_AUTH_EMULATOR_HOST"))

requiere_emuladores = pytest.mark.skipif(
    not CON_EMULADORES,
    reason="Necesita FIRESTORE_EMULATOR_HOST y FIREBASE_AUTH_EMULATOR_HOST")


class MailerFalso:
    """Imita a `correo.Workspace`: registra lo que se mandaría."""

    usuario = "notificaciones@equipos.com.uy"
    clave = "x"

    def __init__(self, error=None):
        self.enviados = []
        self.error = error

    def enviar(self, destino, asunto, texto, nombre=None, reply_to=None):
        if self.error:
            raise self.error
        self.enviados.append({"destino": destino, "asunto": asunto,
                              "texto": texto, "nombre": nombre,
                              "reply_to": reply_to})
        return {"intentos": 1, "ms": 5}


class Actor:
    def __init__(self, uid, email=None):
        self.uid = uid
        self.token = {"email": email} if email else {}


@pytest.fixture
def mailer():
    return MailerFalso()


def _limpiar_emuladores():
    import requests  # viene con firebase-admin

    fs = os.environ["FIRESTORE_EMULATOR_HOST"]
    au = os.environ["FIREBASE_AUTH_EMULATOR_HOST"]
    requests.delete(f"http://{fs}/emulator/v1/projects/{PROYECTO}/databases/(default)/documents",
                    timeout=10)
    requests.delete(f"http://{au}/emulator/v1/projects/{PROYECTO}/accounts", timeout=10)


@pytest.fixture
def entorno():
    """`(db, cuentas)` contra los emuladores, vacíos."""
    if not CON_EMULADORES:
        pytest.skip("sin emuladores")
    os.environ.setdefault("GCLOUD_PROJECT", PROYECTO)
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", PROYECTO)
    import firebase_admin
    from firebase_admin import auth, firestore

    try:
        app = firebase_admin.get_app()
    except ValueError:
        from firebase_admin import credentials
        from google.auth.credentials import AnonymousCredentials

        class _Anonima(credentials.Base):  # los emuladores no validan credenciales
            def get_credential(self):
                return AnonymousCredentials()

        app = firebase_admin.initialize_app(_Anonima(), options={"projectId": PROYECTO})
    _limpiar_emuladores()
    return firestore.client(app), auth


@pytest.fixture
def admin(entorno):
    db, cuentas = entorno
    cuenta = cuentas.create_user(email="admin@equipos.com.uy", password="secreto123")
    db.collection("users").document(cuenta.uid).set(
        {"email": "admin@equipos.com.uy", "role": "admin"})
    return Actor(cuenta.uid, "admin@equipos.com.uy")
