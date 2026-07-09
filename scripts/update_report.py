#!/usr/bin/env python3
"""Actualiza (sobrescribe) un informe del Portal de Informes vía la REST API de Firebase.

No requiere backend ni Cloud Functions: se autentica como un usuario administrador
del portal, sube el archivo nuevo a la MISMA ruta de Storage del informe (lo
sobrescribe) y, si ese informe tiene un enlace público, refresca su URL para que
siga funcionando.

Solo usa la librería estándar de Python 3 (no hace falta `pip install`).

────────────────────────────────────────────────────────────────────────────
USO

  # 1) Listar los informes para conocer sus IDs
  python3 update_report.py --list \
      --email admin@equipos.com.uy --password 'TU_PASSWORD'

  # 2) Sobrescribir un informe por su ID
  python3 update_report.py --report-id <ID> --file ./nuevo.html \
      --email admin@equipos.com.uy --password 'TU_PASSWORD'

Las credenciales también pueden ir en variables de entorno, para no dejarlas en
el historial de la terminal ni en scripts:

  export PORTAL_EMAIL='admin@equipos.com.uy'
  export PORTAL_PASSWORD='TU_PASSWORD'
  python3 update_report.py --report-id <ID> --file ./nuevo.html

RECOMENDACIÓN: creá un usuario admin "de servicio" dedicado para esta integración
(no reutilices tu usuario personal), así podés rotar/revocar sus credenciales sin
afectar tu acceso.
────────────────────────────────────────────────────────────────────────────
"""

import argparse
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

# ── Configuración del proyecto (valores públicos; se pueden pisar por entorno) ──
API_KEY    = os.environ.get("PORTAL_API_KEY",    "AIzaSyCNYTImSJphSSfcfPuMsgKWCFy26VH2fBk")
PROJECT_ID = os.environ.get("PORTAL_PROJECT_ID", "portal-informes-ec")
BUCKET     = os.environ.get("PORTAL_BUCKET",     "portal-informes-ec.firebasestorage.app")

IDTK   = "https://identitytoolkit.googleapis.com/v1"
FS     = f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/(default)/documents"
STOR   = f"https://firebasestorage.googleapis.com/v0/b/{BUCKET}/o"


def _request(url, data=None, headers=None, method=None):
    """HTTP genérico. Serializa dict/list como JSON. Devuelve el JSON de respuesta."""
    hdrs = dict(headers or {})
    if isinstance(data, (dict, list)):
        data = json.dumps(data).encode()
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise SystemExit(f"❌ Error HTTP {e.code} en {url}\n{detail}")
    except urllib.error.URLError as e:
        raise SystemExit(f"❌ Error de conexión con {url}: {e.reason}")


def sign_in(email, password):
    """Devuelve (idToken, uid) autenticando al usuario admin por email/contraseña."""
    d = _request(
        f"{IDTK}/accounts:signInWithPassword?key={API_KEY}",
        {"email": email, "password": password, "returnSecureToken": True},
    )
    return d["idToken"], d["localId"]


def _unwrap(value):
    """Convierte un valor tipado de Firestore ({'stringValue': ...}) a algo plano."""
    if not isinstance(value, dict) or not value:
        return value
    (kind, v), = value.items()
    if kind == "integerValue":
        return int(v)
    if kind == "doubleValue":
        return float(v)
    if kind == "booleanValue":
        return bool(v)
    return v  # stringValue, timestampValue, nullValue, etc.


def parse_fields(doc):
    return {k: _unwrap(v) for k, v in (doc.get("fields") or {}).items()}


def fs_get(path, idtoken):
    return _request(f"{FS}/{path}", headers={"Authorization": f"Bearer {idtoken}"})


def list_reports(idtoken):
    reports, page = [], None
    while True:
        url = f"{FS}/reports?pageSize=300" + (f"&pageToken={page}" if page else "")
        d = _request(url, headers={"Authorization": f"Bearer {idtoken}"})
        for doc in d.get("documents", []):
            rid = doc["name"].split("/")[-1]
            f = parse_fields(doc)
            reports.append({
                "id": rid,
                "name": f.get("name", ""),
                "storagePath": f.get("storagePath", ""),
                "publicToken": f.get("publicToken"),
            })
        page = d.get("nextPageToken")
        if not page:
            break
    return reports


