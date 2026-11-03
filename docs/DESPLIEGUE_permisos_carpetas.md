# Despliegue — Permisos por carpeta

**Proyecto Firebase:** `portal-informes-ec` · **Spec:** `specs/SPEC — Permisos por carpeta (plataforma-informes-ec).md`

A un usuario ahora se le pueden asignar **carpetas**: ve todos sus informes y los de sus subcarpetas, también los que se suban después, y recibe el aviso «Nuevo informe». El acceso de cada usuario ya expandido lo calcula una Cloud Function y lo guarda en `accesoEfectivo/{uid}`, que es lo que leen las reglas y el portal. El cliente navega desde sus carpetas y **deja de poder leer la colección `folders`**.

> ⚠️ **El orden importa.** Las reglas nuevas leen `accesoEfectivo`. Si se despliegan antes de que exista para todos los usuarios, **los clientes pierden acceso** a sus informes. Seguí los pasos en orden.
>
> ⚠️ Hasta terminar el paso 3, **no corras `firebase deploy` sin `--only`**: desplegaría las reglas antes de tiempo.

## Qué cambia

| Requisito | Dónde | Qué hace |
| --- | --- | --- |
| C1 | Permisos → «📁 Carpetas» | Árbol de carpetas con un check por carpeta, protecciones, caducidad y la casilla «Avisar por correo, también cuando se suban informes nuevos a esta carpeta». Escribe `userAccess/{uid}.folderIds` y `folderOptions[fid]` (con `grantedAt`, `grantedBy…`). Una subcarpeta de una asignada se ve tildada en gris, «incluida por …». |
| C2 | Permisos → «📄 Informes» | Un informe que el usuario ve por una carpeta aparece tildado en gris con «📁 vía …». Tildarlo le da además la asignación directa; destildar la directa no le quita el acceso si la carpeta se lo da («también vía …»). |
| C3 | Árbol de carpetas → «👥 Usuarios» | Modal por carpeta. Los que ya la ven por una carpeta de arriba aparecen en gris, «por …». Escribe lo mismo que Permisos. |
| C4 | `functions/portal/permisos.py`, `main.py` | `calcular_acceso` (pura) y `recalcular`, que escribe `accesoEfectivo/{uid}` solo si cambió. Triggers: `notificarAcceso` (`userAccess`, ahora solo recalcula), `onInformeCambio` (`reports`: alta, baja o cambio de carpeta), `onCarpetaCambio` (`folders`: alta, baja, padre, nombre o visibilidad). `reconciliarAccesos` todos los días a las 03:17 de Montevideo y la callable `recalcularAccesos`. |
| C5, C13, C14 | `loadUserReports()` y la navegación del cliente | El cliente lee `accesoEfectivo/{uid}` con `onSnapshot` (un informe nuevo aparece sin recargar) y navega desde sus raíces, sin las carpetas de arriba. Ya no lee `folders`. El admin, en «Mis informes», ve lo mismo con su propio acceso efectivo. |
| C6 | `reportDownloadURL()` | Si Storage todavía no deja abrir un informe asignado (el recálculo tarda 1–3 s), reintenta a los 1, 2 y 4 s mostrando «Preparando el acceso…». |
| C7 | Contadores, matriz, modal «Usuarios» del informe | Cuentan desde `accesoEfectivo`. La matriz muestra «📁» (por carpeta, con la carpeta en el tooltip) distinto de «✓» (directo). El modal muestra «vía …» con un enlace a la carpeta. |
| C8 | `functions/portal/avisos.py` | El aviso sale de los ids nuevos en `accesoEfectivo` (trigger `avisarAccesoNuevo`). `avisarAsignacion` recalcula primero y acepta carpetas. Id del aviso con el `grantedAt` de la carpeta: el panel y el trigger no duplican. La ruta de carpeta del correo arranca en la raíz del usuario. |
| C9 | `deleteFolder()`, `onCarpetaCambio` | La confirmación dice cuántos usuarios pierden acceso. Al borrarla, la función la quita de `folderIds`/`folderOptions`. Nadie gana la carpeta padre. |
| C10 | Configuración → «Accesos por carpeta», `scripts/recalcular_accesos.py` | Botón «🔄 Recalcular accesos» y script de recálculo y verificación («0 diferencias»). |
| Reglas | `firestore.rules`, `storage.rules` | `accesoEfectivo`: cada uno lee el suyo y el admin todos; nadie escribe desde el navegador. `folders`: solo admin. `reports.get`: por `accesoEfectivo` o `userAccess`. Storage: por `accesoEfectivo` (sigue leyendo 2 documentos: `users` y `accesoEfectivo`). |
| C11 | `functions/tests/test_permisos.py`, `test_avisos.py`, `tests/rules/` | Tests del cálculo, de los triggers, de los avisos y de las reglas. |

