# SPEC — Cierre de acceso a archivos e informes encriptados

Nov 3, 2026 · @Equipos

## Resumen

Dos cambios sobre el portal. Se implementan en este orden, porque el B se apoya en el A:

- **(A)** Cerrar un agujero de las reglas actuales. Hoy cualquier usuario con login puede listar y bajar **todos** los informes, y cualquier persona **sin login** puede listar todos los enlaces públicos.
- **(B)** Permitir que el admin marque un informe como **encriptado**. Se usa el estándar **OpenPGP** (cifrado simétrico, igual que `gpg -c`): el archivo se cifra en el navegador antes de subirlo, se puede abrir también fuera del portal con `gpg -d` y el admin puede subir `.gpg` cifrados en su máquina. Para los enlaces públicos, la clave de sesión viaja en el fragmento de la URL (`#k=…`), que el navegador nunca manda al servidor.

Repositorio `araujomelogno/plataforma-informes-ec`, revisado sobre `cc40c98`.

---

## Cambio A — Cerrar el acceso a archivos y metadatos

### Cómo funciona hoy

| Dónde | Regla actual | Efecto |
| --- | --- | --- |
| `storage.rules` → `reports/{fileName}` | `allow read: if request.auth != null` | Cualquier usuario con login puede pedir `getDownloadURL()` de **cualquier** informe |
| `firestore.rules` → `reports/{reportId}` | `allow read: if isAuth()` | Cualquier usuario con login puede hacer `db.collection('reports').get()` y obtener el `storagePath` y el nombre de **todos** los informes |
| `firestore.rules` → `publicLinks/{token}` | `allow read: if true` | `read` incluye `list`: cualquiera **sin login** puede listar la colección y obtener las URLs de descarga de todos los enlaces públicos, también los de informes que nunca recibió |

La combinación de las dos primeras filas es el problema principal. Un cliente con las herramientas de desarrollo del navegador (F12) puede ejecutar `db.collection('reports').get()`, recorrer los `storagePath` y bajar informes de otros clientes. La pantalla de "mis informes" filtra por `userAccess`, pero el backend no.

Hay otro detalle: la ruta en Storage (`reports/{Date.now()}_{nombre}`) no contiene el `reportId`, así que hoy la regla de Storage no tiene forma de cruzar el archivo con `userAccess/{uid}.reportIds`.

### Objetivos

1. Un usuario no admin solo puede leer (en Firestore y en Storage) los informes que figuran en su `userAccess/{uid}.reportIds`.
2. Nadie sin login puede listar `publicLinks`. Los enlaces públicos existentes siguen funcionando.
3. Los usuarios actuales no pierden acceso a ningún informe asignado durante la migración.

### No-objetivos

- **Aplicar la caducidad (`options[reportId].expiresAt`) en las reglas.** Sigue controlada en el front (P1 abajo).
- **Restringir la lectura de `folders`.** Un cliente sigue pudiendo leer los nombres de todas las carpetas (no su contenido). Ver pregunta abierta 3.
- **Invalidar URLs de descarga ya entregadas.** Las URLs de Storage con `token=` son permanentes. Quien ya obtuvo una la conserva aunque le quiten el acceso. Para el contenido sensible, la respuesta es el cambio B.

### Requisitos P0

**A1. Etiquetar cada archivo con su `reportId`.** Todo objeto en `reports/` lleva la metadata personalizada `customMetadata.reportId = <id del doc en reports>`.

- `uploadFiles()`: generar primero la referencia con `const ref = db.collection('reports').doc()`, subir con `{ contentType, customMetadata: { reportId: ref.id } }` y crear el doc con `ref.set({...})` en lugar de `.add()`.
- Reescritura de informe (el flujo que hoy hace `storage.ref(target.storagePath).put(file, {contentType})`): incluir el mismo `customMetadata.reportId`. Al sobrescribir, Storage **reemplaza** la metadata, y sin la etiqueta el informe queda ilegible para los clientes.
- La fachada de Storage (`window.storage`, cerca de la línea 100) ya pasa `meta` a `uploadBytesResumable`. Verificar que `customMetadata` llegue.

