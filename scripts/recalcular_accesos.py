#!/usr/bin/env python3
"""Recalcula el acceso efectivo de los usuarios y verifica la migración (C10).

Los permisos por carpeta se expanden en `accesoEfectivo/{uid}` (lo escriben las
Cloud Functions; las reglas lo leen en lugar de `userAccess`). Antes de desplegar
las reglas nuevas, cada usuario tiene que tener su `accesoEfectivo` con todos sus
informes directos: si no, pierde acceso.

Este script:
  1. Llama a la función `recalcularAccesos` (la misma del botón «🔄 Recalcular
     accesos» de Configuración), para todos o para un --uid.
  2. Verifica, leyendo Firestore como admin, que todo `userAccess/{uid}` tiene
     su `accesoEfectivo/{uid}` y que `userAccess.reportIds ⊆ accesoEfectivo.reportIds`
     (sin contar los informes borrados). En régimen informa «0 diferencias».

Usa la misma autenticación REST como admin que update_report.py y solo la
librería estándar de Python 3.

USO
  python3 scripts/recalcular_accesos.py                    # recalcula a todos y verifica
  python3 scripts/recalcular_accesos.py --solo-verificar   # solo verifica
  python3 scripts/recalcular_accesos.py --uid <UID>        # recalcula a uno
  (credenciales: --email/--password o PORTAL_EMAIL/PORTAL_PASSWORD)

La URL de las funciones sale de PORTAL_FUNCTIONS_URL o, si no está, de
https://{PORTAL_REGION}-{PORTAL_PROJECT_ID}.cloudfunctions.net.
"""

import argparse
import os
import sys
import urllib.parse

import update_report as ur

REGION = os.environ.get("PORTAL_REGION", "us-central1")


def functions_url():
    return os.environ.get("PORTAL_FUNCTIONS_URL") or f"https://{REGION}-{ur.PROJECT_ID}.cloudfunctions.net"


def llamar(nombre, datos, idtoken):
    """Llama a una función callable (protocolo de Firebase: {"data": …} → {"result": …})."""
    r = ur._request(f"{functions_url()}/{nombre}", data={"data": datos},
                    headers={"Authorization": f"Bearer {idtoken}"}, method="POST")
    if "error" in r:
        sys.exit(f"❌ {nombre}: {r['error'].get('message') or r['error']}")
    return r.get("result") or {}


def _lista(campo):
    return [v.get("stringValue") for v in ((campo or {}).get("arrayValue") or {}).get("values", [])
            if v.get("stringValue")]


def listar(coleccion, idtoken):
    """{id: fields} de toda una colección (paginado)."""
    docs, page = {}, None
    while True:
        url = f"{ur.FS}/{coleccion}?pageSize=300" + (f"&pageToken={urllib.parse.quote(page)}" if page else "")
        d = ur._request(url, headers={"Authorization": f"Bearer {idtoken}"})
        for doc in d.get("documents", []):
            docs[doc["name"].split("/")[-1]] = doc.get("fields") or {}
        page = d.get("nextPageToken")
        if not page:
            return docs


def verificar(idtoken):
    accesos = listar("userAccess", idtoken)
    efectivos = listar("accesoEfectivo", idtoken)
    existentes = {r["id"] for r in ur.list_reports(idtoken)}
    diferencias = []
    for uid, campos in sorted(accesos.items()):
        directos = [r for r in dict.fromkeys(_lista(campos.get("reportIds"))) if r in existentes]
        if uid not in efectivos:
            diferencias.append((uid, "sin accesoEfectivo", directos))
            continue
        tiene = set(_lista(efectivos[uid].get("reportIds")))
        faltan = [r for r in directos if r not in tiene]
        if faltan:
            diferencias.append((uid, "faltan informes", faltan))
    return len(accesos), diferencias


def main():
    ap = argparse.ArgumentParser(description="Recalcula y verifica el acceso efectivo (permisos por carpeta).")
    ap.add_argument("--email", default=os.environ.get("PORTAL_EMAIL"),
                    help="Email del usuario admin (o variable PORTAL_EMAIL).")
    ap.add_argument("--password", default=os.environ.get("PORTAL_PASSWORD"),
                    help="Contraseña del usuario admin (o variable PORTAL_PASSWORD).")
    ap.add_argument("--uid", help="Recalcular solo este usuario.")
    ap.add_argument("--solo-verificar", action="store_true", help="No recalcula: solo informa las diferencias.")
    args = ap.parse_args()

    if not args.email or not args.password:
        sys.exit("❌ Faltan credenciales. Usá --email/--password o PORTAL_EMAIL/PORTAL_PASSWORD.")
    idtoken, _ = ur.sign_in(args.email, args.password)

    if not args.solo_verificar:
        r = llamar("recalcularAccesos", {"uid": args.uid} if args.uid else {}, idtoken)
        print(f"🔄 Recalculados: {r.get('total', 0)} usuarios · {r.get('cambiados', 0)} con cambios.")

    total, diferencias = verificar(idtoken)
    print(f"\n{total} usuarios con userAccess.")
    for uid, motivo, ids in diferencias:
        print(f"   {uid}: {motivo} {', '.join(ids[:10])}{' …' if len(ids) > 10 else ''}")
    if diferencias:
        sys.exit(f"\n❌ {len(diferencias)} diferencias. No despliegues las reglas: volvé a correr el recálculo "
                 "y, si siguen, revisá los logs de las funciones.")
    print("✅ 0 diferencias: todo userAccess tiene su accesoEfectivo con sus informes directos.")


if __name__ == "__main__":
    main()
