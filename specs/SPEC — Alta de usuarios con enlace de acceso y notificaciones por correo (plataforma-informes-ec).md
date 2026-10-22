# SPEC — Alta de usuarios con enlace de acceso y notificaciones por correo

Oct 9, 2026 · @Equipos

## Resumen

El alta de usuarios del portal de informes deja de pedir una contraseña: el sistema crea la cuenta con una clave aleatoria y le manda a la persona un enlace para fijar la suya, desde `notificaciones@equipos.com.uy`, igual que en `paneles`. Además, cada vez que un admin le da acceso a un informe, el usuario recibe un aviso por correo. Los textos de ambos correos se editan en una nueva sección **Configuración** del panel admin.

**Repositorio:** `araujomelogno/plataforma-informes-ec` (proyecto Firebase `portal-informes-ec`). **Referencia:** `araujomelogno/paneles`, módulos `functions/panel_api/usuarios.py` y `functions/panel_api/correo.py`.

### Cómo funciona hoy (según el código)

- **Alta individual** (`index.html`, `createUser()` → `provisionUser(email, pass)`): el admin escribe email y una "contraseña temporal" de 6+ caracteres. El front llama directo a la REST API `identitytoolkit…/accounts:signUp` con la `apiKey` pública y después crea `users/{uid}` con `role: 'user'`, `creadoPor` y `creadoPorUid`. La contraseña se la tiene que pasar el admin a mano.
- **Alta masiva** (`importUsers()`): Excel/CSV con email en la columna 1 y contraseña en la 2; reutiliza `provisionUser`.
- **Restablecer contraseña** (`resetUserPassword()` y "¿Olvidaste tu contraseña?" en el login): usa `sendPasswordResetEmail` de Firebase, que sale desde el remitente por defecto de Firebase, no desde Workspace.
- **Asignar acceso a un informe**: todo pasa por `grantReportToUser(userId, reportId, grant)`, que escribe `userAccess/{uid}` (`reportIds[]` + `options[reportId]` con `grantedByUid`, `grantedByEmail`, `grantedAt`). Se llama desde la pestaña Permisos (`togglePerm`) y desde el modal "Usuarios" de cada informe (`toggleReportUser`). Hoy no se avisa nada al usuario.
- **No hay backend**: el repo es un único `index.html` estático en Firebase Hosting, sin `functions/`. No existe una sección Configuración.

### Cómo lo resuelve `paneles`

- Una Cloud Function (Python) crea la cuenta en Firebase Auth con una clave aleatoria (`secrets.token_urlsafe`) que no se guarda en ningún lado.
- Genera un enlace de restablecimiento con el Admin SDK (`generate_password_reset_link`) y lo manda por SMTP de Google Workspace (`smtp.gmail.com:587`, STARTTLS) como `notificaciones@equipos.com.uy`. La contraseña de aplicación vive en Secret Manager (`SMTP_PASSWORD`).
- El enlace se muestra una vez en pantalla además del correo: si el envío falla, el alta no falla.
- Cada envío se registra (enviado/fallido + motivo) y el registro se purga a los 90 días.
- Las plantillas están fijas en el código (`PLANTILLAS` en `correo.py`); acá la diferencia es que tienen que ser editables desde Configuración.

## Problema

Hoy el admin inventa una contraseña, la escribe en el formulario y se la tiene que hacer llegar al cliente por otro canal (mail personal, WhatsApp, teléfono). Eso deja contraseñas conocidas por terceros, viajando en texto plano y muchas veces nunca cambiadas, para un portal donde los clientes ven informes confidenciales. Además, cuando se le habilita un informe a alguien, la persona no se entera salvo que el equipo le avise a mano, así que el informe queda publicado pero sin leer.

Afecta a los admins de Equipos que dan de alta clientes (cada alta y cada importación masiva) y a los usuarios cliente, que reciben credenciales informales y no saben cuándo tienen material nuevo.

## Objetivos y no-objetivos

### Objetivos

