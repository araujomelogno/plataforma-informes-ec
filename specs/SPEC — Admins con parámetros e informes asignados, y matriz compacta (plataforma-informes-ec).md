# SPEC — Admins con parámetros e informes asignados, y matriz compacta

Oct 22, 2026 · @Equipos

## Resumen

Dos cambios chicos, solo de front (`index.html`) y del aviso por correo ya existente: **(A)** los usuarios admin pasan a poder tener parámetros e informes asignados, con una sección "Mis informes" para abrirlos rápido; **(B)** la matriz usuarios/informes muestra solo las columnas de usuarios que tienen al menos un ✓ en los informes visibles.

Repositorio `araujomelogno/plataforma-informes-ec`, revisado sobre `3d1a490` (ya incluye el alta con enlace y los avisos por correo).

### Cómo funciona hoy

Los admins están excluidos a propósito en seis lugares:

| Dónde | Código | Efecto |
| --- | --- | --- |
| Tabla de usuarios | `renderUsersTable()`: `permBtn` y `paramsBtn` vacíos si `isAdmin` | Un admin no tiene botones "🔐 Permisos" ni "⚙️ Parámetros" |
| Pestaña Permisos | `populatePermSelect()`: `allUsers.filter(u => u.role !== 'admin')` | No se lo puede elegir |
| Modal "Usuarios" de un informe | `openReportUsersModal()`: mismo filtro | No se le puede tildar un informe |
| Matriz | `renderMatrix()`: `allNonAdmin` | No aparece como columna |
| Ingreso | `enterPortal()`: admin → `renderAdmin()`, nunca `renderUser()` | No tiene vista "mis informes" |
| Avisos por correo | `functions/portal/avisos.py` (líneas 88 y 237) | Si se le asignara algo, el aviso se omite |

Además: el visor envía a cada informe HTML los parámetros del usuario logueado (`setupPortalParams`, `currentUserData.params`). Como un admin no puede tener parámetros, cuando previsualiza un dashboard parametrizado (`previewReport`) el informe recibe `params: {}` y lo ve distinto a como lo ve un cliente.

La matriz (`renderMatrix()`) arma una columna por cada usuario no admin que pase el filtro de email, tenga o no algún ✓. Con muchos usuarios la tabla se vuelve muy ancha y casi toda de puntos (`·`).

## Cambio A — Admins con parámetros e informes asignados

**Problema.** Un admin ve todos los informes en la lista general, pero no tiene forma de quedarse con "los suyos" a mano; con cientos de archivos y carpetas, encontrar el informe del estudio que sigue lleva tiempo. Y al no poder tener parámetros, no puede ver un dashboard parametrizado como lo ve un cliente, ni usar parámetros propios (p. ej. su región o cliente).

**Objetivos**

1. Un admin abre un informe asignado en 2 clics desde que entra al portal.
2. Un admin con parámetros ve los dashboards parametrizados con esos parámetros, en "Mis informes" y en la vista previa.
3. Asignar a un admin funciona igual que a un cliente, desde las mismas tres pantallas (Permisos, modal del informe, matriz).

**No-objetivos**

- **Cambiar qué puede ver un admin.** Sigue viendo y administrando todos los informes; la asignación es un atajo, no un permiso.
- **Aplicar protecciones a admins** (marca de agua, sin impresión, sin copia, caducidad). Un admin puede bajarse el archivo desde la lista general, así que restringirlo en "Mis informes" no protege nada.
- **"Ver como" otro usuario** (previsualizar con los parámetros de un cliente puntual). Útil, pero es otra funcionalidad (P2).

**Historias de usuario**

- Como admin, quiero que otro admin (o yo) me asigne informes, para tener a mano los del estudio que sigo.
- Como admin, quiero una sección "Mis informes" con la misma navegación por carpetas que ve el cliente, para encontrar rápido lo mío.
- Como admin, quiero tener parámetros propios, para que los dashboards parametrizados me muestren lo mismo que a un cliente con esos valores.
- Como admin, quiero ver en la matriz y en la pestaña Permisos qué tienen asignado los admins, para tener el panorama completo.

### Requisitos P0

**A1. Parámetros para admins.** El botón "⚙️ Parámetros" aparece también en filas de admins; usa el mismo modal (`openUserParamsModal`) y guarda en `users/{uid}.params`.

