"""Configuración que cambia entre ambientes: viene del entorno.

Lo que no es secreto vive en `functions/.env` (versionado); la contraseña de
aplicación del SMTP vive en Secret Manager (`SMTP_PASSWORD`) y Firebase la
inyecta como variable de entorno solo en las funciones que la declaran.
"""

import os


def _texto(nombre, por_defecto):
    return (os.environ.get(nombre) or por_defecto).strip()


def _entero(nombre, por_defecto):
    try:
        return int(str(os.environ.get(nombre) or por_defecto).strip())
    except (TypeError, ValueError):
        return por_defecto


# Región de las funciones. Tiene que ser la misma que la de Firestore del
# proyecto (el trigger de `userAccess` escucha a la base desde esa región) y
# la misma que `FUNCTIONS_REGION` en `index.html`.
REGION = _texto("REGION", "us-central1")

# URL pública del portal: va en los correos ({{url_portal}}) y es a donde
# vuelve la persona después de fijar su contraseña.
PORTAL_URL = _texto("PORTAL_URL", "https://portal-informes-ec.web.app")

# Cuántos correos por día puede usar este portal. Workspace corta en 2.000
# destinatarios diarios por cuenta, y `notificaciones@` se comparte con
# `paneles`, cuyo consumo no se ve desde acá: el resto queda para él.
CUPO_DIARIO = _entero("CORREO_CUPO_DIARIO", 1500)

# Cuánto se conserva el registro de envíos (TTL de Firestore sobre `expiraEn`).
DIAS_DE_REGISTRO = _entero("CORREO_DIAS_REGISTRO", 90)

# Autoservicio "¿Olvidaste tu contraseña?": cuántos correos por dirección y
# por hora, para que nadie use el formulario para inundar una casilla.
RESTABLECER_POR_HORA = _entero("RESTABLECER_POR_HORA", 3)