1. **Ningún admin conoce la contraseña de un cliente.** 100% de las altas nuevas (individuales e importadas) se hacen sin contraseña escrita por el admin.
2. **El cliente entra solo.** Al menos 80% de los usuarios nuevos fija su contraseña e ingresa dentro de los 7 días del alta, sin intervención manual.
3. **Avisar cada acceso nuevo.** 100% de las asignaciones de informe generan un correo (salvo que el admin elija no notificar), con su resultado registrado.
4. **Los textos los maneja el equipo, no el código.** Cambiar asunto o cuerpo de un correo no requiere deploy.
5. **Un fallo de correo nunca rompe un alta ni una asignación.** Si el SMTP falla, la operación queda hecha y el admin ve el motivo y una salida (copiar el enlace / reenviar).

### No-objetivos

- **Correos HTML con diseño de marca.** Se arranca con texto plano, como `paneles`; HTML agrega riesgo de spam y trabajo de maquetación sin resolver el problema central (queda como P2).
- **Aviso por actualización de un informe ya asignado** ("sobrescribir" en `overwriteReport`). Es otro disparador con otra lógica de frecuencia; va en una iteración aparte.
- **Aviso al quitar un acceso.** No aporta al cliente y puede generar consultas innecesarias.
- **Login sin contraseña (magic link permanente).** Cambia el modelo de autenticación y convive mal con el 2FA/TOTP que ya existe; acá se mantiene email + contraseña.
- **Proveedor transaccional de correo (SendGrid, Mailgun, etc.).** El volumen no lo justifica; se usa la cuenta de Workspace que ya se paga.

## Historias de usuario

**Admin de Equipos**

- Como admin, quiero dar de alta a un cliente escribiendo solo su email, para no tener que inventar ni transmitir una contraseña.
- Como admin, quiero ver si el correo de bienvenida salió o falló (y por qué), para saber si tengo que pasarle el enlace por otro canal.
- Como admin, quiero poder copiar el enlace de acceso una sola vez si el correo falló, para no dejar al cliente sin entrada.
- Como admin, quiero importar un Excel con solo emails y que a cada uno le llegue su invitación, para dar de alta a un cliente con muchos usuarios de una vez.
- Como admin, quiero reenviar el acceso a un usuario que perdió o dejó vencer el enlace, para destrabarlo sin borrarlo y volverlo a crear.
- Como admin, quiero que el usuario reciba un aviso cuando le habilito un informe, para no tener que escribirle a mano.
- Como admin, quiero poder habilitar un informe sin notificar (por ejemplo, al preparar accesos antes de publicar), para controlar cuándo se entera el cliente.
- Como admin, quiero editar el asunto y el texto de cada correo desde Configuración, con variables como el nombre del informe, para ajustar el tono sin pedirle un cambio al desarrollador.
- Como admin, quiero mandarme un correo de prueba con la plantilla editada, para ver cómo llega antes de que lo reciba un cliente.

**Usuario cliente**

- Como cliente, quiero recibir un correo de Equipos con un enlace para crear mi contraseña, para entrar al portal sin depender de que alguien me la dicte.
- Como cliente, quiero recibir un aviso con el nombre del informe y un enlace al portal cuando me dan acceso, para saber que hay algo nuevo para mí.
- Como cliente cuyo enlace venció, quiero que el correo me diga cómo pedir otro, para no quedar trabado.

**Casos borde**

- Alta de un email que ya existe en Firebase Auth: no se crea otra cuenta ni se pisa la clave; se informa y se ofrece "Reenviar acceso".
- Admin que tilda y destilda el mismo informe en segundos: no deberían salir correos duplicados ni avisos de algo que ya no tiene.
- Admin que habilita 10 informes seguidos a la misma persona: idealmente le llega un solo correo con la lista (P1).
- Usuario con rol `admin`: no se le notifican asignaciones (no tiene permisos por informe).

## Requisitos

### P0 — Imprescindibles

