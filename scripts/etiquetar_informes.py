#!/usr/bin/env python3
"""Etiqueta cada archivo de informes en Storage con el id de su doc en Firestore.

Las reglas de Storage dejan leer un archivo de reports/ a un cliente solo si su
metadata personalizada `reportId` figura en userAccess/{uid}.reportIds. El portal
ya etiqueta lo que sube o reescribe; este script etiqueta los archivos que se
subieron antes (migración única, ver docs/DESPLIEGUE_cierre_acceso_y_encriptacion.md).

Recorre la colección `reports` y, para cada doc, hace PATCH de la metadata del
objeto `storagePath` con {"metadata": {"reportId": <id>}}. Es idempotente: si el
objeto ya tiene la etiqueta correcta no lo toca. Al final informa:
  · etiquetados (o "a etiquetar" con --dry-run),
  · docs cuyo archivo no existe en Storage,
  · archivos de reports/ sin doc (huérfanos).
Solo informa: no borra nada.

Usa la misma autenticación REST como admin que update_report.py y solo la
librería estándar de Python 3.

USO
  python3 scripts/etiquetar_informes.py --dry-run --email admin@equipos.com.uy --password '…'
  python3 scripts/etiquetar_informes.py --email admin@equipos.com.uy --password '…'
  (o con las variables PORTAL_EMAIL / PORTAL_PASSWORD)
"""

import argparse
import os
import sys
import urllib.parse

from update_report import STOR, _request, get_metadata, list_reports, sign_in, tag_report_id


def list_storage_objects(prefix, idtoken):
    """Nombres de todos los objetos bajo `prefix` (paginado)."""
    names, page = [], None
    while True:
        q = {"prefix": prefix, "delimiter": "/"}
        if page:
            q["pageToken"] = page
        d = _request(f"{STOR}?{urllib.parse.urlencode(q)}", headers={"Authorization": f"Firebase {idtoken}"})
        names += [it["name"] for it in d.get("items", [])]
        page = d.get("nextPageToken")
        if not page:
            return names


def main():
    ap = argparse.ArgumentParser(description="Etiqueta los archivos de informes con metadata.reportId.")
    ap.add_argument("--email", default=os.environ.get("PORTAL_EMAIL"),
                    help="Email del usuario admin (o variable PORTAL_EMAIL).")
    ap.add_argument("--password", default=os.environ.get("PORTAL_PASSWORD"),
                    help="Contraseña del usuario admin (o variable PORTAL_PASSWORD).")
    ap.add_argument("--dry-run", action="store_true", help="Muestra qué haría, sin escribir nada.")
    args = ap.parse_args()

    if not args.email or not args.password:
        sys.exit("❌ Faltan credenciales. Usá --email/--password o PORTAL_EMAIL/PORTAL_PASSWORD.")

    idtoken, _ = sign_in(args.email, args.password)
    reports = list_reports(idtoken)
    print(f"{len(reports)} informes en Firestore." + ("  (simulación: no se escribe nada)" if args.dry_run else ""))

    etiquetados, ya_ok, sin_archivo, sin_ruta, pendientes = [], [], [], [], []
    rutas_con_doc = set()
    for r in reports:
        path = r["storagePath"]
        if not path:
            sin_ruta.append(r)
            continue
        rutas_con_doc.add(path)
        meta = get_metadata(path, idtoken)
        if meta is None:
            sin_archivo.append(r)
            continue
        actual = (meta.get("metadata") or {}).get("reportId")
        if actual == r["id"]:
            ya_ok.append(r)
            continue
        if actual:
            print(f"⚠ {path}: tenía reportId={actual}, se corrige a {r['id']}")
        if args.dry_run:
            etiquetados.append(r)
            continue
        tag_report_id(path, r["id"], idtoken)
        nuevo = (get_metadata(path, idtoken) or {}).get("metadata") or {}
        (etiquetados if nuevo.get("reportId") == r["id"] else pendientes).append(r)

    huerfanos = [n for n in list_storage_objects("reports/", idtoken) if n not in rutas_con_doc]

    verbo = "A etiquetar" if args.dry_run else "Etiquetados"
    print(f"\n── {verbo}: {len(etiquetados)}")
    for r in etiquetados:
        print(f"   {r['id']}  {r['storagePath']}")
    print(f"── Ya tenían la etiqueta correcta: {len(ya_ok)}")
    print(f"── Docs cuyo archivo no existe en Storage: {len(sin_archivo)}")
    for r in sin_archivo:
        print(f"   {r['id']}  {r['storagePath']}  ({r['name']})")
    if sin_ruta:
        print(f"── Docs sin storagePath: {len(sin_ruta)}")
        for r in sin_ruta:
            print(f"   {r['id']}  ({r['name']})")
    print(f"── Archivos de reports/ sin doc (huérfanos, no se tocan): {len(huerfanos)}")
    for n in huerfanos:
        print(f"   {n}")

    if args.dry_run:
        print(f"\n{len(etiquetados)} cambios pendientes. Corré sin --dry-run para aplicarlos.")
        return
    if pendientes:
        print(f"\n❌ {len(pendientes)} objetos quedaron sin etiqueta (falló la verificación):")
        for r in pendientes:
            print(f"   {r['id']}  {r['storagePath']}")
        sys.exit(1)
    print(f"\n✅ {len(etiquetados)} cambios. 0 objetos sin etiqueta (sin contar los huérfanos).")


if __name__ == "__main__":
    main()
