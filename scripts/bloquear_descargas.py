#!/usr/bin/env python3
"""Deja con la descarga bloqueada todas las asignaciones existentes.

Desde ahora cada asignación nueva arranca con «Bloquear descarga» activado
(`DEFAULT_OPTS` en index.html). Este script pone `noDownload: true` en las que
ya existían, en cada `userAccess/{uid}`:

  · `options[reportId]` de cada informe asignado (y de los que tienen opciones
    guardadas aunque hoy no estén asignados: si se vuelven a asignar, conservan
    sus opciones, que así también quedan con la descarga bloqueada);
  · `folderOptions[folderId]` de cada carpeta asignada (y las que tienen
    opciones guardadas).

Solo toca el campo `noDownload`: el resto de las opciones (marca de agua,
caducidad, quién lo asignó…) queda igual. Es idempotente: lo que ya está
bloqueado no se vuelve a escribir. Cada cambio en `userAccess` dispara el
recálculo del acceso efectivo (Cloud Function), así que los clientes lo ven al
abrir el informe, sin recargar.

Usa la misma autenticación REST como admin que update_report.py y solo la
librería estándar de Python 3.

USO
  python3 scripts/bloquear_descargas.py --dry-run     # muestra qué cambiaría
  python3 scripts/bloquear_descargas.py               # lo aplica
  (credenciales: --email/--password o PORTAL_EMAIL/PORTAL_PASSWORD)
"""

import argparse
import os
import re
import sys
import urllib.parse

import update_report as ur

# Campos por PATCH (cada uno va en la URL como updateMask).
TANDA = 100


def _ruta(*partes):
    """Ruta de campo de Firestore; los segmentos que no son identificadores
    simples (p. ej. un id que empieza con un número) van entre backticks."""
    out = []
    for p in partes:
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", p):
            out.append(p)
        else:
            out.append("`" + p.replace("\\", "\\\\").replace("`", "\\`") + "`")
    return ".".join(out)


def _lista(campo):
    return [v.get("stringValue") for v in ((campo or {}).get("arrayValue") or {}).get("values", [])
            if v.get("stringValue")]


def _mapa(campo):
    return ((campo or {}).get("mapValue") or {}).get("fields") or {}


def _bloqueado(opciones):
    return (_mapa(opciones).get("noDownload") or {}).get("booleanValue") is True


def pendientes(campos):
    """{'options': [rid…], 'folderOptions': [fid…]} que todavía no tienen la
    descarga bloqueada."""
    out = {}
    for mapa, lista in (("options", "reportIds"), ("folderOptions", "folderIds")):
        guardadas = _mapa(campos.get(mapa))
        ids = list(dict.fromkeys(_lista(campos.get(lista)) + list(guardadas)))
        out[mapa] = [i for i in ids if not _bloqueado(guardadas.get(i))]
    return out


def listar_accesos(idtoken):
    docs, page = {}, None
    while True:
        url = f"{ur.FS}/userAccess?pageSize=300" + (f"&pageToken={urllib.parse.quote(page)}" if page else "")
        d = ur._request(url, headers={"Authorization": f"Bearer {idtoken}"})
        for doc in d.get("documents", []):
            docs[doc["name"].split("/")[-1]] = doc.get("fields") or {}
        page = d.get("nextPageToken")
        if not page:
            return docs


def bloquear(uid, cambios, idtoken):
    """PATCH de solo `<mapa>.<id>.noDownload = true` (updateMask), en tandas."""
    pares = [(mapa, i) for mapa, ids in cambios.items() for i in ids]
    for k in range(0, len(pares), TANDA):
        tanda = pares[k:k + TANDA]
        cuerpo = {}
        for mapa, i in tanda:
            cuerpo.setdefault(mapa, {"mapValue": {"fields": {}}})["mapValue"]["fields"][i] = {
                "mapValue": {"fields": {"noDownload": {"booleanValue": True}}}}
        mascara = "&".join("updateMask.fieldPaths=" + urllib.parse.quote(_ruta(mapa, i, "noDownload"))
                           for mapa, i in tanda)
        ur._request(f"{ur.FS}/userAccess/{urllib.parse.quote(uid)}?{mascara}&currentDocument.exists=true",
                    data={"fields": cuerpo}, headers={"Authorization": f"Bearer {idtoken}"}, method="PATCH")


def main():
    ap = argparse.ArgumentParser(description="Bloquea la descarga en todas las asignaciones existentes.")
    ap.add_argument("--email", default=os.environ.get("PORTAL_EMAIL"),
                    help="Email del usuario admin (o variable PORTAL_EMAIL).")
    ap.add_argument("--password", default=os.environ.get("PORTAL_PASSWORD"),
                    help="Contraseña del usuario admin (o variable PORTAL_PASSWORD).")
    ap.add_argument("--dry-run", action="store_true", help="Muestra qué cambiaría, sin escribir nada.")
    args = ap.parse_args()

    if not args.email or not args.password:
        sys.exit("❌ Faltan credenciales. Usá --email/--password o PORTAL_EMAIL/PORTAL_PASSWORD.")
    idtoken, _ = ur.sign_in(args.email, args.password)

    accesos = listar_accesos(idtoken)
    print(f"{len(accesos)} usuarios con asignaciones." + ("  (simulación: no se escribe nada)" if args.dry_run else ""))
    usuarios = informes = carpetas = 0
    for uid, campos in sorted(accesos.items()):
        cambios = pendientes(campos)
        n_inf, n_car = len(cambios["options"]), len(cambios["folderOptions"])
        if not n_inf and not n_car:
            continue
        usuarios += 1
        informes += n_inf
        carpetas += n_car
        print(f"   {uid}: {n_inf} informe(s), {n_car} carpeta(s)")
        if not args.dry_run:
            bloquear(uid, cambios, idtoken)

    resumen = f"{informes} asignaciones de informes y {carpetas} de carpetas, en {usuarios} usuarios"
    if args.dry_run:
        print(f"\nSe bloquearía la descarga en {resumen}. Corré sin --dry-run para aplicarlo.")
    else:
        print(f"\n✅ Descarga bloqueada en {resumen}." if usuarios else "\n✅ 0 cambios: todas las asignaciones ya tenían la descarga bloqueada.")


if __name__ == "__main__":
    main()