Respuestas que asume la implementación para las preguntas abiertas de la spec:

1. **Carpetas ocultas:** se pueden asignar. Una carpeta oculta asignada no se muestra: su contenido aparece en el inicio del cliente.
2. **Borrar una carpeta asignada:** quita el acceso (C9), no lo pasa a la carpeta padre.
3. **Informes directos:** la carpeta visible más cercana del informe pasa a ser una raíz del cliente, sin sus antecesoras (como dice la spec).
4. **Admins:** se les pueden asignar carpetas para «Mis informes», con la casilla de aviso destildada por defecto.

Detalles de implementación:

- **Opciones por informe.** Para cada informe se usan las de su asignación directa si existen; si no, las de la carpeta asignada más cercana. Un informe directo sin opciones propias toma las de la carpeta que también se lo da.
- **`accesoEfectivo.carpetas`.** Incluye las carpetas ocultas del subárbol del usuario, **sin nombre**: el portal las necesita para ubicar su contenido en la carpeta visible más cercana. Además se guarda `carpetaIds` (las claves de `carpetas`) para buscar con `array-contains` quién ve una carpeta cuando se renombra o se oculta.
- **Recálculo a todos.** Incluye a los usuarios sin `userAccess`, que reciben un `accesoEfectivo` vacío. Así un cliente sin nada asignado ve «No tenés informes asignados» y no queda esperando.

Fuera de esta entrega (P1 de la spec): caducidad aplicada en el backend (C15), aviso de ganados y perdidos al mover (C16) y filas de carpetas en la matriz (C17).

## Pasos

Desde la raíz del repo, con `main` actualizado (PR mergeado) y `firebase use portal-informes-ec`.

1. **Funciones:**

   ```bash
   firebase deploy --only functions --project portal-informes-ec
   ```

   Se crean `onInformeCambio`, `onCarpetaCambio`, `avisarAccesoNuevo`, `reconciliarAccesos` y `recalcularAccesos`. `notificarAcceso` pasa a solo recalcular (el aviso lo manda `avisarAccesoNuevo`). Las reglas y el front viejos siguen funcionando: todavía leen `userAccess`.

2. **Recalcular a todos los usuarios.** El front nuevo todavía no está publicado, así que se usa el script, con un usuario admin del portal:

   ```bash
   export PORTAL_EMAIL='admin@equipos.com.uy'
   export PORTAL_PASSWORD='…'
   python3 scripts/recalcular_accesos.py
   ```

3. **Verificar.** El script termina con **«✅ 0 diferencias»**: todo `userAccess/{uid}` tiene su `accesoEfectivo/{uid}` y `userAccess.reportIds ⊆ accesoEfectivo.reportIds`. Para volver a mirar sin recalcular, usá `python3 scripts/recalcular_accesos.py --solo-verificar`.

4. **Front:**

   ```bash
   firebase deploy --only hosting --project portal-informes-ec
   ```

   Hasta el paso 5, el cliente ya no lee `folders`, pero la regla todavía se lo permitiría.