Criterios:

- [ ] Un informe recién subido tiene `metadata.reportId` igual al id de su doc (se puede ver en la consola de Storage).
- [ ] Después de reescribir un informe, la etiqueta sigue presente.

**A2. Script de migración de archivos existentes.** Nuevo `scripts/etiquetar_informes.py`, con la misma autenticación REST como admin que usa `update_report.py` (solo librería estándar).

- Recorre `reports` en Firestore y hace PATCH de la metadata del objeto `storagePath` con `{"metadata": {"reportId": id}}`.
- `--dry-run` muestra qué haría sin escribir nada.
- Es idempotente: si el objeto ya tiene la etiqueta correcta, no hace nada.
- Al final informa tres listas: etiquetados, docs cuyo archivo no existe y archivos de `reports/` sin doc (huérfanos). Solo informa; no borra nada.

Criterios:

- [ ] Correrlo dos veces seguidas deja la segunda corrida con "0 cambios".
- [ ] Al terminar, informa "0 objetos sin etiqueta" (excluyendo los huérfanos).

**A3. `update_report.py` conserva la etiqueta.** Después del POST que sobrescribe el archivo, hace PATCH de `metadata.reportId`, o sube en multipart con la metadata incluida; Claude Code elige la opción que funcione. Al final verifica con un GET de metadata.

- [ ] Después de `update_report.py --report-id X`, un usuario con acceso a X lo sigue abriendo.

**A4. Regla de Storage.**

```
match /reports/{fileName} {
  allow read: if request.auth != null && (
    isAdminSt() ||
    (resource.metadata.reportId is string &&
     firestore.exists(/databases/(default)/documents/userAccess/$(request.auth.uid)) &&
     resource.metadata.reportId in
       firestore.get(/databases/(default)/documents/userAccess/$(request.auth.uid)).data.get('reportIds', []))
  );
  allow write: if isAdminSt();   // igual que hoy
}
```

`isAdminSt()` es una función con el mismo `firestore.get(.../users/uid).data.role == 'admin'` de hoy. La regla de `clientDocs/` no cambia.

- [ ] Un cliente con acceso al informe X obtiene `getDownloadURL()` de X.
- [ ] El mismo cliente recibe `storage/unauthorized` al pedir la URL de un informe Y no asignado.
- [ ] Un admin lee, sube, reescribe y borra cualquier informe.

**A5. Regla de Firestore para `reports`.**

```
match /reports/{reportId} {
  allow get:  if isAdmin() || (isAuth() &&
    reportId in get(/databases/$(database)/documents/userAccess/$(request.auth.uid)).data.get('reportIds', []));
  allow list: if isAdmin();
  allow write: if isAdmin();
}
```

Si `userAccess/{uid}` no existe, el `get()` de la regla falla y la regla niega. Es el resultado correcto, pero el front tiene que tolerarlo.

- `loadUserReports()` ya trae los informes uno por uno con `.doc(id).get()`, así que es compatible. Hay que envolver cada `get` en `try/catch → null` para que un id viejo o sin permiso no rompa todo el `Promise.all`.
- [ ] `db.collection('reports').get()` ejecutado por un cliente desde la consola devuelve `permission-denied`.
- [ ] El cliente sigue viendo y abriendo sus informes en "Mis informes".

**A6. `publicLinks`: separar `get` de `list`.**

```
match /publicLinks/{token} {
  allow get:    if true;
  allow list:   if isAdmin();
  allow create, delete: if isAdmin();
  allow update: if <igual que hoy>;
}
```

- [ ] Un visitante sin login abre `/?p=TOKEN` igual que hoy.
- [ ] `db.collection('publicLinks').get()` sin login o como cliente da `permission-denied`.

**A7. Tests de reglas.** Nueva carpeta `tests/rules/` con `@firebase/rules-unit-testing` contra el emulador (Firestore + Storage). Agregar Storage a `emulators` en `firebase.json` (puerto 9199, el mismo que ya usa `connectStorageEmulator`).