- [ ] Un admin puede definir, editar y borrar parámetros de cualquier admin, incluido él mismo.
- [ ] Con parámetros `{region: 'Norte'}`, la vista previa de un informe HTML que pide `__portalParamsRequest` recibe `params: {region: 'Norte'}`.
- [ ] Al cambiar los parámetros propios, la próxima apertura usa los nuevos sin recargar (se actualiza `currentUserData.params`).

**A2. Asignar informes a admins.** Los admins aparecen en la pestaña Permisos, en el modal "Usuarios" de cada informe y tienen el botón "🔐 Permisos" en la tabla de usuarios. Se identifican con la insignia "admin" junto al email.

- [ ] Asignar o quitar un informe a un admin escribe `userAccess/{uid}` igual que para un cliente (con `grantedBy…`).
- [ ] Para admins, la pestaña Permisos y el modal no muestran las opciones de protección ni caducidad (no se aplican; ver no-objetivos).
- [ ] Los contadores "usuarios con acceso" de la lista de informes cuentan también a los admins asignados.

**A3. Sección "Mis informes" para admins.** Nuevo ítem en la barra lateral del admin, arriba de "Informes", con la misma navegación por carpetas de la vista cliente (`loadUserReports` / `renderUserLevel`, respetando carpetas ocultas).

- [ ] Un admin con 3 informes asignados ve esos 3 en "Mis informes", en sus carpetas; uno sin asignaciones ve "No tenés informes asignados" con un enlace a la pestaña Permisos.
- [ ] Abrir un informe desde ahí lo muestra sin protecciones (igual que `previewReport`) y con los parámetros del admin.
- [ ] El ingreso del admin sigue cayendo en "Informes"; "Mis informes" no reemplaza la pantalla inicial (ver pregunta abierta).

**A4. Avisos por correo.** Asignar un informe a un admin respeta la misma casilla "Avisar al usuario por correo". Se quita el filtro de admins en `avisos.py` y se deja la casilla destildada por defecto cuando el destinatario es admin.

- [ ] Asignar a un admin con la casilla destildada no envía nada; tildándola, envía "Nuevo informe" como a cualquier usuario.

### P1

- **A5. Dejar el rastro de uso de admins aparte.** Las aperturas desde "Mis informes" registran `role: 'admin'` en `sessions` y `dashboardEvents` (o no se registran), para no mezclar el uso interno con las métricas de clientes.

## Cambio B — Matriz que contrae columnas

**Problema.** La matriz pone una columna por usuario aunque no tenga ningún acceso. Al filtrar por un informe o un estudio, el admin quiere ver quién lo tiene, pero tiene que recorrer de costado decenas de columnas vacías.

**Regla.** Una columna de usuario se muestra solo si ese usuario tiene al menos un ✓ en las filas que están visibles. La regla se recalcula con cada cambio de los filtros, así que al escribir en "🔎 Informe…" la tabla se angosta a los usuarios de esos informes.

Como los usuarios ocultos tienen 0 en todas las filas visibles, la columna "Total" de cada informe no cambia.

### Requisitos P0

**B1. Contraer columnas sin ✓.** En `renderMatrix()`, después de filtrar informes y usuarios, se descartan los usuarios sin ningún acceso a los informes filtrados.

- [ ] Sin filtros, se ven solo los usuarios con al menos un informe asignado.
- [ ] Filtrando "Encuesta MSP", se ven solo los usuarios con acceso a algún informe que coincida; al borrar el filtro vuelven los demás.
- [ ] El filtro "🔎 Usuario (email)…" se sigue aplicando encima de la regla.
- [ ] La fila "Informes por usuario" y la columna "Total" coinciden con las de hoy para los usuarios mostrados.

**B2. Decir qué se ocultó.** Arriba de la tabla, una línea con el conteo: "Mostrando 12 de 87 usuarios (los demás no tienen acceso a los informes filtrados)".

- [ ] El conteo se actualiza con cada tecla en los filtros.

**B3. Estado vacío propio.** Si ningún usuario tiene acceso a los informes filtrados, se muestra "Ningún usuario tiene acceso a estos informes" en vez de una tabla con solo la columna de nombres.

**B4. Admins en la matriz.** Con el cambio A, los admins con asignaciones entran como columna, con una marca "admin" en el encabezado para distinguirlos.

### P1