5. **Reglas:**

   ```bash
   firebase deploy --only firestore:rules,storage --project portal-informes-ec
   ```

6. **Prueba manual** con un cliente real (ver Verificación).

**Comunicación:** los clientes que hoy tienen informes directos van a ver su navegación más corta, sin las carpetas de arriba. Conviene avisarles a los que más usan el portal.

## Verificación (criterios de aceptación)

Como admin, recargando con Ctrl/Cmd+Shift+R:

1. ☐ Permisos → elegir un cliente → en «📁 Carpetas», tildar «Cliente X». Sus subcarpetas aparecen tildadas en gris, «incluida por Cliente X», y en «📄 Informes» sus informes muestran «📁 vía Cliente X».
2. ☐ Con la casilla de aviso tildada llega **un** correo con los informes de la carpeta. La ruta del correo arranca en la carpeta asignada, por ejemplo «carpeta: Estudio 1 / Ola 2».
3. ☐ Subir 3 informes a esa carpeta: el cliente los ve aparecer sin recargar y recibe **un** correo con los 3. Con la casilla destildada en la carpeta, no sale nada.
4. ☐ Destildar la carpeta le quita esos informes, salvo los que tiene por asignación directa o por otra carpeta.
5. ☐ Árbol de carpetas → «👥 Usuarios» de una subcarpeta: el cliente aparece en gris, «por Cliente X».
6. ☐ El contador «usuarios con acceso» incluye a quienes lo ven por carpeta, y la matriz muestra «📁» para esas celdas.
7. ☐ Borrar una carpeta asignada: la confirmación dice cuántos usuarios pierden acceso. Después, su `userAccess` no conserva la carpeta.
8. ☐ Configuración → «🔄 Recalcular accesos» termina con «0 diferencias».

Como cliente con «Estudio 1» asignada (dentro de «Clientes / Cliente X»):

9. ☐ El inicio muestra «📁 Estudio 1». En ninguna pantalla aparecen «Clientes» ni «Cliente X», y la miga de pan es «🏠 Inicio › Estudio 1 › …».
10. ☐ Abre un informe de una subcarpeta. Las protecciones y la caducidad de la carpeta se aplican, salvo en los informes con asignación propia.
11. ☐ En la consola (F12): `await db.collection('folders').get()` y `await db.collection('folders').doc('<id>').get()` dan `permission-denied`, y `await storage.ref('<storagePath de un informe ajeno>').getDownloadURL()` da `storage/unauthorized`.

## Tests

```bash
firebase emulators:exec --only firestore,auth --project demo-portal "cd functions && venv/bin/python -m pytest -q"
```

```bash
cd tests/rules && npm install && npm test
```

Los tests de `functions/tests/test_permisos.py` del cálculo puro corren sin emuladores. Los de recálculo, triggers y avisos necesitan los emuladores de Firestore y Auth.

## Costos

US$ 0/mes con el volumen del portal: las invocaciones, las lecturas de los recálculos y las escrituras de `accesoEfectivo` quedan dentro del tramo gratuito. Las lecturas de reglas no cambian (`users` + `accesoEfectivo` en lugar de `userAccess`), y los clientes dejan de leer todas las carpetas en cada apertura de «Mis Informes». Detalle en la spec, sección «Costos».

## Rollback

Volver a desplegar las reglas del commit anterior, que leen `userAccess` (sigue completo) y vuelven a abrir `folders`:

```bash
git checkout <commit anterior> -- firestore.rules storage.rules
```

```bash
firebase deploy --only firestore:rules,storage --project portal-informes-ec
```

`accesoEfectivo` no molesta. Si además se vuelve atrás el hosting, el cliente vuelve a navegar desde la raíz. Las carpetas asignadas dejan de dar acceso con las reglas viejas (solo cuentan las asignaciones directas).
