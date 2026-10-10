"""Plantillas de correo: textos por defecto, variables, validación y armado.

Los textos por defecto viven acá, en código. El equipo los puede pisar desde
Configuración → Correos (doc `config/correos` en Firestore) sin deploy: si una
plantilla nunca se editó, se usa la de acá.

Formato: texto plano con variables `{{nombre}}`, que se reemplazan en el
servidor. Una variable desconocida se rechaza al guardar (en el front) y, por
las dudas, se deja vacía al enviar. Si una línea tiene variables y **todas**
quedaron vacías (por ejemplo `Carpeta: {{carpeta}}` en un informe sin
carpeta), la línea se omite entera.
"""

import re

BIENVENIDA = "bienvenida"
RESTABLECER = "restablecer"
NUEVO_INFORME = "nuevoInforme"
CLAVES = (BIENVENIDA, RESTABLECER, NUEVO_INFORME)

NOMBRES = {
    BIENVENIDA: "Bienvenida (alta de usuario)",
    RESTABLECER: "Restablecer contraseña",
    NUEVO_INFORME: "Nuevo informe",
}

# Qué variables admite cada plantilla (tabla de la spec).
VARIABLES = {
    BIENVENIDA: ("email", "enlace", "url_portal", "admin"),
    RESTABLECER: ("email", "enlace", "url_portal"),
    NUEVO_INFORME: ("email", "url_portal", "admin", "informe", "carpeta", "vence"),
}

# Variables sin las cuales la plantilla no sirve: un correo de acceso sin el
# enlace deja a la persona sin forma de entrar.
OBLIGATORIAS = {
    BIENVENIDA: ("enlace",),
    RESTABLECER: ("enlace",),
    NUEVO_INFORME: (),
}

DESCRIPCION_VARIABLES = {
    "email": "Email del usuario destinatario",
    "enlace": "Enlace para fijar la contraseña",
    "url_portal": "URL del portal",
    "admin": "Email del admin que dio el alta o el acceso",
    "informe": "Nombre del informe (si son varios, la lista)",
    "carpeta": "Carpeta del informe, si tiene",
    "vence": "Fecha de caducidad del acceso, si se configuró",
}

# Las plantillas que tienen interruptor "Enviar este correo". Las de acceso no:
# apagarlas dejaría altas sin forma de entrar (el enlace igual se muestra).
CON_INTERRUPTOR = (NUEVO_INFORME,)

FIRMA = (
    "\n\n—\nEquipos Consultores · Portal de informes\n"
    "Este correo se envió automáticamente. Si no esperabas recibirlo, "
    "podés ignorarlo."
)

POR_DEFECTO = {
    BIENVENIDA: {
        "asunto": "Tu acceso al Portal de Informes de Equipos Consultores",
        "cuerpo": (
            "Hola:\n\n"
            "{{admin}} te dio acceso al Portal de Informes de Equipos "
            "Consultores con la dirección {{email}}.\n\n"
            "Para entrar, primero creá tu contraseña desde este enlace:\n"
            "{{enlace}}\n\n"
            "El enlace sirve una sola vez y vence a la hora. Si venció, entrá a "
            "{{url_portal}}, escribí tu email y tocá «¿Olvidaste tu "
            "contraseña?» para recibir uno nuevo.\n\n"
            "Después vas a ingresar siempre en {{url_portal}} con tu email y "
            "la contraseña que elegiste."
        ),
        "activo": True,
    },
    RESTABLECER: {
        "asunto": "Elegí una contraseña nueva para el Portal de Informes",
        "cuerpo": (
            "Hola:\n\n"
            "Recibimos un pedido para elegir una contraseña nueva para tu "
            "cuenta ({{email}}) en el Portal de Informes de Equipos "
            "Consultores.\n\n"
            "Elegila desde este enlace:\n"
            "{{enlace}}\n\n"
            "El enlace sirve una sola vez y vence a la hora. Si venció, pedí "
            "otro con «¿Olvidaste tu contraseña?» en {{url_portal}}.\n\n"
            "Si no lo pediste vos, ignorá este correo: tu contraseña actual "
            "sigue igual."
        ),
        "activo": True,
    },
    NUEVO_INFORME: {
        "asunto": "Nuevo material en el Portal de Informes: {{informe}}",
        "cuerpo": (
            "Hola:\n\n"
            "Tenés material nuevo disponible en el Portal de Informes de "
            "Equipos Consultores:\n\n"
            "{{informe}}\n"
            "Carpeta: {{carpeta}}\n"
            "Disponible hasta: {{vence}}\n\n"
            "Para verlo, ingresá en {{url_portal}} con tu email y tu "
            "contraseña.\n\n"
            "Acceso habilitado por {{admin}}."
        ),
        "activo": True,
    },
}

# Datos de ejemplo para el correo de prueba y la vista previa.
EJEMPLO = {
    "email": "cliente@empresa.com",
    "enlace": "https://portal-informes-ec.firebaseapp.com/__/auth/action?mode=resetPassword&oobCode=EJEMPLO",
    "admin": "admin@equipos.com.uy",
    "informe": "Informe de ejemplo — Estudio de satisfacción 2026",
    "carpeta": "Clientes / Empresa / 2026",
    "vence": "31/12/2026",
}