- **B5. Interruptor "Mostrar todos los usuarios".** Apagado por defecto; prendido, vuelve al comportamiento de hoy (útil para ver quién no tiene nada). Se recuerda en `localStorage` del navegador del admin.
- **B6. Ocultar informes sin usuarios.** El mismo criterio para filas: interruptor para esconder informes sin ningún ✓ entre los usuarios visibles.

## Diseño técnico

No hacen falta colecciones nuevas, cambios de reglas de Firestore ni funciones nuevas. `userAccess/{uid}` y `users/{uid}.params` ya los escribe solo un admin y cada usuario lee los suyos, lo que también vale para un admin.

| Archivo / función | Cambio | Req. |
| --- | --- | --- |
| `renderUsersTable()` | Mostrar `permBtn` y `paramsBtn` también si `isAdmin` | A1, A2 |
| `saveUserParams` (modal de parámetros) | Si `uid === currentUser.uid`, actualizar también `currentUserData.params` | A1 |
| `populatePermSelect()`, `openReportUsersModal()` | Quitar el filtro `role !== 'admin'`; agregar la insignia "admin" en la opción y en la fila | A2 |
| `loadUserPermissions()`, `reportUserOptsHTML()` | Si el usuario es admin, no dibujar protecciones ni caducidad | A2 |
| `tpl-admin` + `switchTab()` | Ítem "Mis informes" (`nav-mine`) y pestaña `tab-mine` con un contenedor propio | A3 |
| `loadUserReports()` / `renderUserLevel()` | Recibir el id del contenedor en vez de usar fijo `user-reports-container`, para reutilizarlas en `tab-mine` | A3 |
| Apertura desde "Mis informes" | Usar las opciones sin protecciones de `previewReport` y pasar `reportId` | A3 |
| `functions/portal/avisos.py` | Quitar `role == 'admin'` de las condiciones de omisión (líneas 88 y 237) | A4 |
| Casilla "Avisar al usuario" | Destildada por defecto si el destinatario es admin | A4 |
| `renderMatrix()` | Incluir admins; después de filtrar, `users = users.filter(u => reports.some(r => has(u.uid, r.id)))`; conteo y estado vacío | B1–B4 |
| `tab-matrix` (HTML) | Línea de conteo arriba de `matrix-content` | B2 |

**Rendimiento de la matriz.** El filtro agrega una pasada usuarios × informes visibles, que ya se hace para pintar las celdas. Con 200 usuarios y 500 informes son 100.000 consultas a un `Set`, del orden de milisegundos; no hace falta debounce.

**Pruebas.** Agregar a `functions/tests` el caso "asignación a admin con aviso activado → envía" y "sin aviso → omitido". El front no tiene pruebas automáticas; los criterios de aceptación de arriba son el checklist manual.

## Costos

Costo recurrente adicional: **US$0**. Todo es código de front sobre datos que ya existen. Las únicas operaciones nuevas son lecturas de Firestore cuando un admin abre "Mis informes": 1 lectura de `userAccess` más 1 por informe asignado. Eso son decenas por día, contra 50.000 lecturas diarias gratuitas.

El único consumo a vigilar es el de A4. Si se tilda el aviso para admins, esos correos salen del mismo cupo de 2.000 destinatarios por día de `notificaciones@`, compartido con `paneles`. Por eso la casilla viene destildada por defecto para admins.

## Preguntas abiertas y fases

**Preguntas abiertas** (ninguna bloquea el cambio B)

- [ ] Al entrar, ¿un admin con informes asignados debería caer en "Mis informes" en vez de "Informes"? La propuesta es que no, para no cambiarle la pantalla de inicio a nadie. (Producto)
- [ ] ¿Las aperturas de admins se excluyen de las métricas o se registran marcadas con `role: 'admin'` (A5)? (Producto)
- [ ] ¿Un admin puede editar sus propios parámetros, o solo otro admin? La propuesta es que pueda, porque igual puede editar los de todos. (Producto)
- [ ] Si a un admin se le quita el rol, ¿sus asignaciones pasan tal cual a ser accesos de cliente, con las protecciones por defecto? La propuesta es que sí, aplicando `DEFAULT_OPTS` a las que no tengan opciones. (Producto)

**Fases** (cada una se despliega sola)

1. **Cambio B** (matriz): B1–B4. Es el más chico y sin dependencias.
2. **Cambio A, front**: A1–A3.
3. **Cambio A, avisos**: A4, que toca `functions/` y requiere redeploy de las funciones.
4. **P1**: A5, B5, B6.