def overwrite_file(storage_path, file_bytes, content_type, idtoken):
    """Sube (sobrescribe) el archivo en la ruta dada. Devuelve la metadata (con downloadTokens)."""
    name = urllib.parse.quote(storage_path, safe="")
    return _request(
        f"{STOR}?name={name}",
        data=file_bytes,
        headers={"Authorization": f"Firebase {idtoken}", "Content-Type": content_type},
        method="POST",
    )


def build_download_url(storage_path, token):
    name = urllib.parse.quote(storage_path, safe="")
    return f"{STOR}/{name}?alt=media&token={token}"


def patch_report_size(report_id, size, idtoken):
    _request(
        f"{FS}/reports/{report_id}?updateMask.fieldPaths=size",
        data={"fields": {"size": {"integerValue": str(size)}}},
        headers={"Authorization": f"Bearer {idtoken}"},
        method="PATCH",
    )


def patch_public_link_url(public_token, new_url, idtoken):
    _request(
        f"{FS}/publicLinks/{public_token}?updateMask.fieldPaths=url",
        data={"fields": {"url": {"stringValue": new_url}}},
        headers={"Authorization": f"Bearer {idtoken}"},
        method="PATCH",
    )


def main():
    ap = argparse.ArgumentParser(
        description="Sobrescribe un informe del Portal de Informes vía la REST API de Firebase.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--email", default=os.environ.get("PORTAL_EMAIL"),
                    help="Email del usuario admin (o variable PORTAL_EMAIL).")
    ap.add_argument("--password", default=os.environ.get("PORTAL_PASSWORD"),
                    help="Contraseña del usuario admin (o variable PORTAL_PASSWORD).")
    ap.add_argument("--list", action="store_true",
                    help="Lista los informes (id, nombre) y termina.")
    ap.add_argument("--report-id", help="ID de Firestore del informe a sobrescribir.")
    ap.add_argument("--file", help="Ruta del archivo nuevo que reemplazará al informe.")
    args = ap.parse_args()

    if not args.email or not args.password:
        sys.exit("❌ Faltan credenciales. Usá --email/--password o PORTAL_EMAIL/PORTAL_PASSWORD.")

    idtoken, uid = sign_in(args.email, args.password)

    if args.list:
        reports = list_reports(idtoken)
        if not reports:
            print("(No hay informes.)")
            return
        print(f"{'ID':<24}  {'NOMBRE'}")
        print("-" * 60)
        for r in reports:
            flag = "  🔗 público" if r["publicToken"] else ""
            print(f"{r['id']:<24}  {r['name']}{flag}")
        return

    if not args.report_id or not args.file:
        sys.exit("❌ Para sobrescribir necesitás --report-id y --file. (Usá --list para ver los IDs.)")

    if not os.path.isfile(args.file):
        sys.exit(f"❌ No existe el archivo: {args.file}")

    # 1) Leer el informe para conocer su ruta de Storage y si tiene enlace público
    doc = fs_get(f"reports/{args.report_id}", idtoken)
    fields = parse_fields(doc)
    storage_path = fields.get("storagePath")
    if not storage_path:
        sys.exit("❌ El informe no tiene 'storagePath'. Verificá el --report-id.")
    public_token = fields.get("publicToken")

    # 2) Sobrescribir el archivo en la misma ruta
    with open(args.file, "rb") as fh:
        data = fh.read()
    content_type = mimetypes.guess_type(args.file)[0] or "text/html"
    meta = overwrite_file(storage_path, data, content_type, idtoken)
    print(f"✅ Informe sobrescrito: '{fields.get('name', storage_path)}'  ({len(data)} bytes, {content_type})")

    # 3) Actualizar el tamaño en la metadata del informe (columna 'Tamaño' del panel)
    try:
        patch_report_size(args.report_id, len(data), idtoken)
    except SystemExit as e:
        print(f"⚠ No se pudo actualizar el tamaño en la metadata: {e}")

    # 4) Si tiene enlace público, refrescar su URL (el token de descarga cambió al sobrescribir)
    if public_token:
        tokens = str(meta.get("downloadTokens", "") or "")
        token = tokens.split(",")[0] if tokens else ""
        if token:
            patch_public_link_url(public_token, build_download_url(storage_path, token), idtoken)
            print("🔗 Enlace público actualizado (sigue funcionando con el contenido nuevo).")
        else:
            print("⚠ No se obtuvo el token de descarga nuevo. Regenerá el enlace público "
                  "desde el panel de administración para que apunte al contenido actualizado.")

    print("Listo.")


if __name__ == "__main__":
    main()