Casos mínimos: los criterios de A4, A5 y A6, más: admin lee todo, cliente sin doc `userAccess` no lee nada, y cliente con acceso no lee un archivo sin etiqueta. Se corre con `npm test` dentro de `tests/rules/`. Es solo una dependencia de desarrollo; no se despliega.

### P1

- **A8. Caducidad en las reglas.** Aplicar `options[reportId].expiresAt` (formato `'YYYY-MM-DD'`) también en Storage y Firestore, comparando con `request.time`.

### Orden de despliegue de A (importante)

Si se despliegan las reglas antes de etiquetar los archivos, **todos los clientes pierden acceso**. El orden es:

1. Desplegar hosting con A1 (`firebase deploy --only hosting`). Las subidas nuevas ya quedan etiquetadas.
2. Correr `etiquetar_informes.py --dry-run`, revisar la salida y después correrlo sin `--dry-run`.
3. Confirmar "0 objetos sin etiqueta".
4. Desplegar las reglas: `firebase deploy --only firestore:rules,storage`.
5. Prueba manual con un usuario cliente real: abre lo suyo y no puede bajar lo ajeno desde la consola.

**Rollback:** volver a desplegar las reglas del commit anterior. La etiqueta de metadata no molesta con las reglas viejas.

Documentar estos pasos en `docs/DESPLIEGUE_cierre_acceso_y_encriptacion.md`, con el mismo estilo que los otros documentos de despliegue.

---

## Cambio B — Informes encriptados con OpenPGP

### Problema

Algunos informes son sensibles: datos de un cliente puntual, resultados antes de publicarse. Se quiere que aunque el archivo se filtre (una URL con token copiada, un acceso mal asignado, una cuenta comprometida), el contenido sea ilegible sin una clave que el admin entrega por otro canal.

Además, el archivo cifrado tiene que poder abrirse **fuera del portal con `gpg`**, como respaldo y para poder cifrar en la máquina del admin. Por eso se usa el estándar OpenPGP (cifrado simétrico, igual que `gpg -c`) y no un formato propio.

### Objetivos

1. El admin marca "🔒 Encriptar" al subir un informe y define una clave. El archivo en Storage queda como un `.gpg` estándar, y ni Google ni el portal guardan la clave.
2. El admin también puede subir un `.gpg` que cifró en su máquina con `gpg -c`. El portal lo reconoce y lo trata como informe encriptado.
3. Un usuario con acceso abre el informe ingresando la clave. Con la clave correcta lo ve igual que un informe normal (visor, parámetros, analítica y protecciones).
4. Cualquier `.gpg` del portal se descifra con `gpg -d` y la misma clave.
5. Un enlace público de un informe encriptado se abre sin escribir nada, porque la **clave de sesión** va en el fragmento `#k=…`. El servidor nunca la recibe.
6. Reescribir un informe encriptado desde el portal no rompe su enlace público.

### No-objetivos

- **Recuperar una clave olvidada.** No existe recuperación por diseño. El admin conserva el original y puede volver a subirlo.
- **Cifrado con clave pública** (archivos cifrados para la clave GPG de una persona). El portal solo maneja cifrado simétrico con contraseña.
- **Cifrar documentos subidos por clientes** (`clientDocs`).
- **Gestionar claves por usuario.** Hay una clave por informe y la comparten todos los que tienen acceso.
- **Cifrar video en P0** (ver B11).

### Historias de usuario

- Como admin, quiero marcar un informe como encriptado al subirlo, para que si el archivo se filtra no se pueda leer.
- Como admin, quiero cifrar un informe en mi máquina con `gpg -c` y subir el `.gpg`, sin que el portal vea nunca el original.
- Como admin, quiero poder abrir con `gpg -d` cualquier informe encriptado del portal, aunque el portal no esté disponible.
- Como cliente, quiero abrir un informe encriptado escribiendo la clave que me pasaron, y no tener que volver a escribirla cada vez que lo abro en la misma pestaña.
- Como cliente, quiero poder bajarme el `.gpg` (si el admin permite descargas), para guardarlo o reenviarlo protegido.
- Como admin, quiero generar un enlace público de un informe encriptado que funcione con solo abrirlo, sin que la clave quede guardada en el servidor.
- Como admin, quiero reescribir un informe encriptado sin que el enlace público que ya mandé deje de funcionar.