**R1. Alta sin contraseña.** El formulario "Crear nuevo usuario" pide solo email. Una Cloud Function `crearUsuario` (solo admins) crea la cuenta con una clave aleatoria que no se guarda ni se devuelve, crea `users/{uid}` con los mismos campos de hoy (`email`, `role: 'user'`, `createdAt`, `creadoPor`, `creadoPorUid`), genera el enlace de acceso con `generatePasswordResetLink` y lo manda con la plantilla "Bienvenida".

- [ ] Dado un admin logueado, cuando crea `cliente@empresa.com`, entonces la cuenta existe en Auth, el doc `users/{uid}` existe y le llega un correo desde `notificaciones@equipos.com.uy` con un enlace que lleva a fijar contraseña.
- [ ] El campo "Contraseña temporal" y el texto "podrá cambiar su contraseña desde Firebase console" desaparecen.
- [ ] Un usuario no admin que llama a la función recibe `permission-denied` y no se crea nada.
- [ ] Si el email ya existe en Auth, no se crea otra cuenta ni se toca su clave; la respuesta dice "ya existía" y ofrece "Reenviar acceso".
- [ ] La contraseña aleatoria no aparece en logs, respuestas ni Firestore.

**R2. El correo es una comodidad, no un punto de falla.** Si el SMTP falla, la cuenta queda creada; el admin ve el motivo y el enlace en un modal "mostrar una vez" con botón Copiar, igual que en `paneles`.

- [ ] Con `SMTP_PASSWORD` inválida, el alta termina OK, el modal muestra el enlace y el motivo ("Workspace rechazó la credencial…") sin exponer la contraseña.
- [ ] El enlace no se guarda en Firestore ni en logs.

**R3. Reenviar acceso.** En la tabla de usuarios, "Restablecer contraseña" pasa a llamarse "Reenviar acceso" y usa la función `reenviarAcceso` (nuevo enlace + plantilla "Bienvenida" o "Restablecer").

- [ ] Reenviar a un usuario existente genera un enlace nuevo y lo manda; queda registrado quién lo pidió y cuándo.

**R4. Importación masiva solo con emails.** El Excel/CSV pasa a una sola columna obligatoria (email). Cada fila usa `crearUsuario`. Si la 2ª columna trae contraseñas, se ignoran y se avisa.

- [ ] El resumen final separa: creados y notificados · creados sin correo (con motivo) · ya existían · inválidos.
- [ ] Si la importación supera el cupo diario disponible (ver Costos y límites), se rechaza antes de empezar con un mensaje claro.

**R5. Aviso al asignar un informe.** Cuando un usuario gana acceso a un informe (un `reportId` nuevo en `userAccess/{uid}.reportIds`), se le manda la plantilla "Nuevo informe". Se dispara desde el servidor (trigger de Firestore), así cubre la pestaña Permisos, el modal "Usuarios" del informe y cualquier vía futura.

- [ ] Habilitar un informe desde Permisos o desde el modal genera exactamente un correo.
- [ ] Quitar un acceso, cambiar una protección (descarga, impresión, caducidad) o reasignar un informe que ya tenía no genera correo.
- [ ] Usuarios con `role: 'admin'` no reciben estos avisos.
- [ ] Un fallo de envío no revierte el permiso.

**R6. Sección Configuración → Correos.** Nueva pestaña "⚙️ Configuración" en la barra lateral del admin con una subsección "Correos". Por cada plantilla: asunto y cuerpo (texto plano), lista de variables disponibles, y un interruptor "Enviar este correo" (para "Nuevo informe").

- [ ] Guardar una plantilla la aplica al siguiente envío, sin deploy.
- [ ] La plantilla "Bienvenida" no se puede guardar sin `{{enlace}}`; una variable desconocida (p. ej. `{{nombre_informe}}` mal escrito) se marca como error antes de guardar.
- [ ] Si nunca se editó una plantilla, se usa el texto por defecto definido en el código.
- [ ] Solo admins pueden leer y escribir la configuración (reglas de Firestore).

