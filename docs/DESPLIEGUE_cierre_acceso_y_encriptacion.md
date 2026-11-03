# Despliegue — Cierre de acceso a archivos e informes encriptados

**Proyecto Firebase:** `portal-informes-ec` · **Spec:** «SPEC — Cierre de acceso a archivos e informes encriptados» (2 nov 2026)

Dos cambios: **(A)** las reglas dejan de permitir que cualquier usuario con login liste y baje todos los informes, y que cualquiera sin login liste los enlaces públicos; **(B)** el admin puede subir un informe **encriptado** con clave, en formato OpenPGP estándar (un `.gpg` que también se abre con `gpg -d`). No hay Cloud Functions, colecciones, índices ni secretos nuevos.

> ⚠️ **El orden importa.** Si se despliegan las reglas antes de etiquetar los archivos existentes, **todos los clientes pierden acceso** a sus informes. Seguí los pasos en orden.
>
> ⚠️ `firebase.json` ahora incluye `storage.rules`. Hasta terminar el paso 3, **no corras `firebase deploy` sin `--only`**: desplegaría las reglas nuevas de Storage antes de tiempo.

## Qué cambia

| Requisito | Dónde | Qué hace |
| --- | --- | --- |
| A1 | `uploadFiles()`, `overwriteReport()` | El id del doc se genera antes de subir. Cada archivo de `reports/` lleva `customMetadata.reportId`, también al reescribir (Storage reemplaza la metadata al sobrescribir). |
| A2 | `scripts/etiquetar_informes.py` (nuevo) | Migración: etiqueta los archivos subidos antes. `--dry-run`, idempotente. Informa docs sin archivo y archivos huérfanos; no borra nada. |
| A3, B8 | `scripts/update_report.py` | Después de sobrescribir vuelve a poner la etiqueta y la verifica con un GET. Con un informe encriptado solo acepta un `.gpg` que empiece con un paquete SKESK (cifrado con contraseña); nunca sube texto plano. |
| A4 | `storage.rules` | Un cliente lee `reports/…` solo si `metadata.reportId` está en su `userAccess/{uid}.reportIds`. El admin lee todo. Un archivo sin etiqueta solo lo lee el admin. |
| A5 | `firestore.rules`, `loadUserReports()` | `reports`: `get` solo de lo asignado, `list` solo admin. El portal trae cada informe por separado y tolera los que la regla niega. |
| A6 | `firestore.rules` | `publicLinks`: `get` abierto (el enlace sigue funcionando), `list` solo admin. |
| A7 | `tests/rules/`, `firebase.json` | Tests de reglas contra los emuladores. Emulador de Storage en el puerto 9199. |
| B1, B11 | Subida | Casilla «🔒 Encriptar con clave», clave + confirmación (mín. 10), «🎲 Generar clave». El objeto queda en `reports/{ts}_{nombre}.gpg` como `application/pgp-encrypted`: un mensaje OpenPGP (SKESK v4 + SEIPD v1, AES-256, S2K SHA-256 count 65.011.712) que abre `gpg -d`. El doc suma `encrypted: true, encFormat: 'openpgp'` y `name` sin `.gpg`. Video y archivos > 100 MB no se encriptan: se avisa y el admin elige subirlos sin encriptar o dejarlos afuera. |
| B2 | Subida | Un `.gpg`/`.pgp` cifrado con `gpg -c` se sube tal cual como encriptado, sin pedir clave. Uno cifrado para una clave GPG se rechaza (no se sube nada). Uno que no es OpenPGP, o de más de 100 MB, va como archivo común y se avisa. |
| B3 | `openUserReport()`, `previewReport()`, `decryptReport()` | Modal de clave. Clave incorrecta ⇒ «Clave incorrecta» y se reintenta sin volver a bajar el archivo. La clave de sesión queda en memoria (`_sessionKeys`) hasta cerrar sesión. |
| B4 | `openViewer()`, `renderPdf/Docx`, `closeViewer()` | Fuente URL o `{bytes, name}`. El HTML descifrado va en una `blob:` URL con `sandbox` **sin** `allow-same-origin`. Las `blob:` se revocan al cerrar. Los informes no encriptados no cambian. |
| B5 | Visor, `downloadReport()` | «⬇ Descargar» (descifrado, con su nombre) y «🔐 Descargar cifrado (.gpg)». El admin las tiene siempre; el cliente, salvo con «bloquear descarga». |
| B6 | Enlace público, modo `?p=` | El enlace de un encriptado es `/?p=TOKEN#k=9.<clave de sesión en base64url>`. El `#k` no llega al servidor ni se guarda. Al reabrir el diálogo se reconstruye con la clave. Sin `#k`, el visitante puede ingresar la clave. El diálogo muestra, plegado, el comando `gpg --override-session-key`. |
| B7 | `overwriteReport()` | Desde el portal: pide la clave y cifra con la misma clave de sesión y contraseña (el `#k` sigue sirviendo); con la clave incorrecta no toca el archivo. Con un `.gpg` hecho en local: avisa que el enlace público cambia y, al terminar, abre el diálogo del enlace para regenerarlo. |
| B9 | `cifrado.js`, `vendor/openpgp-6.3.2.min.mjs`, `tests/cifrado/` | OpenPGP.js 6.3.2 incluido en el repo (LGPL-3.0, licencia en `vendor/openpgp-LICENSE.txt`), no desde un CDN. `cifrado.js` lo usa con la configuración compatible con gpg 2.2/2.4. Tests con interoperabilidad con `gpg`. |
| B10 | `docs/manual-usuario.html` | Admin §16 y cliente §5. |

