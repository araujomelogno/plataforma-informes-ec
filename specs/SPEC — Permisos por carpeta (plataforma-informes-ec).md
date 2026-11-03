# SPEC — Permisos por carpeta

Nov 3, 2026 · @Equipos

## Resumen

Hoy a un usuario solo se le pueden asignar informes de a uno. Este cambio permite **asignarle carpetas**. Con permiso sobre una carpeta, el usuario ve todos los informes que hay en ella **y en todas sus subcarpetas**, incluidos los que se suban después. Cuando aparece un informe nuevo en una carpeta asignada, el usuario recibe el mismo aviso "Nuevo informe" por correo que hoy.

Como los nombres de carpetas pueden revelar a otros clientes, el cliente **navega desde sus carpetas asignadas**, sin ver las de arriba, y **deja de poder leer la colección `folders`**: recibe solo los nombres de las carpetas que le corresponden.

Repositorio `araujomelogno/plataforma-informes-ec`, revisado sobre `cc99ef5`. Ese commit ya incluye el cierre de acceso por reglas y los informes encriptados (`8156df7`, spec "Cierre de acceso a archivos e informes encriptados"). Esta spec **modifica esas reglas**.

### Cómo funciona hoy

| Pieza | Comportamiento actual |
| --- | --- |
| `userAccess/{uid}` | `reportIds: []` y `options: {reportId: {watermark, noPrint, noDownload, noCopy, expiresAt, notificar, grantedAt, grantedBy, grantedByEmail}}`. Lo escribe solo el admin |
| `storage.rules` → `reports/` | Un cliente lee si `metadata.reportId in userAccess/{uid}.reportIds`. Para el admin, `isAdminSt()` lee `users/{uid}`. **Ya usa los 2 documentos de Firestore que permiten las reglas de Storage** |
| `firestore.rules` → `reports/{id}` | `get` si `reportId in userAccess.reportIds`; `list` solo el admin |
| `folders/{id}` | `{name, parentId, clientVisible}`; árbol con cualquier profundidad. Los informes apuntan a su carpeta con `reports/{id}.folderId`. **Regla: `read: if isAuth()`**: cualquier cliente puede listar los nombres de **todas** las carpetas desde las herramientas de desarrollo del navegador |
| Navegación del cliente | Muestra el camino desde la raíz hasta cada informe, salteando las carpetas ocultas. Ve los nombres de las carpetas antecesoras de sus informes |
| `loadUserReports()` | Lee `userAccess.reportIds`, trae cada informe con `get` y arma la navegación por carpetas visibles |
| Avisos | `notificarAcceso` (trigger de `userAccess`) encola un aviso por cada id nuevo en `reportIds`; `avisarAsignacion` (callable) lo manda en el momento. Mismo id de aviso (`{uid}-{rid}-{grantedAt}`): no se duplica |

### Por qué no alcanza con cambiar las reglas

La forma intuitiva sería que la regla de Storage suba por el árbol de carpetas del informe y se fije si alguna está asignada. No se puede:

- Las reglas de Storage **no pueden leer más de 2 documentos de Firestore por evaluación** ([documentación](https://firebase.google.com/docs/storage/security/rules-conditions)), y ya se usan los 2.
- Las reglas no tienen bucles para recorrer el árbol.
- Un cliente tampoco podría *listar* los informes de una carpeta, porque `reports` no admite `list` para clientes.

**Solución:** el **acceso efectivo** de cada usuario (sus informes directos más los de sus carpetas, ya expandidos) se calcula en una Cloud Function y se guarda en un documento nuevo, `accesoEfectivo/{uid}`. Las reglas y el portal leen ese documento en lugar de `userAccess`. La regla de Storage sigue leyendo 2 documentos: `users` y `accesoEfectivo`.

## Objetivos

1. Un admin asigna una carpeta a un usuario en 2 clics, desde la pestaña Permisos o desde el árbol de carpetas.
2. El usuario ve todos los informes de esa carpeta y de sus subcarpetas, sin que el admin los asigne uno por uno.
3. Un informe subido o movido a una carpeta asignada aparece en el portal del usuario sin intervención, y le llega el aviso por correo.
4. Las reglas siguen garantizando que un cliente no puede leer, ni en Firestore ni en Storage, nada fuera de su acceso efectivo.
5. Un cliente no puede conocer, ni en pantalla ni desde las herramientas de desarrollo, el nombre de una carpeta fuera de las que le corresponden.
6. Los usuarios actuales no pierden acceso a ningún informe durante la migración.

## No-objetivos

- **Permisos negativos** (asignar una carpeta salvo un informe o una subcarpeta). Si hace falta excluir algo, se reorganizan las carpetas.
- **Asignar la raíz completa.** Se asignan carpetas concretas.
- **Cambiar los enlaces públicos o el cifrado.** Funcionan igual: un informe encriptado en una carpeta asignada se ve con su clave, como hoy.
- **Grupos de usuarios** (asignar una carpeta a "todos los de Cliente X"). Es la siguiente evolución natural, pero es otra spec.

## Historias de usuario

- Como admin, quiero asignarle a un cliente la carpeta de su estudio, para no tener que habilitar cada informe que subo.
- Como admin, quiero que al subir un informe a esa carpeta el cliente lo vea y reciba el aviso, sin acordarme de asignarlo.
- Como admin, quiero ver de un vistazo si un usuario tiene un informe por asignación directa o por una carpeta, para entender por qué lo ve.
- Como admin, quiero poner protecciones y una caducidad a una carpeta asignada, y que valgan para todos sus informes.
- Como cliente, quiero ver los informes nuevos de mi estudio apenas se publican, en la misma navegación por carpetas de siempre.

## Diseño

### Datos

**`userAccess/{uid}`** (lo escribe el admin, como hoy). Suma dos campos:

```
folderIds:     ["fA", "fB"]
folderOptions: { "fA": { watermark, noPrint, noDownload, noCopy, expiresAt,
                         notificar, grantedAt, grantedBy, grantedByEmail } }
```

Los campos de `folderOptions` son los mismos que los de `options` por informe; así se reutilizan los mismos componentes de la interfaz.

**`accesoEfectivo/{uid}`** (nuevo; **solo lo escribe la Cloud Function**):

```
reportIds:  ["r1", "r2", "r7", …]               // directos ∪ informes de las carpetas asignadas y sus subcarpetas
via:        { "r7": "fA", "r1": null }          // null = asignación directa; si no, la carpeta asignada que lo da
opciones:   { "r7": {…}, "r1": {…} }            // opciones que se aplican a cada informe (ver precedencia)
carpetas:   { "fA": {name, parentId, clientVisible}, … }
            // las carpetas que el cliente puede ver (ver "Carpetas visibles"); parentId == null si es
            // una raíz para ESTE usuario, aunque en el árbol real tenga padre
raices:     ["fA", "fX"]                        // raíces de su navegación, en orden alfabético
calculadoEn: <timestamp>
```

**Precedencia de opciones.** Para cada informe, se aplica la primera que exista:

1. La asignación directa (`options[rid]`).
2. La carpeta asignada **más cercana** al informe, subiendo por el árbol.

Así, un informe con asignación directa conserva sus protecciones y su caducidad propias aunque también llegue por una carpeta.

**Carpetas visibles y raíces del cliente.** El cliente no ve el árbol desde la raíz, sino un bosque recortado:

- **Carpetas asignadas:** cada carpeta asignada que no esté dentro de otra carpeta asignada es una **raíz**. Debajo se ven sus subcarpetas, con la regla de carpetas ocultas de siempre (`clientVisible === false` se saltea y su contenido sube a la carpeta visible más cercana, *sin pasar por encima de la raíz*).
- **Informes directos fuera de las carpetas asignadas:** la carpeta visible más cercana del informe pasa a ser una raíz, **sin sus antecesoras**. Si el informe está en la raíz o solo tiene carpetas ocultas encima, se muestra en el inicio del cliente.
- **Una carpeta asignada oculta** (`clientVisible: false`) no se muestra como raíz: su contenido aparece en el inicio del cliente.
- **Ninguna carpeta antecesora de una raíz** se incluye en `carpetas`, ni siquiera su nombre.

Ejemplo, con el árbol `Clientes / Cliente X / Estudio 1 / Ola 2` y la carpeta `Estudio 1` asignada: el cliente ve en su inicio `📁 Estudio 1`, y dentro `📁 Ola 2`. Nunca recibe los nombres `Clientes` ni `Cliente X`.

### Cálculo (`functions/portal/permisos.py`, nuevo)

`calcular_acceso(user_access, folders, reports) → {reportIds, via, opciones}` es una función **pura**, sin Firestore, para testearla fácil:

1. Arma el índice `hijos[parentId]` desde `folders`.
2. Para cada carpeta asignada, recorre su subárbol en anchura (BFS) con un conjunto de visitados, para protegerse de ciclos.
3. Para cada informe de ese subárbol, lo suma a `reportIds` y calcula `via` y `opciones` con la precedencia de arriba.
4. Suma los `reportIds` directos que existen.
5. Arma `carpetas` y `raices` según "Carpetas visibles y raíces del cliente". Para cada raíz, `parentId` se escribe como `null`.
6. Ignora las carpetas y los informes borrados. Un `folderId` que apunta a una carpeta inexistente cuenta como raíz, como ya hace el portal.

`recalcular(db, uid)` lee `userAccess/{uid}`, `folders` (todas, una sola vez por invocación) y los informes de los subárboles asignados (`where('folderId', 'in', [...])` en tandas de 30). Llama a `calcular_acceso` y **escribe `accesoEfectivo/{uid}` solo si cambió** `reportIds`, `via`, `opciones`, `carpetas` o `raices`. Así no se disparan avisos ni escrituras de más.

### Cuándo se recalcula

| Evento | Función | A quién se recalcula |
| --- | --- | --- |
| `userAccess/{uid}` escrito | `notificarAcceso` (ya existe; pasa a **solo** recalcular) | A ese `uid` |
| `reports/{id}` creado, borrado o con `folderId` cambiado | `onInformeCambio` (nueva) | A los usuarios cuyos `folderIds` contienen alguna carpeta del camino del informe, **antes y después** del cambio (`array-contains-any` en tandas de 30) |
| `folders/{id}` creada, con `parentId`, `name` o `clientVisible` cambiado, o borrada | `onCarpetaCambio` (nueva) | A los usuarios cuyos `folderIds` contienen la carpeta o alguna de sus antecesoras, antes y después. Si solo cambió `name` o `clientVisible`, se suman los usuarios que la tienen en `carpetas` por un informe directo (`accesoEfectivo` donde `carpetas.{id}` existe) |
| Todos los días, 03:17 (Montevideo) | `reconciliarAccesos` (programada, nueva) | A todos: red de seguridad ante un trigger perdido o una carrera entre triggers |
| Manual | `recalcularAccesos` (callable, solo admin) | A todos o a un `uid`. Se usa en la migración y como botón de reparación |

Los triggers que no cambian nada relevante **salen sin leer nada más**: comparan `before` y `after` de `folderId` en informes y de `parentId`, `name` y `clientVisible` en carpetas. Renombrar un informe no recalcula nada. Renombrar una carpeta sí, porque el nombre está copiado en `accesoEfectivo.carpetas`.

### Avisos por correo

El aviso pasa a depender del **acceso efectivo**, no de `userAccess`:

- **Respaldo:** la lógica de `registrar_cambio` se mueve a un trigger nuevo sobre **`accesoEfectivo/{uid}`** (`avisarAccesoNuevo`). Por cada id nuevo en `reportIds` encola el aviso, respetando `opciones[rid].notificar` y la ventana de agrupado (`config/correos.ventanaAgrupadoMin`).
  - Si se suben 10 informes a una carpeta asignada, el usuario recibe **un solo** correo con la lista, como hoy cuando el admin habilita varios.
- **En el momento** (`avisarAsignacion`): antes de encolar, llama a `recalcular(db, uid)` de forma síncrona y toma los vigentes de `accesoEfectivo`, no de `userAccess.reportIds`. Acepta un `folderId` en lugar de `reportIds`: avisa todos los informes que esa carpeta le da al usuario.
- **Id del aviso:**
  - Directo: `{uid}-{rid}-{grantedAt del informe}`, sin cambios.
  - Por carpeta: `{uid}-{rid}-{grantedAt de la carpeta}`. El panel y el trigger coinciden, así que no se duplica. Si un informe sale de la carpeta y vuelve a entrar mientras el aviso sigue en la cola (`DIAS_DE_REGISTRO`), no se avisa de nuevo.
- En `_valores()`, la caducidad (`vence`) sale de `accesoEfectivo.opciones`, y **la ruta de carpeta del correo** (`_ruta_carpeta`) se arma con `accesoEfectivo.carpetas`, desde la raíz del usuario. Hoy arma el camino completo desde la raíz del árbol, y el correo revelaría los mismos nombres que se ocultan en pantalla.

### Reglas

**Firestore:**

```
match /accesoEfectivo/{uid} {
  allow read:  if isAuth() && (request.auth.uid == uid || isAdmin());
  allow write: if false;                        // solo la Cloud Function (Admin SDK)
}

match /folders/{folderId} {
  allow read:  if isAdmin();                   // el cliente recibe sus carpetas en accesoEfectivo.carpetas
  allow write: if isAdmin();
}

match /reports/{reportId} {
  allow get: if isAdmin() || (isAuth() && (
    reportId in get(/databases/$(database)/documents/accesoEfectivo/$(request.auth.uid)).data.get('reportIds', []) ||
    reportId in get(/databases/$(database)/documents/userAccess/$(request.auth.uid)).data.get('reportIds', [])
  ));
  allow list:  if isAdmin();
  allow write: if isAdmin();
}
```

En Firestore se mantiene también `userAccess.reportIds`, porque el límite es 10 documentos. Así una asignación directa recién hecha muestra el informe aunque el recálculo todavía no haya terminado.

**Storage** (sigue leyendo 2 documentos: `users` en `isAdminSt()` y `accesoEfectivo`):

```
allow read: if request.auth != null && (
  isAdminSt() ||
  (resource.metadata.reportId is string &&
   firestore.exists(/databases/(default)/documents/accesoEfectivo/$(request.auth.uid)) &&
   resource.metadata.reportId in
     firestore.get(/databases/(default)/documents/accesoEfectivo/$(request.auth.uid)).data.get('reportIds', []))
);
```

**Consecuencia:** el archivo de un informe recién asignado se puede abrir recién cuando el recálculo termina, que suele tardar 1–3 s. El portal lo maneja (ver C6).

## Requisitos P0

**C1. Asignar carpetas en la pestaña Permisos.** Arriba de la grilla de informes, una sección nueva "📁 Carpetas" con el árbol de carpetas (indentado, con la misma visibilidad que el árbol del admin):

- Un check por carpeta.
- Al tildarla, las mismas protecciones, caducidad y casilla "Avisar al usuario por correo" que tiene cada informe. El texto de la casilla cambia a: "Avisar por correo, también cuando se suban informes nuevos a esta carpeta".
- Tildar una carpeta escribe en `userAccess/{uid}` `folderIds` (con `arrayUnion`) y `folderOptions[fid]` (con `grantedAt`, `grantedBy` y `grantedByEmail`, igual que `grantReportToUser`).

Criterios:

- [ ] Asignar "Cliente X" a un usuario hace que vea los informes de "Cliente X" y de "Cliente X / Estudio 1 / Ola 2".
- [ ] Quitar la carpeta le quita esos informes, salvo los que tiene por asignación directa o por otra carpeta.
- [ ] Una subcarpeta de una carpeta asignada se muestra tildada en gris con "incluida por *Cliente X*". No se puede destildar sola (ver no-objetivos).

**C2. Indicar en la grilla de informes cuándo el acceso viene de una carpeta.** En la grilla de Permisos, un informe que el usuario ve por una carpeta y no por asignación directa se muestra con su check en gris y la etiqueta "📁 vía *Cliente X*" (sale de `accesoEfectivo.via`).

- Tildarlo crea además la asignación directa; sirve para darle protecciones o caducidad propias.
- Destildar la asignación directa no le quita el acceso si la carpeta se lo sigue dando, y la grilla lo dice.

Criterios:

- [ ] El admin distingue en la grilla, sin abrir nada, qué informes son directos y cuáles vienen de una carpeta.

**C3. Asignar usuarios desde el árbol de carpetas.** En `renderFoldersTree()`, cada carpeta suma un botón "👥 Usuarios" que abre un modal como el de "Usuarios" de cada informe (`openReportUsersModal`):

- Lista de usuarios con un check, con la casilla de aviso y las protecciones de C1.
- Los usuarios que ya ven la carpeta porque tienen asignada una carpeta antecesora aparecen tildados en gris con "por *Carpeta padre*".

Criterios:

- [ ] Asignar desde este modal o desde la pestaña Permisos escribe exactamente lo mismo.

**C4. Recálculo del acceso efectivo.** `permisos.py`, con los triggers, la función programada y la callable de la tabla "Cuándo se recalcula".

- [ ] Subir un informe a una carpeta asignada lo agrega a `accesoEfectivo/{uid}.reportIds` en menos de 10 s.
- [ ] Mover un informe fuera de la carpeta asignada se lo quita al usuario (si no lo tiene por otra vía).
- [ ] Mover una carpeta (con todo su subárbol) bajo una carpeta asignada se lo da al usuario.
- [ ] Renombrar un informe no escribe `accesoEfectivo`; renombrar una carpeta solo lo reescribe a los usuarios que la ven (lo cubre un test).
- [ ] Un ciclo en `parentId` (datos corruptos) no cuelga la función.

**C5. El portal del usuario lee el acceso efectivo.** `loadUserReports()` lee `accesoEfectivo/{uid}`: `reportIds` para la lista, `opciones` para `myAccessOptions` (que alimenta las protecciones y `accessExpired`), y `carpetas` y `raices` para la navegación (ver C13). Para un cliente **ya no llama a `loadFolders()`**.

- Si el documento todavía no existe (usuario nuevo con el recálculo en curso), muestra "Preparando tus informes…" y espera al `onSnapshot`. No vuelve a la lectura de `folders`, porque la regla ya no lo permite.
- Se suscribe con `onSnapshot` a `accesoEfectivo/{uid}` mientras la vista está abierta, así un informe nuevo aparece sin recargar.

Criterios:

- [ ] Un usuario con la carpeta asignada ve aparecer un informe recién subido sin recargar la página.
- [ ] Las protecciones y la caducidad de la carpeta se aplican a sus informes; las de una asignación directa tienen prioridad.

**C6. Tolerar la demora del recálculo.** Si `getDownloadURL()` falla con `storage/unauthorized` para un informe que **sí** está en `userAccess.reportIds` (es decir, el recálculo está en curso), el portal reintenta 3 veces, con 1, 2 y 4 s de espera, mostrando "Preparando el acceso…". Recién después muestra el error.

**C7. Contadores, matriz y modal de usuarios del informe.**

- `loadReportAccessCounts()` cuenta desde `accesoEfectivo`, que el admin puede listar.
- En la matriz, una celda por carpeta se muestra como "📁", distinta del "✓" directo, con un tooltip que nombra la carpeta.
- En el modal "Usuarios" de un informe, los usuarios que lo ven por carpeta aparecen tildados en gris con "vía *carpeta*" y un enlace para abrir esa carpeta en el árbol.

Criterios:

- [ ] El contador "usuarios con acceso" de un informe incluye a quienes lo ven por carpeta.

**C8. Avisos.** Lo descrito en "Avisos por correo".

- [ ] Asignar una carpeta con 5 informes y la casilla tildada manda **un** correo con los 5.
- [ ] Subir 3 informes a esa carpeta dentro de la ventana de agrupado manda **un** correo con los 3.
- [ ] Con la casilla destildada en la carpeta, no sale ningún correo, ni al asignar ni al subir informes nuevos.
- [ ] Un usuario que ya tenía el informe por asignación directa no recibe un segundo aviso cuando además lo gana por carpeta, porque no es un id nuevo en `accesoEfectivo.reportIds`.

**C9. Borrar una carpeta asignada.** `deleteFolder()` ya mueve el contenido a la carpeta padre. Si la carpeta (o alguna subcarpeta) está asignada a usuarios, la confirmación lo dice: "*N* usuarios tienen permiso sobre esta carpeta y van a perder acceso a su contenido". `onCarpetaCambio` quita el id de `folderIds` y `folderOptions` de esos usuarios.

- [ ] Después de borrar, `userAccess` no conserva referencias a la carpeta borrada.
- [ ] Ningún usuario gana acceso a la carpeta padre por el borrado.

**C10. Migración y orden de despliegue (importante).** Las reglas nuevas leen `accesoEfectivo`; si se despliegan antes de que exista para todos los usuarios, **los clientes pierden acceso**. El orden es:

1. Desplegar las funciones (`firebase deploy --only functions`).
2. Ejecutar `recalcularAccesos` para todos los usuarios, con el botón "🔄 Recalcular accesos" en Configuración o con `scripts/recalcular_accesos.py`.
3. Verificar que todo `userAccess/{uid}` tiene su `accesoEfectivo/{uid}` y que `userAccess.reportIds ⊆ accesoEfectivo.reportIds`. El script lo informa con un "0 diferencias".
4. Desplegar el hosting (C1–C7, C13). Hasta el paso 5, el cliente ya no lee `folders` pero la regla todavía se lo permitiría.
5. Desplegar las reglas (`firebase deploy --only firestore:rules,storage`).
6. Prueba manual: un cliente con una carpeta asignada abre un informe de una subcarpeta y no puede pedir la URL de un informe ajeno desde la consola.

**Rollback:** volver a desplegar las reglas anteriores, que leen `userAccess` (que sigue completo) y vuelven a abrir `folders`. `accesoEfectivo` no molesta. Si además se vuelve atrás el hosting, el cliente vuelve a navegar desde la raíz.

**Comunicación:** los clientes que hoy tienen informes directos van a ver su navegación más corta, sin las carpetas de arriba. Conviene avisarles a los que más usan el portal.

Documentar estos pasos en `docs/DESPLIEGUE_permisos_carpetas.md`.

**C11. Tests.**

- `functions/tests/test_permisos.py`, para `calcular_acceso`. Casos:
  - Carpeta con subcarpetas a 3 niveles.
  - Directo más carpeta, verificando la precedencia de opciones.
  - Dos carpetas asignadas anidadas: gana la más cercana.
  - Carpeta y `folderId` inexistentes.
  - Ciclo en `parentId`.
  - Usuario sin `userAccess`.
  - Raíces y `carpetas`: ninguna antecesora de una raíz aparece; carpetas asignadas anidadas dan una sola raíz; informe directo con su carpeta como raíz; carpeta oculta asignada.
- Tests de los triggers: a quién recalculan y que salen sin hacer nada cuando el cambio no es relevante.
- Tests de avisos: una carpeta asignada genera un solo correo; no se duplica entre el panel y el trigger.
- `tests/rules/`, actualizado:
  - Un cliente lee el archivo si el informe está en `accesoEfectivo` aunque no esté en `userAccess`.
  - Un cliente **no** lo lee en Storage si solo está en `userAccess` (garantiza que la regla de Storage no lee 3 documentos).
  - Nadie que no sea admin puede escribir `accesoEfectivo`.
  - Un cliente no puede leer ni listar `folders`.

**C12. Manual.** Agregar a `docs/manual-usuario.html` una sección para el admin: asignar carpetas, qué heredan las subcarpetas, precedencia de opciones, qué pasa al mover o borrar carpetas, la demora de unos segundos y qué ve el cliente (sus raíces, sin las carpetas de arriba). Actualizar las capturas de la vista del cliente.

**C13. Navegación desde las raíces del cliente.** La vista del cliente (`renderUserLevel()`, `userBreadcrumbHTML()`, `countAccessibleInFolder()`, `nearestVisibleFolderFrom()`) trabaja sobre `accesoEfectivo.carpetas` y `raices`, no sobre el árbol completo:

- El inicio muestra las raíces (`📁 Estudio 1`, `📁 Ola Octubre`) y los informes que no caen en ninguna.
- La miga de pan (*breadcrumb*) es `🏠 Inicio › Estudio 1 › Ola 2` y nunca muestra antecesoras de una raíz.
- `nearestVisibleFolderFrom` se detiene en una raíz del usuario.
- El admin, en "Mis informes", usa la misma lógica con su propio `accesoEfectivo`, así ve lo mismo que vería un cliente con esas asignaciones.

Criterios:

- [ ] Con `Clientes / Cliente X / Estudio 1` y solo `Estudio 1` asignada, el cliente ve `Estudio 1` en su inicio, y en ninguna pantalla aparecen `Clientes` ni `Cliente X`.
- [ ] Un cliente con un informe directo en `Clientes / Cliente Y / Estudio 3` ve `📁 Estudio 3` en su inicio, sin `Cliente Y`.
- [ ] Con dos carpetas asignadas, una dentro de la otra, solo aparece la de más arriba como raíz.
- [ ] Una subcarpeta oculta dentro de una raíz sigue subiendo su contenido a la raíz, nunca más arriba.
- [ ] El correo de aviso muestra la ruta desde la raíz del usuario ("carpeta: Estudio 1 / Ola 2"), no el camino completo.

**C14. Cerrar la lectura de `folders` a los clientes.** La regla de `folders` pasa a `read: if isAdmin()`. Al cliente le llegan solo los nombres de `accesoEfectivo.carpetas`.

- Revisar que ningún flujo de cliente lea `folders`. Hoy lo hace `loadUserReports()` → `loadFolders()`; la subida de documentos del cliente (`clientDocs`) no usa carpetas.
- [ ] `db.collection('folders').get()` y `db.collection('folders').doc(id).get()` desde la consola de un cliente dan `permission-denied`.
- [ ] `accesoEfectivo/{uid}.carpetas` no contiene ninguna carpeta antecesora de una raíz del usuario (lo cubre un test de `calcular_acceso`).
- [ ] El cliente navega igual que antes del cambio, salvo por las antecesoras que ya no ve.

## P1

- **C15. Caducidad aplicada en el backend.** El recálculo excluye los informes con `expiresAt` vencido y la función diaria los saca. Así las reglas aplican la caducidad (hoy solo la controla el portal), sin costo extra.
- **C16. Aviso al mover.** Al mover un informe o una carpeta, la confirmación dice "*N* usuarios van a perder acceso y *M* lo van a ganar".
- **C17. Filas de carpetas en la matriz.** Una fila por carpeta asignada, además de las filas por informe.

## Diseño técnico (resumen por archivo)

| Archivo / función | Cambio | Req. |
| --- | --- | --- |
| `functions/portal/permisos.py` (nuevo) | `calcular_acceso` (pura), `recalcular`, `usuarios_afectados` | C4 |
| `functions/main.py` | `notificarAcceso` → recalcula; nuevas `onInformeCambio`, `onCarpetaCambio`, `avisarAccesoNuevo`, `reconciliarAccesos`, `recalcularAccesos` | C4, C8, C10 |
| `functions/portal/avisos.py` | Diferencia sobre `accesoEfectivo`; `avisar_ahora` recalcula primero y acepta `folderId`; id del aviso con el `grantedAt` de la carpeta; ruta de carpeta desde la raíz del usuario | C8, C13 |
| `firestore.rules` | `accesoEfectivo` (lectura propia o admin, sin escritura); `reports.get` con `accesoEfectivo` o `userAccess`; `folders` solo admin | Reglas, C14 |
| `storage.rules` | `userAccess` → `accesoEfectivo` | Reglas |
| `loadUserPermissions()`, `togglePerm()` | Sección de carpetas; etiqueta "vía carpeta" | C1, C2 |
| `renderFoldersTree()` + modal nuevo | "👥 Usuarios" por carpeta | C3 |
| `loadUserReports()` | Lee `accesoEfectivo` con `onSnapshot`; deja de llamar a `loadFolders()` para clientes | C5, C14 |
| `renderUserLevel()`, `userBreadcrumbHTML()`, `countAccessibleInFolder()`, `nearestVisibleFolderFrom()` | Navegación sobre `carpetas` y `raices` | C13 |
| `openUserReport()` | Reintentos ante `storage/unauthorized` transitorio | C6 |
| `loadReportAccessCounts()`, `renderMatrix()`, `openReportUsersModal()` | Contar y mostrar el acceso por carpeta | C7 |
| `deleteFolder()` | Aviso de usuarios afectados | C9 |
| Configuración + `scripts/recalcular_accesos.py` (nuevo) | Botón y script de recálculo y verificación | C10 |
| `functions/tests/test_permisos.py`, `tests/rules/` | Tests | C11 |
| `docs/DESPLIEGUE_permisos_carpetas.md` (nuevo), `docs/manual-usuario.html` | Despliegue y manual | C10, C12 |

`firestore.indexes.json`: el `array-contains-any` sobre `userAccess.folderIds` y el `in` sobre `reports.folderId` usan los índices de un solo campo que Firestore crea solo, así que no hace falta agregar índices compuestos.

## Costos

Se suman funciones y lecturas de Firestore. Estimación con un volumen holgado para el portal (1.000 informes, 150 carpetas, 200 usuarios, 300 eventos por mes entre subidas, movimientos y asignaciones):

| Concepto | Volumen estimado | Costo |
| --- | --- | --- |
| Invocaciones de funciones (triggers + 30 reconciliaciones al mes) | ~1.000/mes | Gratis (el tramo gratuito es de 2 millones/mes) |
| Lecturas por recálculo de un usuario | ~150 carpetas + los informes de sus carpetas ≈ 200–400 | — |
| Lecturas por eventos | 300 eventos × ~2 usuarios × ~300 ≈ 180.000/mes | Gratis (50.000/día gratis ≈ 1,5 millones/mes) |
| Reconciliación diaria | ~1.350 lecturas/día (carpetas + informes + `userAccess`, leídos una vez) | Gratis |
| Lecturas de reglas | Igual que hoy (`users` + `accesoEfectivo` en vez de `userAccess`) | Sin cambio |
| Lecturas de `folders` por los clientes | Hoy cada apertura de "Mis informes" lee **todas** las carpetas (~150); pasan a 0, porque vienen en `accesoEfectivo` | **Ahorro**: con 2.000 aperturas/mes, ~300.000 lecturas menos |
| Escrituras de `accesoEfectivo` | Solo cuando cambia; ~600/mes | Gratis (20.000/día gratis) |

**Total esperado: US$ 0/mes.** Incluso multiplicando el volumen por 10, quedaría en centavos: por encima del tramo gratuito, del orden de US$ 0,03–0,06 cada 100.000 lecturas, según la región. Un recálculo masivo (`recalcularAccesos` para todos) cuesta unas 1.500 lecturas, también despreciable.

Las funciones nuevas se crean con el `max_instances=10` global que ya tiene el proyecto, que acota el costo ante un pico.

## Métricas de éxito

- 0 informes de una carpeta asignada que el usuario no pueda abrir 10 s después de subirlos (lo cubren los tests y una prueba manual).
- 0 lecturas posibles, desde una cuenta cliente, de informes fuera de su acceso efectivo (tests de reglas).
- 0 avisos duplicados por la misma asignación.
- La reconciliación diaria corrige 0 diferencias en régimen. Si corrige alguna, hay un trigger que falla y conviene investigarlo; queda registrado en el log de la función.

## Preguntas abiertas

1. **Carpetas ocultas (`clientVisible: false`):** ¿se pueden asignar? Esta spec asume que sí: el usuario ve sus informes "subidos" a la carpeta visible más cercana, como hoy.
2. **Borrar una carpeta asignada:** la spec quita el acceso (C9). La alternativa es pasar el permiso a la carpeta padre, pero eso le daría al usuario más de lo que tenía.
3. **Informes directos (C13):** la carpeta inmediata del informe pasa a ser una raíz del cliente. Si muchos clientes tienen informes sueltos en carpetas con nombres genéricos ("Informes", "Ola 2"), el inicio puede quedar con raíces repetidas o confusas. ¿Preferís que los informes directos aparezcan sueltos en el inicio, sin carpeta?
4. **Usuarios admin:** ¿se les pueden asignar carpetas para "Mis informes"? Esta spec asume que sí, con la casilla de aviso destildada por defecto, como hoy con los informes.