**R7. Registro de envíos.** Cada intento de envío deja una fila en `mailLog` (tipo, destinatario, estado, motivo, intentos, quién lo disparó, fecha). Se purga a los 90 días.

- [ ] Un admin puede ver en Configuración → Correos los últimos envíos, filtrar fallidos y ver el contador de las últimas 24 h.

### P1 — Muy deseables

- **R8. "No notificar" por asignación.** Casilla "Avisar al usuario por correo" (marcada por defecto) en Permisos y en el modal del informe; si se desmarca, el trigger no envía. Criterio: con la casilla desmarcada, habilitar un informe no genera correo y el log no muestra intento.
- **R9. Agrupar avisos.** Si a un usuario se le habilitan varios informes en una ventana corta (p. ej. 2 minutos), sale un solo correo con la lista. Criterio: 5 informes habilitados en 30 segundos → 1 correo con 5 nombres.
- **R10. Correo de prueba.** Botón "Enviarme una prueba" por plantilla, que manda al admin logueado con datos de ejemplo.
- **R11. "¿Olvidaste tu contraseña?" por Workspace.** El login usa también la plantilla "Restablecer" desde `notificaciones@`, en vez del remitente por defecto de Firebase, para que todos los correos del portal salgan del mismo lado. Debe responder igual exista o no la cuenta.
- **R12. Remitente y Reply-To configurables** (nombre visible, dirección de respuesta) desde Configuración.

### P2 — A futuro (diseñar sin cerrarles la puerta)

- Plantillas en HTML con logo y botón.
- Aviso cuando se actualiza un informe ya asignado.
- Plantillas por cliente o por carpeta (p. ej. un texto distinto para cada estudio).
- Mover el envío a una cola (Cloud Tasks) si el volumen crece, como en `SPEC_ingesta_diferida_cloud_tasks.md` de `paneles`.

### Variables de plantilla

| Variable | Disponible en | Contenido |
| --- | --- | --- |
| `{{email}}` | Todas | Email del usuario destinatario |
| `{{enlace}}` | Bienvenida, Restablecer | Enlace para fijar la contraseña |
| `{{url_portal}}` | Todas | URL del portal (dominio de Hosting) |
| `{{admin}}` | Bienvenida, Nuevo informe | Email del admin que dio el alta o el acceso |
| `{{informe}}` | Nuevo informe | Nombre del informe (en el agrupado, lista de nombres) |
| `{{carpeta}}` | Nuevo informe | Ruta de la carpeta del informe, si tiene |
| `{{vence}}` | Nuevo informe | Fecha de caducidad del acceso, si se configuró |

## Diseño técnico propuesto

Se agrega un backend mínimo de Cloud Functions (2ª gen, Python) al repo, reutilizando el módulo `correo.py` de `paneles` casi tal cual. Mandar SMTP y generar enlaces de acceso requiere el Admin SDK y un secreto, cosas que no pueden vivir en el `index.html` público.

&#91;embedded content: flujo de los dos correos · 2 disparadores, 2 funciones nuevas\]

El navegador solo dispara la acción; la cuenta, el enlace y el envío ocurren en el servidor, que es el único que conoce la contraseña SMTP.

### Componentes

| Pieza | Tipo | Qué hace |
| --- | --- | --- |
| `crearUsuario` | Callable | Verifica que quien llama tenga `users/{uid}.role == 'admin'`. Crea la cuenta (clave aleatoria), el doc `users/{uid}`, genera el enlace y manda "Bienvenida". Devuelve `{uid, estado, correo:{enviado, detalle}, enlace?}`; el enlace solo vuelve si el correo falló. |
| `reenviarAcceso` | Callable | Solo admin. Nuevo enlace + correo; registra quién lo pidió. |
| `notificarAcceso` | Trigger `onDocumentWritten('userAccess/{uid}')` | Compara `reportIds` antes y después; por cada id nuevo (y con `options[id].notificar !== false`) arma "Nuevo informe" y envía. Ignora usuarios admin. |
| `enviarPrueba` (P1) | Callable | Manda una plantilla con datos de ejemplo al admin que la pide. |
| `correo.py` | Módulo | Copia de `paneles`: SMTP Workspace, reintentos acotados, clasificación de errores, sin loguear credenciales. Se le cambia el registro: de Postgres a Firestore (`mailLog`). |