Respuestas que asume la implementación para las preguntas abiertas de la spec:

1. **Política de clave:** mínimo 10 caracteres; el generador es opcional.
2. **Video encriptado:** no (queda para otra spec).
3. **Carpetas:** los clientes siguen pudiendo leer los nombres de todas las carpetas.
4. **Nombre del archivo:** va cifrado dentro del `.gpg`, pero sigue visible en Firestore (`name`) y en el `storagePath`.

Fuera de esta entrega (P1 de la spec): caducidad en las reglas (A8), cambiar la clave (B12), encriptar/desencriptar un informe existente (B13), aceptar `.asc` (B14), «recordar la clave» en `sessionStorage` (B15) y quitar `#k` de la barra de direcciones (B16).

## Pasos

Desde la raíz del repo, con `main` actualizado (PR mergeado) y `firebase use portal-informes-ec`.

1. **Front** (las subidas y reescrituras nuevas ya quedan etiquetadas; las reglas viejas no se ven afectadas):

   ```bash
   firebase deploy --only hosting --project portal-informes-ec
   ```

2. **Migración de los archivos existentes.** Con un usuario admin del portal:

   ```bash
   export PORTAL_EMAIL='admin@equipos.com.uy'
   export PORTAL_PASSWORD='…'
   python3 scripts/etiquetar_informes.py --dry-run
   ```

   Revisá la salida: «A etiquetar», «Docs cuyo archivo no existe» y «huérfanos». Después:

   ```bash
   python3 scripts/etiquetar_informes.py
   ```

3. **Confirmar.** Volvé a correr el script: tiene que terminar con **«0 cambios. 0 objetos sin etiqueta»**. Los «docs cuyo archivo no existe» ya no abrían antes; los huérfanos no los ve ningún cliente. Ninguno de los dos bloquea el paso 4.

   Si alguien sube o reescribe un informe desde un front viejo (pestaña abierta antes del paso 1) entre el paso 3 y el 4, ese archivo queda sin etiqueta. Para cubrirlo, corré el script una vez más justo antes del paso 4.

4. **Reglas:**

   ```bash
   firebase deploy --only firestore:rules,storage --project portal-informes-ec
   ```

   Las reglas de Storage ya leían Firestore (`firestore.get`), así que el permiso entre servicios está otorgado. Si la CLI pregunta si otorgar el rol, respondé que sí.

5. **Prueba manual** con un usuario cliente real (ver Verificación).

**CORS:** los informes encriptados se bajan con `fetch` (también los HTML, que antes iban directo al iframe). Necesitan el CORS del bucket configurado con `cors.json`, igual que hoy PDF/Word. Si ya se ven PDF en el visor, está configurado.

**`vendor/openpgp-6.3.2.min.mjs`** se sirve desde Hosting junto con `cifrado.js`. Para comprobar que es la versión publicada en npm: `sha256sum vendor/openpgp-6.3.2.min.mjs` debe dar `7d3285efa6dfedbb34a136d8b5ad21c28fb973269df0b2818dcb74dfb40b59d9` (el `dist/openpgp.min.mjs` del paquete `openpgp@6.3.2`).

## Verificación (criterios de aceptación)

Recargando con Ctrl/Cmd+Shift+R.

**Cierre de acceso (como cliente, en la consola F12 del portal)**