LIMITE_ASUNTO = 200
LIMITE_CUERPO = 10000

_VARIABLE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def variables_usadas(texto):
    return [m.group(1) for m in _VARIABLE.finditer(texto or "")]


def validar(clave, asunto, cuerpo):
    """Lista de errores (vacía si la plantilla se puede guardar)."""
    if clave not in CLAVES:
        return [f"Plantilla desconocida: {clave!r}."]
    errores = []
    asunto = asunto or ""
    cuerpo = cuerpo or ""
    if not asunto.strip():
        errores.append("El asunto no puede quedar vacío.")
    if not cuerpo.strip():
        errores.append("El cuerpo no puede quedar vacío.")
    if len(asunto) > LIMITE_ASUNTO:
        errores.append(f"El asunto supera los {LIMITE_ASUNTO} caracteres.")
    if len(cuerpo) > LIMITE_CUERPO:
        errores.append(f"El cuerpo supera los {LIMITE_CUERPO} caracteres.")
    permitidas = set(VARIABLES[clave])
    desconocidas = sorted({v for v in variables_usadas(asunto + "\n" + cuerpo)
                           if v not in permitidas})
    if desconocidas:
        errores.append("Variables desconocidas para esta plantilla: "
                       + ", ".join("{{" + v + "}}" for v in desconocidas) + ".")
    for obligatoria in OBLIGATORIAS[clave]:
        if obligatoria not in variables_usadas(cuerpo):
            errores.append(f"El cuerpo tiene que incluir {{{{{obligatoria}}}}}.")
    return errores


def _reemplazar_linea(linea, valores, permitidas):
    encontradas = list(_VARIABLE.finditer(linea))
    if not encontradas:
        return linea

    def valor(m):
        nombre = m.group(1)
        if nombre not in permitidas:
            return ""
        return str(valores.get(nombre) or "")

    if all(not valor(m) for m in encontradas):
        return None  # todas vacías → la línea se omite
    return _VARIABLE.sub(valor, linea)


def reemplazar(texto, valores, permitidas):
    lineas = []
    for linea in (texto or "").split("\n"):
        nueva = _reemplazar_linea(linea, valores, permitidas)
        if nueva is not None:
            lineas.append(nueva)
    return "\n".join(lineas)


def plantilla_efectiva(config_correos, clave):
    """Asunto, cuerpo y `activo` en uso: lo editado o, si no, lo del código."""
    defecto = POR_DEFECTO[clave]
    editada = ((config_correos or {}).get("plantillas") or {}).get(clave) or {}
    asunto = editada.get("asunto") or defecto["asunto"]
    cuerpo = editada.get("cuerpo") or defecto["cuerpo"]
    activo = editada.get("activo")
    return {
        "asunto": asunto,
        "cuerpo": cuerpo,
        "activo": defecto["activo"] if activo is None else bool(activo),
    }


def armar(config_correos, clave, valores):
    """`(asunto, texto)` listos para mandar.

    `valores['informe']` puede ser una lista (aviso agrupado): en el asunto va
    separada por comas y en el cuerpo, un renglón por informe.
    """
    p = plantilla_efectiva(config_correos, clave)
    permitidas = set(VARIABLES[clave])
    valores = dict(valores or {})
    informe = valores.get("informe")
    valores_asunto = dict(valores)
    if isinstance(informe, (list, tuple)):
        valores_asunto["informe"] = ", ".join(str(x) for x in informe)
        valores["informe"] = "\n".join(f"• {x}" for x in informe)
    asunto = reemplazar(p["asunto"], valores_asunto, permitidas)
    # Un salto de línea en el asunto rompe la cabecera del correo.
    asunto = re.sub(r"\s+", " ", asunto).strip()
    if len(asunto) > 250:
        asunto = asunto[:247].rstrip() + "…"
    cuerpo = reemplazar(p["cuerpo"], valores, permitidas)
    return asunto, cuerpo.rstrip() + FIRMA


def remitente(config_correos):
    """`(nombre_visible, reply_to)` configurados (o los de siempre)."""
    cfg = config_correos or {}
    nombre = (cfg.get("remitenteNombre") or "").strip() or "Equipos Consultores"
    reply_to = (cfg.get("replyTo") or "").strip() or None
    # Sin saltos de línea: van a cabeceras del correo.
    nombre = re.sub(r"[\r\n]+", " ", nombre)[:80]
    if reply_to and (not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", reply_to)):
        reply_to = None
    return nombre, reply_to


def catalogo():
    """Lo que el panel necesita para editar: defaults, variables y reglas."""
    return {
        "claves": list(CLAVES),
        "nombres": NOMBRES,
        "porDefecto": POR_DEFECTO,
        "variables": {k: list(v) for k, v in VARIABLES.items()},
        "obligatorias": {k: list(v) for k, v in OBLIGATORIAS.items()},
        "descripcionVariables": DESCRIPCION_VARIABLES,
        "conInterruptor": list(CON_INTERRUPTOR),
        "firma": FIRMA,
        "ejemplo": EJEMPLO,
    }