### Enlace de acceso

`auth.generate_password_reset_link(email, ActionCodeSettings(url=<URL del portal>))`, como en `paneles`. Al fijar la contraseña, Firebase deja a la persona en el portal. Los enlaces de restablecimiento de Firebase vencen a la hora (a verificar en la consola de Identity Platform), por eso: el correo explica cómo pedir otro con "¿Olvidaste tu contraseña?", y existe "Reenviar acceso".

### Modelo de datos (Firestore)

| Colección / doc | Campos | Reglas |
| --- | --- | --- |
| `config/correos` | `plantillas.{bienvenida, restablecer, nuevoInforme}.{asunto, cuerpo, activo}`, `remitenteNombre`, `replyTo`, `actualizadoPor`, `actualizadoEn` | Lee y escribe solo admin |
| `mailLog/{id}` | `tipo`, `destinatario`, `estado` (enviado / fallido / omitido), `motivo`, `intentos`, `duracionMs`, `disparadoPor`, `reportId?`, `eventId?`, `creadoEn` | Lee solo admin; escribe solo el backend (`allow write: if false`) |
| `userAccess/{uid}.options[reportId].notificar` (P1) | booleano, default `true` | Sin cambios |

### Plantillas

- Texto plano con variables `{{nombre}}`; se reemplazan en el servidor. Una variable desconocida se rechaza al guardar (en el front) y, por las dudas, se deja vacía al enviar.
- Los textos por defecto viven en el código (como `PLANTILLAS` en `paneles`) y se usan si `config/correos` no tiene la plantilla.
- Se agrega siempre una firma fija al pie ("Equipos Consultores · Portal de informes — Este correo se envió automáticamente…").

### Idempotencia del trigger

Los triggers de Firestore pueden ejecutarse más de una vez por el mismo cambio. Antes de enviar, la función crea `mailLog/{eventId}-{reportId}` con `create()` (falla si ya existe); si falla, no envía. Así un reintento no duplica correos.

### Cambios en `index.html`

- `createUser()` e `importUsers()` llaman a `crearUsuario` vía `httpsCallable` (SDK `firebase-functions` 10.7.0, el mismo que ya se usa para Auth); se borra `provisionUser()` y la llamada a `accounts:signUp`.
- `resetUserPassword()` pasa a `reenviarAcceso`.
- Nueva pestaña Configuración: editor de plantillas, lista de variables, vista previa, interruptor por plantilla y tabla de últimos envíos.
- (P1) Casilla "Avisar al usuario por correo" en Permisos y en el modal del informe; se escribe en `options[reportId].notificar` en el mismo `set` de `grantReportToUser`.

### Secretos y configuración

- `SMTP_PASSWORD` en Secret Manager de `portal-informes-ec`, declarado en `secrets=` de cada función que envía.
- `SMTP_USUARIO = notificaciones@equipos.com.uy`, `SMTP_HOST = smtp.gmail.com`, `SMTP_PORT = 587` como variables de entorno.
- La contraseña de aplicación nunca va al repo, a la spec ni al front.

## Costos y límites

Costo recurrente esperado: **US$0 a US$0,50 por mes**, casi todo por almacenar las imágenes de las funciones. El único requisito con impacto es que `portal-informes-ec` esté en plan **Blaze** (pago por uso); el README indica que el 2FA/TOTP ya lo exige, así que probablemente ya lo está.

Supuesto de volumen: hasta 300 altas y 2.000 avisos de informe por mes (≈2.500 envíos, ≈3.000 invocaciones). Precios de lista de GCP a mi fecha de conocimiento; conviene confirmarlos en la consola antes de activar.