1. ☐ El cliente ve y abre sus informes en «Mis Informes».
2. ☐ `await db.collection('reports').get()` da `permission-denied`.
3. ☐ `await storage.ref('<storagePath de un informe NO asignado>').getDownloadURL()` da `storage/unauthorized`.
4. ☐ `await db.collection('publicLinks').get()` da `permission-denied`, también en una ventana privada sin login (`/?p=x` y en la consola).
5. ☐ Un enlace público existente (`/?p=TOKEN`) abre igual que antes en una ventana privada.
6. ☐ Como admin: subir, ver, reescribir y borrar un informe funciona. En la consola de Storage, el archivo tiene la metadata `reportId` igual al id de su doc, también después de reescribirlo.
7. ☐ `python3 scripts/update_report.py --report-id X --file …` sobre un informe asignado: el cliente lo sigue abriendo.

**Encriptados**

8. ☐ Subir un HTML con «🔒 Encriptar con clave»: con una clave corta o la confirmación distinta no deja subir. Al terminar aparece «Guardá la clave…» y la lista muestra 🔒.
9. ☐ En la consola de Storage el objeto termina en `.gpg` y es `application/pgp-encrypted`; el doc tiene `encrypted: true`, `encFormat: 'openpgp'` y ningún campo con la clave.
10. ☐ «🔐 Descargar cifrado (.gpg)» y después `gpg -d informe.html.gpg` con la clave devuelve el archivo original.
11. ☐ Cifrar en local con `gpg -c --cipher-algo AES256 --s2k-digest-algo SHA256 --s2k-count 65011712 informe.html` y subir `informe.html.gpg`: no pide clave, queda 🔒 como `informe.html` y abre en el portal con la clave. Un `.gpg` cifrado para una clave pública (`gpg -e -r …`) se rechaza y no se sube nada.
12. ☐ El cliente lo abre con la clave. Con una incorrecta ve «Clave incorrecta» y puede reintentar. Al reabrirlo no le pide la clave; después de salir y volver a entrar, sí.
13. ☐ El cliente ve «⬇ Descargar» y «🔐 Descargar cifrado (.gpg)» en el visor; con «bloquear descarga», ninguna.
14. ☐ Con `examples/dashboard-parametros.html` encriptado, el informe recibe los parámetros del usuario. Con un dashboard instrumentado, «Analítica de dashboards» registra sus eventos.
15. ☐ En la consola del iframe del informe (selector de contexto de F12), `parent.document` da error y `indexedDB.open('x')` da `SecurityError`.
16. ☐ Marca de agua, bloqueo de impresión y de copia funcionan igual que en uno sin encriptar.
17. ☐ «🔗 Link público» pide la clave y genera `…/?p=TOKEN#k=9.…`. Abierto en una ventana privada se ve sin pedir nada; sin el `#k=…` pide la clave. En la pestaña Network el valor de `k` no aparece en ninguna petición. El contador de accesos suma. El comando plegado `gpg --override-session-key '9:…' -d` descifra el `.gpg` sin la clave.
18. ☐ Reescribir el informe encriptado desde el portal: con una clave incorrecta se cancela sin cambios; con la correcta, el mismo enlace `#k=` muestra el contenido nuevo.
19. ☐ Reescribirlo con un `.gpg` hecho en local avisa que el enlace cambia y, al terminar, abre el diálogo del enlace para obtener el nuevo.
20. ☐ `update_report.py` sobre un informe encriptado con un `.html` aborta («pasá un .gpg cifrado con gpg -c…»); con un `.gpg` de `gpg -c` lo sube y avisa que hay que regenerar el enlace público.

## Tests

Requieren Node 22+ (y Java 11+ para los emuladores).

```bash
cd tests/cifrado && npm test
```

Los tests de interoperabilidad usan `gpg` si está instalado (gpg cifra/descifra lo de la librería y viceversa, y `--list-packets` confirma SKESK v4, AES-256, sin AEAD, count 65011712); si no está, se saltean.

```bash
cd tests/rules && npm install && npm test
```

`tests/rules` levanta los emuladores de Firestore y Storage con `firebase emulators:exec` (usa el `firebase.json` de la raíz) y prueba los criterios de A4, A5 y A6. Es solo una dependencia de desarrollo: `tests/**` no se despliega.

## Rollback

Volver a desplegar las reglas del commit anterior:

```bash
git checkout <commit anterior> -- firestore.rules storage.rules
```

```bash
firebase deploy --only firestore:rules,storage --project portal-informes-ec
```

La etiqueta de metadata no molesta con las reglas viejas. Los informes encriptados siguen necesitando el front nuevo para abrirse en el portal: si se vuelve atrás el hosting, esos informes no se pueden ver ahí, pero el `.gpg` de Storage se sigue abriendo con `gpg -d` y la clave.