### Diseño criptográfico

**Librería:** [OpenPGP.js](https://github.com/openpgpjs/openpgpjs) **6.3.2** (licencia LGPL-3.0). Usa Web Crypto por debajo para AES.

Se **incluye en el repo** como `vendor/openpgp-6.3.2.min.mjs` (395 KB, unos 130 KB comprimido), en vez de cargarla desde un CDN como las librerías de los visores. Es la librería que maneja las claves, y un CDN comprometido o un `@latest` podría robarlas. Se carga con `import()` solo cuando hace falta cifrar o descifrar.

**Formato del archivo:** un mensaje OpenPGP binario, compatible con gpg 2.2 y 2.4:

| Paquete | Contenido |
| --- | --- |
| SKESK v4 (tag 3) | Clave de sesión cifrada con la contraseña. S2K iterado con salt, SHA-256, count 65.011.712 (el máximo, igual que el que se usa con gpg) |
| SEIPD v1 (tag 18) | Contenido cifrado con AES-256 y chequeo de integridad (MDC) |
| Literal data (dentro del cifrado) | Bytes del archivo + nombre original (`informe.html`) |

**Configuración obligatoria de OpenPGP.js:**

```js
const CFG = {
  aeadProtect: false,                                     // SEIPD v1: gpg 2.2/2.4 no leen el v2 (AEAD)
  preferredSymmetricAlgorithm: openpgp.enums.symmetric.aes256,
  s2kIterationCountByte: 255,                             // count 65.011.712; el default de la librería es más bajo
};
// s2kType queda en 'iterated' (default). Argon2 no lo leen gpg 2.2/2.4.
```

**Clave de sesión y por qué importa.** El portal genera una clave de sesión aleatoria de 256 bits y la pasa a `openpgp.encrypt({ ..., passwords: [clave], sessionKey: { data, algorithm: 'aes256' } })`. La contraseña solo cifra esa clave de sesión. Esto permite:

- **(a)** que el enlace público lleve la clave de sesión, no la contraseña (que puede estar reutilizada en otro lado);
- **(b)** que reescribir el informe reutilice la misma clave de sesión, así el `#k=` del enlace sigue sirviendo.

**Archivos cifrados con `gpg -c` en local.** gpg no usa una clave de sesión aleatoria: la deriva directamente de la contraseña y de un salt nuevo cada vez. OpenPGP.js los abre igual: `decryptSessionKeys({ passwords })` devuelve esa clave derivada. Pero si el admin vuelve a cifrar en local y reescribe, la clave de sesión cambia y **el enlace público hay que regenerarlo**. Si reescribe desde el portal (B7), se conserva.

**Codificación de `#k=`:** `#k=<id de algoritmo>.<clave en base64url>`. Para AES-256 queda, por ejemplo, `#k=9.Hi3JykWQCXzS-DPUoT4LL4U5PrAScsLg9eWCPVSj7Yo`. El id del algoritmo va porque un `.gpg` cifrado en local con otra opción podría no usar AES-256. Es el mismo dato que muestra `gpg --show-session-key` (`9:1E2DC9…`), solo que en base64url.

**Verificado (gpg 2.4.4 ↔ OpenPGP.js 6.3.2):**

- gpg descifra con la contraseña lo que cifra OpenPGP.js.
- gpg descifra con `--override-session-key` el archivo original y el reescrito con la misma clave de sesión.
- OpenPGP.js descifra un `gpg -c --cipher-algo AES256`, tanto con la contraseña como con la clave de sesión.
- Una clave incorrecta da `Session key decryption failed`.

**Datos en Firestore.** El doc de `reports` suma:

- `encrypted: true`
- `encFormat: 'openpgp'`
- `name` sin la extensión `.gpg` (`informe.html`), para elegir el visor.

El `storagePath` termina en `.gpg`. **Ningún dato secreto va a Firestore.**

**Módulo.** La lógica va en un archivo nuevo, `cifrado.js` (módulo ES servido por hosting), con funciones finas sobre OpenPGP.js:

- `cifrar(bytes, {password, filename, sessionKey?}) → {bytes, sessionKey}`
- `esMensajeSimetrico(bytes)`: true si es OpenPGP binario con al menos un SKESK; false si es de clave pública o no es OpenPGP
- `sessionKeyDesdePassword(bytes, password)`
- `descifrar(bytes, sessionKey) → {bytes, filename}`
- `sessionKeyAFragmento` / `fragmentoASessionKey`

`index.html` solo lo importa. Así se puede testear en Node 22+.

### Requisitos P0

**B1. Subida con cifrado en el portal.** En el área de subida se agregan:

- Un check "🔒 Encriptar con clave".
- Al tildarlo, campos de clave y confirmación, con un botón "Generar clave" que propone una frase aleatoria de 5 palabras o 20 caracteres y la muestra para copiar.

Con varios archivos en la misma subida, todos usan la misma clave, cada uno con su propia clave de sesión.

- [ ] La clave tiene mínimo 10 caracteres y la confirmación tiene que coincidir; si no, no se habilita "Subir".
- [ ] El objeto en Storage queda en `reports/{ts}_{nombre}.gpg` con `contentType: application/pgp-encrypted` y `customMetadata.reportId` (A1).
- [ ] `gpg -d` sobre el objeto bajado, con la clave, devuelve el archivo original byte a byte.
- [ ] El doc del informe tiene `encrypted: true` y no contiene ni la clave ni la clave de sesión.
- [ ] Al terminar se muestra un aviso: "Guardá la clave: no se puede recuperar. Enviala al cliente por un canal distinto al correo de aviso."
- [ ] La tabla de informes muestra 🔒 junto al nombre de los encriptados.

**B2. Subida de un `.gpg` cifrado en local.** Si el archivo subido termina en `.gpg` o `.pgp`, se lee con `esMensajeSimetrico`.

- Si es simétrico, se sube tal cual, se marca `encrypted: true` y el `name` queda sin la extensión. No se pide clave.
- Si es OpenPGP cifrado con clave pública, se rechaza: "Este archivo está cifrado para una clave GPG, no con contraseña. Ciframelo con `gpg -c`."
- Si no es OpenPGP, se sube como un archivo común y se avisa.

Comando recomendado (va en el manual):

```bash
gpg -c --cipher-algo AES256 --s2k-digest-algo SHA256 --s2k-count 65011712 informe.html
```

- [ ] Un `informe.html.gpg` generado con ese comando se abre en el portal con la clave y se muestra como HTML.
- [ ] Un `.gpg` cifrado con clave pública se rechaza con el mensaje de arriba y no se sube nada.

**B3. Apertura con clave.** `openUserReport()` y `previewReport()`, si `encrypted`:

1. Bajan los bytes con `fetchBytes`.
2. Abren un modal de clave: campo tipo password, "Abrir" y "Cancelar".
3. Obtienen la clave de sesión con `sessionKeyDesdePassword`.
4. Descifran con `descifrar` y pasan el resultado al visor (B4).

- [ ] Con la clave incorrecta se ve "Clave incorrecta" y se puede reintentar sin volver a bajar el archivo.
- [ ] Mientras se deriva la clave (puede tardar 1 o 2 s en equipos lentos, por el S2K), se muestra "Descifrando…".
- [ ] La clave de sesión queda en un `Map` en memoria (`reportId → sessionKey`) mientras la pestaña siga abierta. Al reabrir el mismo informe no se vuelve a pedir la clave. Al cerrar sesión, el `Map` se vacía.
- [ ] La clave y la clave de sesión nunca se escriben en Firestore, `localStorage`, `sessionStorage`, consola, `sessions` ni `dashboardEvents`.

**B4. Visor con contenido en memoria.** `openViewer` pasa a aceptar como fuente una URL (como hoy) o `{ bytes, name }`. El tipo se decide con `fileKind(name)`, usando el nombre sin `.gpg`.

| Tipo | Fuente en memoria |
| --- | --- |
| PDF / DOCX | `renderPdf` y `renderDocx` reciben `data` directo en vez de llamar a `fetchBytes(url)` |
| PPTX | `pptxFileUrl` con una `blob:` URL creada con `URL.createObjectURL` |
| HTML | iframe con `src` = `blob:` URL del HTML descifrado (`type: text/html`), con **`sandbox="allow-scripts allow-forms allow-popups"` (sin `allow-same-origin`)** |
| Sin visor | botón de descarga del blob descifrado con su nombre original |

**El sandbox es obligatorio.** Una `blob:` URL creada por el portal hereda el origen del portal. Con `allow-same-origin`, el JS del informe podría leer la sesión de Firebase del usuario (IndexedDB) y operar con sus permisos.

Todas las `blob:` URLs se revocan en `closeViewer()`.

- [ ] `setupPortalParams` y `setupDashboardAnalytics` siguen funcionando, porque `postMessage` funciona con origen opaco. Se verifica con `examples/dashboard-parametros.html` encriptado: recibe los parámetros y registra eventos.
- [ ] Desde la consola del iframe, `parent.document` y la base IndexedDB de Firebase del portal no son accesibles.
- [ ] Marca de agua, bloqueo de impresión y bloqueo de copia se comportan igual que en un informe sin encriptar.
- [ ] Los informes **no** encriptados siguen usando la URL de Storage y el sandbox actual: no se tocan.

**B5. Descargas.** Para un informe encriptado se ofrecen dos opciones, al admin y también al cliente:

- **"Descargar"**: el contenido descifrado con su nombre original (`informe.html`).
- **"Descargar cifrado (.gpg)"**: el objeto tal como está en Storage (`informe.html.gpg`), que se abre con `gpg -d` y la clave.

| Quién | `noDownload` | Qué ve |
| --- | --- | --- |
| Admin | — | Las dos opciones, siempre |
| Cliente | desactivado | Las dos opciones |
| Cliente | activado | Ninguna |

Ocultar los botones es disuasivo, igual que hoy: un cliente con acceso puede bajar el `.gpg` desde las herramientas de desarrollo (F12), porque las reglas le permiten leer el objeto. Eso no expone nada sin la clave; la barrera real es la clave.

- [ ] Las dos descargas respetan la tabla.
- [ ] El `.gpg` descargado por un cliente se abre con `gpg -d` y la clave.

**B6. Enlace público con la clave de sesión en el fragmento.**

- **Generar:** `generatePublicLink()` sobre un informe encriptado pide la clave, obtiene la clave de sesión y arma `${origin}/?p=${token}#k=${fragmento}`. El doc en `publicLinks` suma `encrypted: true` y no guarda ni la clave de sesión ni la clave.
- **Reabrir el modal más tarde:** como el fragmento no está guardado en ningún lado, el modal muestra "Este enlace incluye la clave del informe. Para verlo completo, ingresá la clave" y un campo de clave. Con la clave correcta, reconstruye la URL completa, que es la misma de antes porque la clave de sesión no cambió. Las estadísticas de accesos se muestran igual.
- **Abrir como visitante:** el modo público lee `k` de `location.hash`, baja los bytes desde `data.url`, descifra con `descifrar` y abre el visor como en B4. Si no hay `#k` o la clave de sesión no sirve, ofrece ingresar la clave del informe.
- **Ayuda en el modal:** el modal del admin muestra, plegado, el comando para descifrar en local con la clave de sesión: `gpg --override-session-key '9:<HEX>' -d archivo.gpg`.
- [ ] El enlace con `#k` abre el informe sin pedir nada, en una ventana privada sin login.
- [ ] El mismo enlace sin `#k` pide la clave; con la clave correcta abre.
- [ ] En las peticiones de red (pestaña Network) no aparece el valor de `k` en ninguna URL, cuerpo ni `Referer`.
- [ ] El contador `hitCount` sigue sumando como hoy.

**B7. Reescribir un informe encriptado.**

- **Desde el portal:** el flujo pide la clave del informe, obtiene la clave de sesión y cifra el archivo nuevo **con la misma clave de sesión y la misma contraseña** (`openpgp.encrypt({ passwords, sessionKey })`). Después refresca `publicLinks.url` como hoy.
- **Con un `.gpg` hecho en local:** se acepta (con la validación de B2), pero antes se avisa: "Al reescribir con un archivo cifrado en tu máquina, el enlace público cambia: vas a tener que volver a copiarlo." Si el informe tiene enlace público, después de subir se pide la clave para regenerar el `#k`.
- [ ] Después de reescribir desde el portal, el enlace público con el mismo `#k=` muestra el contenido nuevo.
- [ ] Con una clave incorrecta, la reescritura se cancela sin tocar el archivo.

**B8. `update_report.py` y encriptados.** Si el informe tiene `encrypted: true`:

- Con un `--file` que no es `.gpg`: aborta con un mensaje claro ("informe encriptado: pasá un .gpg cifrado con gpg -c, o reescribilo desde el portal"). Nunca sobrescribe con texto plano.
- Con un `--file x.gpg`: verifica que empiece con un paquete SKESK, lo sube con la etiqueta de A3 y avisa que el enlace público, si lo hay, hay que regenerarlo desde el portal.

**B9. Tests.** En `tests/cifrado/` (Node 22+, `node --test`):

- Ida y vuelta con la contraseña.
- Ida y vuelta con la clave de sesión.
- Contraseña incorrecta → error.
- Un byte alterado → error de integridad.
- Reescritura con la misma clave de sesión → abre con el mismo fragmento.
- `fragmentoASessionKey(sessionKeyAFragmento(x))` devuelve x.
- `esMensajeSimetrico` rechaza un mensaje cifrado con clave pública y un archivo que no es OpenPGP.
- **Interoperabilidad**, si `gpg` está instalado (se saltea si no):
  - gpg descifra lo que cifra la librería, con la contraseña y con `--override-session-key`.
  - La librería descifra un `gpg -c --cipher-algo AES256`.
  - `gpg --list-packets` muestra `symkey enc packet: version 4`, `cipher 9`, `aead 0` y `count 65011712`.

**B10. Manual.** Agregar a `docs/manual-usuario.html` una sección para el admin y otra para el cliente, con:

- Cómo subir encriptado, desde el portal o con `gpg -c`.
- Cómo enviar la clave: nunca en el mismo correo del aviso de acceso.
- Cómo descifrar con `gpg -d`.
- Dónde conseguir gpg: Gpg4win en Windows, GPG Suite o `brew install gnupg` en Mac, ya instalado en Linux.
- Qué hacer si se pierde la clave.
- Cómo funciona el enlace público con clave.

**B11. Límites.**

- El check de encriptar se deshabilita para video (`fileKind === 'video'`) con un tooltip que lo explica. El motivo: el portal descifra el archivo entero en memoria.
- Tope de 100 MB por archivo encriptado, tanto para cifrar en el portal como para subir un `.gpg`; por encima, se avisa y no se encripta.

### P1

- **B12. Cambiar la clave** de un informe: se cifra de nuevo con la misma clave de sesión y la contraseña nueva. El enlace público no cambia.
- **B13. Encriptar o desencriptar un informe existente** desde su menú, sin tener que volver a subirlo desde la PC.
- **B14. Aceptar `.asc`** (`gpg -c -a`, en texto ASCII) leyéndolo con `readMessage({ armoredMessage })`.
- **B15. "Recordar la clave mientras dure la sesión"** en `sessionStorage`, opcional y destildado por defecto.
- **B16. Quitar `#k` de la barra de direcciones** con `history.replaceState` después de leerlo, para que no quede visible al compartir pantalla. Contra: si se recarga la página, se pierde la clave.

---

## Diseño técnico (resumen por archivo)

| Archivo / función | Cambio | Req. |
| --- | --- | --- |
| `storage.rules` | Lectura de `reports/` cruzando `metadata.reportId` con `userAccess` | A4 |
| `firestore.rules` | `reports`: `get` por asignación y `list` solo admin; `publicLinks`: `get` abierto y `list` solo admin | A5, A6 |
| `firebase.json` | Emulador de Storage (9199) | A7 |
| `uploadFiles()` | Id del doc generado antes de subir, `customMetadata.reportId`, cifrado opcional, detección de `.gpg` | A1, B1, B2 |
| Reescritura de informe | Conservar `customMetadata.reportId`; si es encriptado, reutilizar la clave de sesión o avisar si viene un `.gpg` local | A1, B7 |
| `loadUserReports()` | `try/catch` por cada `get` | A5 |
| `openUserReport()`, `previewReport()`, `downloadReport()` | Rama `encrypted` con modal de clave, caché de la clave de sesión en memoria y las dos descargas | B3, B5 |
| `openViewer()`, `renderPdf/Docx/Pptx`, `closeViewer()` | Fuente `{bytes, name}`, sandbox sin `allow-same-origin` para el HTML descifrado, revocar `blob:` | B4 |
| `generatePublicLink()`, `publicLinkModalBody()`, modo público (`?p=`) | `#k=`, reconstrucción del enlace con la clave, descifrado anónimo | B6 |
| `vendor/openpgp-6.3.2.min.mjs` (nuevo) | OpenPGP.js incluido en el repo | B |
| `cifrado.js` (nuevo) | Funciones finas sobre OpenPGP.js con la configuración compatible con gpg | B |
| `scripts/etiquetar_informes.py` (nuevo) | Migración de la metadata | A2 |
| `scripts/update_report.py` | Conservar la etiqueta; con encriptados, solo acepta `.gpg` | A3, B8 |
| `tests/rules/`, `tests/cifrado/` (nuevos) | Tests, incluida la interoperabilidad con gpg | A7, B9 |
| `docs/DESPLIEGUE_cierre_acceso_y_encriptacion.md` (nuevo), `docs/manual-usuario.html` | Despliegue y manual | A, B10 |

No hacen falta Cloud Functions, colecciones ni servicios nuevos.

## Costos

- **Cifrado (B): US$ 0 recurrente.** OpenPGP.js y gpg son gratuitos y corren en el navegador y en la máquina del admin. No se suma KMS ni backend. Cada `.gpg` pesa unos 60–100 bytes más que el original. La librería (unos 130 KB comprimida) sale desde Hosting; con el volumen del portal, ese tráfico es despreciable dentro de los 10 GB/mes gratis de Hosting.
- **Reglas cruzadas (A):** cada `getDownloadURL()` o `get` de un informe que hace un cliente suma 1 o 2 lecturas de Firestore (`users/{uid}` para `isAdmin` y `userAccess/{uid}`). El plan Blaze trae 50.000 lecturas gratis por día; por encima se paga del orden de US$ 0,03–0,06 cada 100.000 lecturas, según la región. Con el volumen del portal (cientos o pocos miles de aperturas por mes), queda en el tramo gratuito o en centavos por mes.
- **Tests con emulador:** sin costo, corren en local.

## Métricas de éxito

- 0 lecturas de informes no asignados posibles desde una cuenta cliente (lo verifican los tests de reglas y la prueba manual del paso 5 del despliegue).
- 0 tickets de "no puedo abrir mi informe" en la semana posterior al despliegue de reglas.
- 100% de los informes encriptados abren con su clave y con su enlace público después de una reescritura desde el portal.
- 100% de los `.gpg` bajados del portal abren con `gpg -d` y su clave.

## Preguntas abiertas

1. **Política de clave:** ¿alcanza con un mínimo de 10 caracteres, o se exige el generador para los informes encriptados?
2. **Video encriptado:** ¿hace falta? Si sí, implica descifrado por partes (*streaming*, que OpenPGP.js soporta) y reproducción con MediaSource; es otra spec.
3. **Nombres de carpetas visibles para todos los clientes:** ¿hay carpetas con nombre de cliente que no deberían ver otros? Si sí, conviene una spec aparte para filtrar `folders` (la complicación es que el cliente necesita leer las carpetas antecesoras de sus informes).
4. **Nombre visible:** el nombre original va cifrado dentro del `.gpg`, pero sigue visible en Firestore (`name`) y en el `storagePath`. Si el nombre del archivo en sí es sensible, habría que guardar en Storage un nombre genérico y mostrar en el portal un nombre que no revele nada.