| Ítem | Tramo gratuito mensual | Uso estimado | Costo estimado |
| --- | --- | --- | --- |
| Cloud Functions 2ª gen (Cloud Run) | 2 M invocaciones, 180.000 vCPU-s, 360.000 GiB-s | ≈3.000 invocaciones de ≈2 s | US$0 |
| Secret Manager | 6 versiones activas, 10.000 accesos | 1 secreto, < 3.000 accesos | US$0 (luego US$0,06 por versión y US$0,03 cada 10.000 accesos) |
| Firestore (`mailLog`, `config`) | 20.000 escrituras y 50.000 lecturas por día | < 200 escrituras por día | US$0 |
| Artifact Registry (imágenes de las funciones) | 0,5 GB | 1 a 2 GB sin política de limpieza | US$0,10 por GB-mes → US$0 a 0,20 |
| Cloud Build (deploys) | 2.500 minutos de build | ≈10 deploys de 3 min | US$0 |
| SMTP Google Workspace | Incluido en la licencia de `notificaciones@` | Ya existe y se paga por `paneles` | US$0 adicional |

**Límite que sí importa: 2.000 destinatarios por día por cuenta de Workspace**, y la cuenta `notificaciones@` se comparte con `paneles`. Una importación grande el mismo día que una convocatoria del panel puede agotar el cupo y hacer rebotar correos de los dos sistemas. Por eso R4 valida el cupo antes de importar y R7 muestra el contador de 24 h.

Medidas de control de costo: activar la política de limpieza de imágenes (`firebase functions:artifacts:setpolicy`) y una alerta de presupuesto en US$5 por mes en la cuenta de facturación.

Si en el futuro el volumen supera ese cupo de forma sostenida, la salida es un proveedor transaccional con dominio verificado (costo por uso, a cotizar en ese momento); hoy no se justifica.

## Seguridad

### Credencial SMTP

- Generar una **contraseña de aplicación nueva y exclusiva** para este proyecto en la cuenta `notificaciones@` (Workspace permite varias). Así se puede revocar sin afectar a `paneles`.
- La contraseña que se compartió en la conversación donde se pidió esta spec debe considerarse expuesta: revocarla en la cuenta de Google, y si es la misma que usa `paneles`, actualizar ahí `SMTP_PASSWORD` en Secret Manager.
- La contraseña solo vive en Secret Manager. Nunca en el repo, en esta spec, en `index.html`, en logs ni en mensajes de error (`correo.py` ya lo cuida).

### Hallazgo en el código actual (urgente, independiente de esta spec)

La regla de `firestore.rules` para `users/{uid}` permite que cada usuario escriba su propio documento completo (`allow write: if isAuth() && (request.auth.uid == uid || isAdmin())`). Como `isAdmin()` lee justamente `users/{uid}.role`, **cualquier usuario cliente puede ponerse `role: 'admin'` a sí mismo** desde la consola del navegador y ver todos los informes. Además, el alta pública con `accounts:signUp` y la `apiKey` (que es pública) permite crear cuentas sin pasar por un admin.

Correcciones:

1. **Ya (hotfix):** limitar la escritura propia a los campos que el front realmente toca, p. ej. `request.resource.data.diff(resource.data).affectedKeys().hasOnly(['mfaEnrolled'])`, y prohibir `create` propio.
2. **Con esta spec (P0):** una vez que las altas pasan por `crearUsuario`, deshabilitar el registro público de usuarios en Identity Platform (Authentication → Configuración → "Permitir creación de cuentas").

### Resto

- Las funciones callable verifican el rol leyendo `users/{uid}` con el Admin SDK, no confiando en datos que mande el cliente.
- El enlace de acceso no se guarda ni se loguea; si se muestra en pantalla (fallo de correo), es una sola vez.
- `mailLog` guarda direcciones de correo (dato personal): solo lo leen admins y se purga a los 90 días.
- Revisar SPF, DKIM y DMARC de `equipos.com.uy` (ya debería estar resuelto por `paneles`); si no, los avisos caen en spam.

## Métricas de éxito

Se miden con `mailLog`, `users` y la colección `sessions` que el portal ya registra. Evaluación a las 2 semanas y a los 2 meses del lanzamiento.

| Métrica | Tipo | Cómo se mide | Meta | Ideal |
| --- | --- | --- | --- | --- |
| Correos enviados OK | Adelantada | `mailLog` estado = enviado / total | ≥ 98% | ≥ 99,5% |
| Altas con contraseña escrita por un admin | Adelantada | Altas por fuera de `crearUsuario` | 0 | 0 |
| Usuarios nuevos que ingresan en 7 días | Adelantada | Primera `sessions` ≤ 7 días después de `users.createdAt` | ≥ 80% | ≥ 90% |
| Altas que necesitan "Reenviar acceso" | Adelantada | Usuarios con ≥ 1 reenvío / altas | ≤ 20% | ≤ 10% |
| Informes abiertos en 7 días tras el aviso | Atrasada | Primera apertura del informe en `sessions` / avisos enviados | ≥ 60% | ≥ 75% |
| Consultas de clientes por acceso | Atrasada | Conteo manual del equipo, antes vs después | -50% | -75% |

## Preguntas abiertas

**Bloqueantes (antes de empezar)**

- [ ] ¿`portal-informes-ec` ya está en plan Blaze? (Operaciones) — si no, activarlo con alerta de presupuesto.
- [ ] ¿Alcanza un enlace que vence a la hora, o se quiere una invitación que dure días? Lo segundo exige un token propio en vez del enlace de Firebase y suma trabajo (Producto).
- [ ] ¿Se genera una contraseña de aplicación exclusiva para este proyecto, o se comparte la de `paneles`? Se recomienda exclusiva (Operaciones).
- [ ] ¿Qué URL va en los correos: el dominio `.web.app` / `.firebaseapp.com` o un dominio propio? (Operaciones)

**No bloqueantes (se resuelven durante la implementación)**

- [ ] ¿"¿Olvidaste tu contraseña?" del login también pasa a Workspace (R11) o queda con el remitente de Firebase? (Producto)
- [ ] ¿Los usuarios ya existentes, creados con contraseña, reciben algo? Propuesta: nada; siguen igual (Producto).
- [ ] ¿Cuál es la ventana para agrupar avisos (R9): 2 minutos, 10, o un resumen diario? (Producto)
- [ ] Texto por defecto de las tres plantillas: ¿lo redacta el equipo o se parte de los de `paneles` adaptados? (Producto)
- [ ] Región de las funciones: la misma que Firestore del proyecto (Ingeniería, confirmar en consola).

## Fases

Sin fechas comprometidas; cada fase se puede desplegar sola.

0. **Hotfix de seguridad** (fuera de esta spec, ya): reglas de `users/{uid}`. Medio día.
1. **Infraestructura de correo:** Blaze confirmado, secreto `SMTP_PASSWORD`, carpeta `functions/` con `correo.py` portado a Firestore, `firebase.json` con `functions`, correo de prueba funcionando desde el emulador y desde producción.
2. **Alta sin contraseña:** `crearUsuario`, `reenviarAcceso`, cambios en el alta individual y la importación (R1–R4), con plantillas por defecto en código. Al cerrar esta fase, deshabilitar el registro público.
3. **Aviso de informe nuevo:** trigger `notificarAcceso` con idempotencia (R5) y registro (R7).
4. **Configuración → Correos:** editor de plantillas y vista de envíos (R6).
5. **P1:** no notificar, agrupado, prueba, login por Workspace, remitente configurable (R8–R12).

Dependencia externa: ninguna con otros equipos; todo depende de tener acceso de owner al proyecto `portal-informes-ec` y a la cuenta `notificaciones@`.
