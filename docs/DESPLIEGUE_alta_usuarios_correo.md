# Despliegue — Alta de usuarios con enlace de acceso y notificaciones por correo

**Proyecto Firebase:** `portal-informes-ec` · **Repositorio:** `araujomelogno/plataforma-informes-ec`
**Spec:** «SPEC — Alta de usuarios con enlace de acceso y notificaciones por correo» (requisitos R1–R12).

Este es el **único documento de despliegue** del cambio. Está escrito para seguirlo de arriba hacia abajo, en orden,
la primera vez que se pone en producción. Cada paso dice qué hacer, con qué comando y cómo verificar que quedó bien.

> **Tiempo estimado:** 1,5 a 2 horas la primera vez (incluye esperar que se construyan los índices y el primer
> despliegue de las funciones). **Quién:** alguien con rol **Owner** en `portal-informes-ec` y acceso a la cuenta de
> Google Workspace `notificaciones@equipos.com.uy`.

---

## Índice

0. [Qué se despliega](#0-qué-se-despliega)
1. [Decisiones previas (preguntas bloqueantes de la spec)](#1-decisiones-previas)
2. [Fase 0 — Hotfix de seguridad de las reglas (se puede hacer ya)](#2-fase-0--hotfix-de-seguridad-de-las-reglas)
3. [Preparar el entorno de despliegue](#3-preparar-el-entorno-de-despliegue)
4. [Confirmar plan Blaze, alerta de presupuesto y APIs](#4-confirmar-plan-blaze-alerta-de-presupuesto-y-apis)
5. [Elegir la región de las funciones](#5-elegir-la-región-de-las-funciones)
6. [Contraseña de aplicación de Workspace → Secret Manager](#6-contraseña-de-aplicación-de-workspace--secret-manager)
7. [Configuración no secreta (`functions/.env`) y dominios autorizados](#7-configuración-no-secreta-y-dominios-autorizados)
8. [Desplegar (en este orden)](#8-desplegar-en-este-orden)
9. [Después del despliegue: limpieza de imágenes y registro público](#9-después-del-despliegue)
10. [Verificación en producción (criterios de aceptación)](#10-verificación-en-producción)
11. [Entregabilidad: SPF, DKIM y DMARC](#11-entregabilidad-spf-dkim-y-dmarc)
12. [Operación y monitoreo](#12-operación-y-monitoreo)
13. [Rollback](#13-rollback)
14. [Desarrollo local, emuladores y pruebas](#14-desarrollo-local-emuladores-y-pruebas)
15. [Costos](#15-costos)
16. [Solución de problemas](#16-solución-de-problemas)
17. [Decisiones de implementación y diferencias con la spec](#17-decisiones-de-implementación-y-diferencias-con-la-spec)

---

## 0. Qué se despliega

Hasta ahora el portal era un `index.html` estático sin backend. Este cambio agrega un **backend mínimo de Cloud
Functions (2ª gen, Python 3.11)** en `functions/` y cambia el front, las reglas y la configuración de Firebase.

### Funciones nuevas

| Función | Tipo | Quién la llama | Qué hace | Req. |
| --- | --- | --- | --- | --- |
| `crearUsuario` | Callable | Admin (panel) | Crea la cuenta con clave aleatoria (no se guarda ni se devuelve), crea `users/{uid}`, genera el enlace de acceso y manda «Bienvenida». Si el correo falla, devuelve el enlace **una vez**. | R1, R2, R4 |
| `reenviarAcceso` | Callable | Admin (panel) | Enlace nuevo + correo («Bienvenida» si nunca ingresó, «Restablecer» si ya ingresó). Registra quién y cuándo. | R3 |
| `infoCorreo` | Callable | Admin (panel) | Plantillas por defecto, variables, cupo diario y contador de 24 h. | R4, R6, R7 |
| `enviarPrueba` | Callable | Admin (panel) | Manda una plantilla (la de pantalla) al admin, con datos de ejemplo. | R10 |
| `solicitarRestablecimiento` | Callable **pública** | Login («¿Olvidaste tu contraseña?») | Manda «Restablecer» desde `notificaciones@`. Responde igual exista o no la cuenta; tope de 3 pedidos/hora por dirección. | R11 |
| `notificarAcceso` | Trigger Firestore `userAccess/{uid}` | Firestore | Detecta informes **nuevos** en `reportIds` y encola el aviso «Nuevo informe» (idempotente). | R5, R8 |
| `despacharAvisos` | Programada (cada 1 min) | Cloud Scheduler | Manda los avisos agrupados cuando vence la ventana (por defecto 2 min). | R9 |

### Archivos que cambian

| Archivo | Cambio |
| --- | --- |
| `functions/` (nuevo) | `main.py` (las 7 funciones), `portal/` (`correo.py` portado de `paneles`, `plantillas.py`, `accesos.py`, `avisos.py`, `envio.py`, `config.py`), `requirements.txt`, `.env` (config **no** secreta), `tests/` (33 pruebas). |
| `index.html` | Alta con solo email; importación con solo emails + validación de cupo; «Reenviar acceso»; modal «mostrar una vez» con el enlace; «¿Olvidaste tu contraseña?» vía Workspace; casilla «Avisar al usuario por correo» en Permisos y en el modal del informe; nueva sección **⚙️ Configuración → Correos**; SDK `firebase-functions` 10.7.0; constante `FUNCTIONS_REGION`. Se eliminó `provisionUser()` y la llamada a `accounts:signUp`. |
| `firestore.rules` | **Hotfix**: un usuario ya no puede escribir su doc completo en `users` (solo `mfaEnrolled`); `create`/`delete` solo admin. Nuevas reglas para `config`, `mailLog`, `avisosPendientes`, `limitesCorreo`. |
| `firestore.indexes.json` (nuevo) | Índice compuesto de `mailLog` (`estado` + `creadoEn`) y políticas **TTL** sobre `expiraEn` (purga automática a 90 días). |
| `firebase.json` | Agrega `functions`, `firestore` (reglas + índices) y `emulators`. En `hosting.ignore` agrega `functions/**` y `**/*.md` para que el código del backend y los `.md` **no** se publiquen en Hosting. |
| `.gitignore` | Versiona `functions/.env` (no tiene secretos); ignora `functions/venv/` y `functions/.secret.local`. |
| `docs/manual-usuario.html` + `docs/manual-img/` | Manual actualizado (alta sin contraseña, reenviar acceso, avisos, Configuración → Correos, primer ingreso del cliente). |

### Colecciones de Firestore nuevas

| Colección / doc | Para qué | Quién lee / escribe |
| --- | --- | --- |
| `config/correos` | Plantillas editadas (`plantillas.{bienvenida,restablecer,nuevoInforme}.{asunto,cuerpo,activo}`), `remitenteNombre`, `replyTo`, `ventanaAgrupadoMin`, `actualizadoPor`, `actualizadoEn`. | Solo admins (front). |
| `mailLog/{id}` | Un registro por intento de envío: `tipo`, `destinatario`, `estado` (enviado/fallido/omitido), `motivo`, `intentos`, `duracionMs`, `disparadoPor`, `uid`, `reportId(s)`, `creadoEn`, `expiraEn`. **Nunca** guarda el enlace ni credenciales. | Lee: admins. Escribe: solo backend. TTL 90 días. |
| `avisosPendientes/{eventId}-{reportId}` | Cola de avisos «Nuevo informe» (idempotencia + agrupado). | Lee: admins. Escribe: solo backend. TTL 90 días. |
| `limitesCorreo/{sha256(email)}` | Tope de pedidos de «¿Olvidaste tu contraseña?». | Nadie desde el navegador. TTL 1 día. |

Campos nuevos en colecciones existentes: `users/{uid}.ultimoReenvio` y `users/{uid}.reenvios` (los escribe
`reenviarAcceso`); `userAccess/{uid}.options[reportId].notificar` (booleano, lo escribe el panel al habilitar).

---

## 1. Decisiones previas

La spec deja cuatro preguntas **bloqueantes**. La implementación asume las respuestas de la izquierda; si alguna
cambia, está indicado qué tocar.

| Pregunta | Asumido en el código | Si se decide otra cosa |
| --- | --- | --- |
| ¿`portal-informes-ec` está en **Blaze**? | Sí (el 2FA/TOTP ya lo exige). Se verifica en el paso 4. | Sin Blaze **no se pueden desplegar funciones**: activarlo antes. |
| ¿Alcanza un enlace que **vence a la hora**? | Sí: se usa el enlace estándar de Firebase (`generatePasswordResetLink`). Los textos por defecto dicen «vence a la hora» y explican cómo pedir otro. | Una invitación de días exige un token propio (no incluido). Si solo cambia la duración en Identity Platform, ajustar el texto de las plantillas desde Configuración → Correos. |
| ¿Contraseña de aplicación **exclusiva** o compartida con `paneles`? | **Exclusiva** (recomendado): se genera una nueva en el paso 6. | Si se comparte, usar la misma en el paso 6; revocarla rompe los dos sistemas. |
| ¿Qué **URL** va en los correos? | `https://portal-informes-ec.web.app` (`PORTAL_URL` en `functions/.env`). | Cambiar `PORTAL_URL` (paso 7) y redesplegar funciones. El dominio debe estar en **Dominios autorizados** de Authentication. |

Preguntas **no bloqueantes**, ya resueltas en la implementación:

- **R11** («¿Olvidaste tu contraseña?» por Workspace): **implementado**. Si la función no responde, el front cae
  automáticamente al correo por defecto de Firebase, así el login nunca queda sin recuperación.
- **Usuarios existentes** (creados con contraseña): **no reciben nada**, siguen igual. Si alguno necesita entrar,
  «Reenviar acceso».
- **Ventana de agrupado (R9):** **2 minutos** por defecto, editable en Configuración → Correos (0 = inmediato).
- **Textos por defecto:** redactados a partir de los de `paneles`, adaptados al portal. Editables sin deploy.
- **Región:** la de Firestore del proyecto (paso 5).

---

## 2. Fase 0 — Hotfix de seguridad de las reglas

> ⚠️ **Urgente e independiente del resto.** Con la regla vieja, **cualquier usuario cliente podía ponerse
> `role: 'admin'`** escribiendo su propio `users/{uid}` desde la consola del navegador y ver todos los informes. Esta
> fase se puede desplegar **ya**, antes que las funciones, y no rompe nada del front actual.

La regla nueva (`firestore.rules`, bloque `match /users/{uid}`):

- `read`: el propio usuario o un admin (igual que antes).
- `create` y `delete`: **solo admin** (el alta ahora la hace `crearUsuario` con el Admin SDK, que no pasa por reglas).
- `update`: admin, o el propio usuario **solo** sobre el campo `mfaEnrolled` (lo único que el portal escribe en nombre
  del cliente, al activar el 2FA).

**Desplegar solo las reglas** (desde la raíz del repo, en la rama ya mergeada):

```bash
firebase use portal-informes-ec
firebase deploy --only firestore:rules
```

> Si hasta ahora las reglas se pegaban a mano en la consola (como indica el README), este comando las reemplaza por
> las de `firestore.rules`, que pasa a ser la fuente de verdad.

**Verificar** (en la consola del navegador, logueado como un usuario **cliente** de prueba, en el portal):

```js
await db.collection('users').doc(auth.currentUser.uid).update({ role: 'admin' })
// → debe fallar con "Missing or insufficient permissions"
```

Y verificar que un admin sigue pudiendo cambiar roles, activar 2FA de un usuario y borrar usuarios desde el panel.

> **Nota sobre el alta vieja:** mientras el front viejo siga publicado, el alta individual escribe `users/{uid}`
> **como admin** (sigue funcionando). Lo que deja de funcionar es que un cliente se cree o se modifique su propio
> documento.

---

## 3. Preparar el entorno de despliegue

Requisitos en la máquina desde la que se despliega:

| Herramienta | Versión | Verificar |
| --- | --- | --- |
| Firebase CLI | ≥ 13.35 (soporta `functions:artifacts:setpolicy` y TTL en `firestore.indexes.json`) | `firebase --version` |
| Python | **3.11** (el `predeploy` crea `functions/venv` con `python3.11`) | `python3.11 --version` |
| gcloud (opcional, recomendado) | cualquiera reciente | `gcloud --version` |

```bash
npm install -g firebase-tools        # o actualizar: npm i -g firebase-tools@latest
firebase login
firebase use portal-informes-ec
gcloud auth login && gcloud config set project portal-informes-ec   # opcional
```

Traer el código:

```bash
git checkout main && git pull          # con el PR ya mergeado
```

---

## 4. Confirmar plan Blaze, alerta de presupuesto y APIs

1. **Plan Blaze.** Firebase Console → ⚙️ *Usage and billing* → *Details & settings*: debe decir **Blaze (pay as you
   go)**. Si dice Spark, activar Blaze (requiere cuenta de facturación).
2. **Alerta de presupuesto en US$5/mes** (medida de control de la spec). Google Cloud Console → *Billing* →
   *Budgets & alerts* → *Create budget*: alcance = proyecto `portal-informes-ec`, monto US$5, alertas al 50%, 90% y 100%
   a los responsables.
3. **APIs.** El primer `firebase deploy --only functions` habilita solas las que faltan (Cloud Functions, Cloud Run,
   Cloud Build, Artifact Registry, Eventarc, Pub/Sub, Cloud Scheduler, Secret Manager). Si se prefiere hacerlo antes:

   ```bash
   gcloud services enable cloudfunctions.googleapis.com run.googleapis.com cloudbuild.googleapis.com \
     artifactregistry.googleapis.com eventarc.googleapis.com pubsub.googleapis.com \
     cloudscheduler.googleapis.com secretmanager.googleapis.com --project portal-informes-ec
   ```

---

## 5. Elegir la región de las funciones

El trigger `notificarAcceso` escucha a Firestore, así que **las funciones van en la región de la base**. Hay que poner
el **mismo valor en dos lugares**.

1. Averiguar la ubicación de Firestore:

   ```bash
   gcloud firestore databases describe --database="(default)" --project portal-informes-ec \
     --format="value(locationId)"
   ```

   (o Firebase Console → Firestore → pestaña *Settings* / *Detalles de la base*.)

2. Traducir a región de funciones:

   | `locationId` de Firestore | `REGION` a usar |
   | --- | --- |
   | `nam5` (multi-región EE. UU.) | `us-central1` |
   | `eur3` (multi-región Europa) | `europe-west1` |
   | una región (ej. `us-east1`, `southamerica-east1`) | **esa misma** |

3. Escribirla en:
   - `functions/.env` → `REGION=<región>`
   - `index.html` → `const FUNCTIONS_REGION = '<región>';` (buscar `FUNCTIONS_REGION`, cerca de `firebaseConfig`).

   El valor por defecto en el repo es **`us-central1`**. Si la base está en otra región, cambiar ambos, commitear y
   seguir.

> Si los dos valores no coinciden, el panel muestra «No se pudo contactar al servidor» al crear un usuario (el
> navegador llama a una URL de función que no existe).

---

## 6. Contraseña de aplicación de Workspace → Secret Manager

### 6.1 Generar una contraseña de aplicación **nueva y exclusiva**

1. Iniciar sesión en <https://myaccount.google.com> como **`notificaciones@equipos.com.uy`**.
2. La cuenta necesita **verificación en dos pasos** activa (*Seguridad* → *Verificación en 2 pasos*). Si el
   administrador de Workspace la tiene deshabilitada por política, pedirle que la permita para esta cuenta.
3. Ir a <https://myaccount.google.com/apppasswords>, nombre: **`portal-informes-ec`** → *Crear*.
4. Copiar los 16 caracteres (sin espacios). **No pegarla en chats, tickets, el repo ni este documento.**

### 6.2 Revocar la contraseña expuesta (seguridad)

La spec indica que la contraseña que se compartió en la conversación donde se pidió el cambio **debe considerarse
expuesta**:

1. En <https://myaccount.google.com/apppasswords> de `notificaciones@`, **revocar** esa contraseña.
2. Si era la misma que usa `paneles`, generar otra para `paneles` y actualizarla allá
   (`firebase functions:secrets:set SMTP_PASSWORD` en ese proyecto + redesplegar sus funciones). Hacerlo en la misma
   ventana de tiempo para no dejar a `paneles` sin correo.

### 6.3 Cargarla en Secret Manager

```bash
firebase functions:secrets:set SMTP_PASSWORD --project portal-informes-ec
# pega la contraseña cuando la pide (no queda en el historial de la terminal)
```

Verificar que existe (sin mostrar el valor):

```bash
firebase functions:secrets:get SMTP_PASSWORD --project portal-informes-ec
```

> Las funciones que mandan correo declaran `secrets=["SMTP_PASSWORD"]`; Firebase les da acceso automáticamente al
> desplegar. La contraseña **nunca** se loguea, ni se devuelve, ni aparece en `mailLog` ni en mensajes de error.

**Rotación futura:** `firebase functions:secrets:set SMTP_PASSWORD` con la nueva + `firebase deploy --only functions`
(las funciones toman la versión `latest` al desplegarse) y luego revocar la vieja en Google.

---

## 7. Configuración no secreta y dominios autorizados

### 7.1 `functions/.env`

Está versionado (no tiene secretos). Revisar los valores:

| Variable | Valor por defecto | Qué es |
| --- | --- | --- |
| `REGION` | `us-central1` | Región de las funciones (paso 5). |
| `PORTAL_URL` | `https://portal-informes-ec.web.app` | URL del portal en los correos (`{{url_portal}}`) y a donde vuelve el usuario tras fijar su contraseña. |
| `SMTP_USUARIO` | `notificaciones@equipos.com.uy` | Cuenta de Workspace que autentica y envía. |
| `SMTP_HOST` / `SMTP_PORT` | `smtp.gmail.com` / `587` | SMTP de Workspace con STARTTLS (465 = SSL también soportado). |
| `CORREO_CUPO_DIARIO` | `1500` | Correos por día que puede usar **este** portal. Workspace corta en 2.000/día por cuenta y `notificaciones@` se comparte con `paneles`, cuyo consumo no se ve desde acá: los 500 restantes quedan para `paneles`. Ajustar según el uso real de `paneles`. |
| `CORREO_DIAS_REGISTRO` | `90` | Días que se conserva `mailLog` (TTL). |
| `RESTABLECER_POR_HORA` | `3` | Tope de «¿Olvidaste tu contraseña?» por dirección y por hora. |

### 7.2 Dominios autorizados

Firebase Console → Authentication → *Settings* → **Authorized domains**: debe incluir el dominio de `PORTAL_URL`
(`portal-informes-ec.web.app` ya viene por defecto). Si se usa un dominio propio, agregarlo; si no, la generación del
enlace falla y el alta informa «No se pudo generar el enlace de acceso».

### 7.3 Idioma de los correos de Firebase (fallback)

Los correos que manda **Firebase** (solo en el fallback de «¿Olvidaste tu contraseña?») ya salen en español
(`auth.languageCode = 'es'`). La página de Firebase donde el usuario escribe la contraseña nueva respeta el parámetro
`lang` del enlace; opcionalmente, en Authentication → *Templates* → *Template language*, elegir **Español**.

---

## 8. Desplegar (en este orden)

> **El orden importa:** el front nuevo depende de las funciones. Si se publica el `index.html` antes de que existan
> las funciones, el alta de usuarios queda rota hasta que se desplieguen.

### 8.1 Reglas e índices de Firestore

```bash
firebase deploy --only firestore:rules,firestore:indexes --project portal-informes-ec
```

- Verificar en Firebase Console → Firestore → *Indexes*: índice compuesto `mailLog` (`estado` ↑, `creadoEn` ↓) en
  estado **Enabled** (tarda unos minutos).
- Verificar en Firestore → *Indexes* → pestaña *TTL* (o *Time-to-live*): políticas sobre `expiraEn` para `mailLog`,
  `avisosPendientes` y `limitesCorreo`.
- Si la CLI no aplicara las políticas TTL, crearlas a mano:

  ```bash
  for c in mailLog avisosPendientes limitesCorreo; do
    gcloud firestore fields ttls update expiraEn --collection-group=$c --enable-ttl --project portal-informes-ec
  done
  ```

### 8.2 Cloud Functions

```bash
firebase deploy --only functions --project portal-informes-ec
```

- El `predeploy` crea `functions/venv` con Python 3.11 e instala `requirements.txt`.
- La primera vez tarda ~5–10 minutos. Si pregunta por una **política de limpieza de imágenes**, responder que sí con
  1 día (o hacerlo en el paso 9.1).
- Al terminar deben figurar las 7 funciones:

  ```bash
  firebase functions:list --project portal-informes-ec
  # crearUsuario, reenviarAcceso, infoCorreo, enviarPrueba, solicitarRestablecimiento,
  # notificarAcceso (firestore), despacharAvisos (scheduled)
  ```

- **Primer deploy de un trigger de Firestore 2ª gen:** si falla con un error de permisos del *Eventarc Service Agent*
  («Permission denied while using the Eventarc Service Agent»), es la propagación inicial de permisos de Google:
  esperar 5 minutos y repetir el mismo comando.
- **Callables públicas:** las callables se despliegan con invocación pública (`allUsers` en Cloud Run), que es lo
  normal: la autorización la hace el propio código (verifica el token y el rol leyendo `users/{uid}`). Si la
  organización de GCP tiene la política *Domain restricted sharing* y el deploy no puede dar acceso público, hay que
  pedir una excepción para este proyecto.

### 8.3 Hosting (el front)

```bash
firebase deploy --only hosting --project portal-informes-ec
```

> No usar `firebase deploy` **sin** `--only` si no se quiere redesplegar todo: desde este cambio `firebase.json`
> incluye funciones y Firestore.

> **Previews de PR (GitHub Action):** los canales de preview usan el mismo proyecto y por lo tanto las mismas
> funciones de producción. Antes del primer deploy de funciones, el alta de usuarios en un preview no funciona.

### 8.4 Comprobación rápida

1. Abrir el portal **en una ventana nueva** (o recargar con Ctrl/Cmd+Shift+R para no usar caché).
2. Entrar como admin → debe aparecer **⚙️ Configuración → Correos** en el menú.
3. En Configuración → Correos debe decir **«✅ Credencial SMTP configurada»** y el contador de 24 h.
4. En la plantilla «Bienvenida», tocar **✉️ Enviarme una prueba** → debe llegar a la casilla del admin, desde
   *Equipos Consultores &lt;notificaciones@equipos.com.uy&gt;*, con «[PRUEBA]» en el asunto. Revisar que **no** caiga en
   spam (si cae, ver paso 11).

---

## 9. Después del despliegue

### 9.1 Política de limpieza de imágenes (control de costo)

Cada deploy deja imágenes de contenedor en Artifact Registry (US$0,10 por GB-mes pasado el 0,5 GB gratis):

```bash
firebase functions:artifacts:setpolicy --location <REGION> --days 1 --project portal-informes-ec
```

### 9.2 Deshabilitar el registro público de cuentas (R1 / Seguridad P0)

Con las altas pasando por `crearUsuario`, ya **no hace falta** que la `apiKey` pública permita crear cuentas
(`accounts:signUp`). Hacerlo **recién después** de comprobar que el alta desde el panel funciona (paso 10, prueba 1):

1. Firebase Console → Authentication → *Settings* → **User actions**.
2. Desmarcar **«Enable create (sign-up)»** (*Permitir la creación de cuentas*) → *Save*.

Esto no afecta a `crearUsuario` (usa el Admin SDK) ni al login, el 2FA o el restablecimiento de contraseñas.

**Verificar** que el alta pública quedó cerrada (debe responder `ADMIN_ONLY_OPERATION` u `OPERATION_NOT_ALLOWED`):

```bash
curl -s -X POST "https://identitytoolkit.googleapis.com/v1/accounts:signUp?key=AIzaSyCNYTImSJphSSfcfPuMsgKWCFy26VH2fBk" \
  -H 'Content-Type: application/json' -d '{"email":"prueba-registro@example.com","password":"x12345678"}'
```

> La `apiKey` del portal es pública por diseño (va en el `index.html`); no es un secreto.

### 9.3 `scripts/update_report.py`

No cambia. Sigue autenticándose con un usuario admin por email/contraseña. Si ese usuario de servicio se crea a
partir de ahora, se crea con «Crear usuario» (recibe el enlace, fija su contraseña) y luego se le da rol admin.

---

## 10. Verificación en producción

Usar una casilla de prueba propia (por ejemplo un alias `+prueba` de Gmail: `tu.nombre+portal1@gmail.com`). Marcar cada
punto. Entre paréntesis, el requisito de la spec.

**Alta y acceso**

1. ☐ (R1) Usuarios → Crear nuevo usuario: el formulario pide **solo email** y ya no aparecen «Contraseña temporal» ni el
   texto de «Firebase console». Crear `tu.nombre+portal1@…` → mensaje «✅ Usuario creado. Le enviamos un correo…».
2. ☐ (R1) Llega el correo «Tu acceso al Portal de Informes…» desde `notificaciones@equipos.com.uy`; el enlace lleva a
   fijar la contraseña y después al portal; se puede ingresar.
3. ☐ (R1) En Firestore, `users/{uid}` tiene `email`, `role: 'user'`, `createdAt`, `creadoPor`, `creadoPorUid`.
   En `mailLog` hay un registro `bienvenida` / `enviado` **sin** el enlace.
4. ☐ (R1) Crear de nuevo el mismo email → «Ya existía una cuenta…» con botón **📨 Reenviar acceso**; no llega correo
   nuevo y la contraseña que eligió sigue funcionando.
5. ☐ (R1) Logueado como **cliente**, en la consola del navegador:
   `await callFn('crearUsuario', {email: 'x@example.com'})` → error `permission-denied`, no se crea nada.
6. ☐ (R1) En *Cloud Logging* (Logs Explorer, recurso Cloud Run de `crearusuario`), buscar el email de prueba: no
   aparecen contraseñas ni enlaces.
7. ☐ (R3) **📨 Reenviar acceso** sobre el usuario de prueba → llega «Elegí una contraseña nueva…» (ya ingresó) y
   `users/{uid}` tiene `ultimoReenvio` (por quién, cuándo) y `reenvios: 1`.
8. ☐ (R11) En el login, «¿Olvidaste tu contraseña?» con el email de prueba → llega desde `notificaciones@`. Con un
   email inexistente → el mismo mensaje en pantalla y **no** sale correo.

**Correo como comodidad (R2)** — opcional, en una ventana de mantenimiento corta:

9. ☐ Cargar temporalmente una contraseña inválida: `firebase functions:secrets:set SMTP_PASSWORD` (valor `invalida`)
   y `firebase deploy --only functions:crearUsuario`. Crear un usuario → se crea igual; se abre el modal con el
   enlace, el botón **Copiar** y el motivo «Workspace rechazó la credencial (535)…», sin la contraseña. Restaurar la
   contraseña buena y redesplegar **todas** las funciones (`firebase deploy --only functions`). Borrar la versión
   inválida del secreto: `firebase functions:secrets:prune`.

**Importación (R4)**

10. ☐ Importar un `.csv` con `email,password` en el encabezado, 2 emails nuevos, 1 existente, 1 inválido, con algo en
    la 2ª columna → resumen con las 4 categorías y el aviso «se ignoraron las contraseñas».
11. ☐ Bajar temporalmente `CORREO_CUPO_DIARIO=1` en `functions/.env`, redesplegar `infoCorreo`
    (`firebase deploy --only functions:infoCorreo`) e importar 2 emails → se rechaza antes de empezar con el mensaje de
    cupo. Volver el valor a 1500 y redesplegar.

**Aviso de informe nuevo (R5, R8, R9)**

12. ☐ (R5) Permisos → usuario de prueba → habilitar un informe → a los ~2–3 minutos llega **un** correo «Nuevo
    material…» con nombre, carpeta y enlace al portal.
13. ☐ (R5) Hacer lo mismo desde Informes → 👥 Usuarios → llega **un** correo.
14. ☐ (R5) Quitar el acceso, cambiar una protección o la caducidad, o volver a marcar un informe que ya tenía → no
    llega nada.
15. ☐ (R5) A un usuario **admin** no le llegan avisos (los admins no figuran en Permisos; se puede probar dando rol
    admin al usuario de prueba y habilitándole un informe desde el modal del informe — no aparece en la lista).
16. ☐ (R8) Desmarcar «📧 Avisar al usuario por correo» y habilitar un informe → no llega correo y en «Últimos envíos»
    no aparece intento.
17. ☐ (R9) Habilitar 5 informes en menos de 30 segundos → llega **1** correo con los 5 nombres.
18. ☐ (R5) Tildar y destildar un informe en pocos segundos → no llega correo (queda un registro «omitido»).

**Configuración → Correos (R6, R7, R10, R12)**

19. ☐ (R6) Cambiar el asunto de «Nuevo informe», guardar, habilitar un informe → el correo usa el asunto nuevo (sin
    deploy).
20. ☐ (R6) En «Bienvenida», borrar `{{enlace}}` → se marca el error y **Guardar** queda deshabilitado. Escribir
    `{{nombre_informe}}` → «Variables desconocidas…».
21. ☐ (R6) «↺ Restaurar texto por defecto» vuelve al texto del código.
22. ☐ (R6) Logueado como cliente: `await db.collection('config').doc('correos').get()` → *permission denied*.
23. ☐ (R7) «Últimos envíos» lista los envíos de las pruebas; el filtro «Solo fallidos» funciona; se ve el contador de
    24 h.
24. ☐ (R10) «✉️ Enviarme una prueba» en cada plantilla → llega al admin con «[PRUEBA]».
25. ☐ (R12) Cambiar el nombre visible del remitente y el Reply-To → la siguiente prueba llega con ese nombre y al
    responder va a la dirección configurada.

**Seguridad**

26. ☐ Hotfix de reglas verificado (paso 2) y registro público cerrado (paso 9.2).
27. ☐ La contraseña expuesta fue revocada (paso 6.2).

Al terminar, borrar los usuarios de prueba (🗑 Borrar en el panel y su credencial en Authentication).

---

## 11. Entregabilidad: SPF, DKIM y DMARC

Debería estar resuelto por `paneles` (misma cuenta). Verificar:

```bash
dig +short TXT equipos.com.uy | grep -i spf          # debe incluir include:_spf.google.com
dig +short TXT google._domainkey.equipos.com.uy      # clave DKIM de Google (selector "google" por defecto)
dig +short TXT _dmarc.equipos.com.uy                 # política DMARC (p=none/quarantine/reject)
```

Y en Gmail, en el correo de prueba → ⋮ → *Mostrar original*: `SPF: PASS`, `DKIM: PASS`, `DMARC: PASS`.
Si DKIM no está, activarlo en la Consola de administración de Workspace → *Apps* → *Google Workspace* → *Gmail* →
*Autenticar correo electrónico*.

---

## 12. Operación y monitoreo

- **Registro de envíos:** Configuración → Correos → «Últimos envíos» (filtrar «Solo fallidos»). Meta de la spec:
  ≥ 98% enviados.
- **Cupo diario:** el contador «Últimas 24 h» vs. `CORREO_CUPO_DIARIO`. Recordar que `paneles` usa la misma cuenta.
- **Logs de las funciones:**

  ```bash
  firebase functions:log --project portal-informes-ec
  firebase functions:log --only notificarAcceso --project portal-informes-ec
  ```

- **Motivos frecuentes de «fallido»** y qué hacer:

  | Motivo en `mailLog` | Causa | Acción |
  | --- | --- | --- |
  | «Workspace rechazó la credencial (535)…» | Contraseña de aplicación revocada/incorrecta. | Paso 6 (nueva contraseña) + redesplegar funciones. |
  | «Falta SMTP_PASSWORD…» | Secreto no cargado o función desplegada sin él. | Paso 6.3 + redesplegar. |
  | «El servidor respondió 550/554…» o «…Daily user sending limit exceeded» | Tope diario de Workspace alcanzado (entre el portal y `paneles`). | Esperar 24 h; reenviar accesos al día siguiente. |
  | «El servidor rechazó el destinatario…» | Dirección inexistente. | Corregir el email del usuario. |
  | «No se pudo generar el enlace de acceso…» | Dominio de `PORTAL_URL` no autorizado. | Paso 7.2. |

- **Métricas de éxito de la spec** (a las 2 semanas y a los 2 meses): se calculan con `mailLog` (enviados/total),
  `users.createdAt` vs. primera `sessions` (ingreso en 7 días), `users.reenvios` (altas que necesitaron reenvío) y
  `sessions` posteriores al aviso.

---

## 13. Rollback

Cada pieza se puede volver atrás por separado.

| Qué | Cómo |
| --- | --- |
| **Front** | Firebase Console → Hosting → *Release history* → versión anterior → *Rollback*. El front viejo vuelve a crear usuarios con contraseña vía `accounts:signUp`: **si se hizo el paso 9.2, primero volver a habilitar «Enable create (sign-up)»** o el alta vieja fallará. |
| **Avisos de informe** | Sin deploy: Configuración → Correos → «Nuevo informe» → apagar «Enviar este correo». Para sacar el trigger: `firebase functions:delete notificarAcceso despacharAvisos --region <REGION>`. |
| **Funciones** | `git revert` del cambio en `functions/` y `firebase deploy --only functions`, o borrar funciones puntuales con `firebase functions:delete <nombre> --region <REGION>`. |
| **Reglas** | **No** volver a la regla vieja de `users` (es la vulnerabilidad). Si algo del panel se rompiera por permisos, corregir la regla puntual. Las reglas anteriores se pueden ver en Firestore → *Rules* → historial. |
| **Plantillas** | «↺ Restaurar texto por defecto» en cada plantilla, o borrar el doc `config/correos`. |
| **Secreto** | `firebase functions:secrets:set SMTP_PASSWORD` con el valor anterior + redesplegar funciones. |

---

## 14. Desarrollo local, emuladores y pruebas

### Pruebas del backend

```bash
cd functions
python3.11 -m venv venv && venv/bin/pip install -r requirements.txt pytest
# Lógica pura (plantillas, SMTP con conexión falsa): corre siempre
venv/bin/python -m pytest -q
# Todo, incluido alta/reenvío/avisos contra los emuladores de Firestore y Auth:
cd .. && firebase emulators:exec --only firestore,auth --project demo-portal \
  "cd functions && venv/bin/python -m pytest -q"
```

Resultado esperado: **33 passed**. Cubren, entre otros: alta + ficha + bienvenida; `permission-denied` para no
admins; email existente sin tocar la clave; SMTP caído → alta hecha + enlace devuelto y no guardado; reenvío con
registro; tope de «¿Olvidaste…?»; trigger idempotente; quitar/cambiar opciones/reasignar no avisa; admins no reciben;
«no notificar»; 5 informes → 1 correo; tildar/destildar → nada; plantilla apagada → omitido; fallo de envío no
revierte el permiso; validación y armado de plantillas.

### El portal completo contra los emuladores

```bash
# functions/.secret.local (no se versiona) con:  SMTP_PASSWORD=
firebase emulators:start --only auth,firestore,functions,hosting --project portal-informes-ec
# abrir http://localhost:5000/?emu=1
```

Con `?emu=1` (solo en `localhost`/`127.0.0.1`) el portal usa los emuladores en vez del proyecto real. Hace falta
sembrar un admin (cuenta en el emulador de Auth + doc `users/{uid}` con `role: 'admin'`). Sin `SMTP_PASSWORD` los
correos fallan a propósito y se ve el flujo de «mostrar el enlace una vez». La función programada `despacharAvisos` no
corre en el emulador (no hay Pub/Sub): para ver los avisos usar `ventanaAgrupadoMin: 0` en `config/correos`, que manda
en el momento. Con un `projectId` que no empieza con `demo-`, el emulador de funciones necesita credenciales de
aplicación (`gcloud auth application-default login`).

---

## 15. Costos

Estimado de la spec, confirmado con el diseño final: **US$0 a US$0,50 por mes**.

| Ítem | Uso estimado | Costo |
| --- | --- | --- |
| Cloud Functions 2ª gen | ≈3.000 invocaciones de las callables/trigger + 43.200 de `despacharAvisos` (1 por minuto; la mayoría no encuentra nada y termina en milisegundos). 256 MB, CPU tipo gen1. | Dentro del tramo gratis (2 M invocaciones) → US$0 |
| Cloud Scheduler | 1 job (`despacharAvisos`). 3 jobs gratis por cuenta de facturación (compartidos con `paneles`). | US$0 a US$0,10 |
| Secret Manager | 1 secreto; accesos al arrancar instancias. | US$0 a US$0,06 |
| Firestore | `mailLog`, `avisosPendientes`, `config`; < 200 escrituras/día + 1 lectura/minuto del despacho. TTL sin costo extra de borrado significativo. | US$0 |
| Artifact Registry | Imágenes de funciones, con política de limpieza (paso 9.1). | US$0 a US$0,20 |
| Cloud Build | ≈10 deploys de 3–5 min. | US$0 |
| SMTP Workspace | Licencia de `notificaciones@` ya existente. | US$0 |

`max_instances=10` por función acota el costo ante un pico o un abuso de la callable pública.

---

## 16. Solución de problemas

| Síntoma | Causa probable | Solución |
| --- | --- | --- |
| «No se pudo contactar al servidor» al crear un usuario | Funciones no desplegadas, o `FUNCTIONS_REGION` (index.html) ≠ `REGION` (functions/.env). | Paso 5 y 8.2. Ver en la consola del navegador la URL de la función que falla. |
| «Solo un administrador puede hacer esto» siendo admin | El doc `users/{uid}` del admin no tiene `role: 'admin'`. | Corregir en Firestore. |
| Siempre aparece el modal con el enlace (el correo nunca sale) | Secreto faltante o inválido. El motivo está en el modal y en «Últimos envíos». | Paso 6 + `firebase deploy --only functions`. |
| Configuración → Correos dice «⚠️ Falta la credencial SMTP» | `SMTP_PASSWORD` vacío en la función `infoCorreo`. | Paso 6.3 + redesplegar. |
| «Últimos envíos» da error de índice | El índice compuesto de `mailLog` todavía se está construyendo. | Esperar a que figure *Enabled* (paso 8.1). |
| Los avisos de informe no llegan | `despacharAvisos` no corre (Cloud Scheduler deshabilitado), plantilla «Nuevo informe» apagada, casilla «Avisar» desmarcada o el usuario es admin. | `firebase functions:log --only despacharAvisos`; revisar en GCP → Cloud Scheduler que el job esté *Enabled*; revisar `mailLog` (estado «omitido» + motivo). |
| Deploy de `notificarAcceso` falla con permisos de Eventarc | Propagación inicial de permisos. | Esperar 5 min y repetir. |
| Deploy falla: «Cannot find python3.11» | El `predeploy` necesita Python 3.11. | Instalarlo (`brew install python@3.11`, `apt install python3.11 python3.11-venv`). |
| El enlace del correo lleva a una página de error de Firebase | El enlace venció (1 h) o ya se usó. | «¿Olvidaste tu contraseña?» o «Reenviar acceso». |
| Correos en spam | SPF/DKIM/DMARC. | Paso 11. |
| El cliente dice que no puede crear su usuario «registrándose» | Correcto: el registro público está cerrado (paso 9.2). | Darlo de alta desde el panel. |

---

## 17. Decisiones de implementación y diferencias con la spec

- **Idempotencia del trigger.** La spec propone crear `mailLog/{eventId}-{reportId}` con `create()`. Como el aviso se
  **agrupa** (R9), el marcador de idempotencia es `avisosPendientes/{eventId}-{reportId}` (también con `create()`, que
  falla si existe): un reintento del trigger no encola dos veces. El despacho reclama los pendientes en una
  **transacción** (`pendiente` → `procesando`), así el trigger y la función programada nunca mandan el mismo grupo dos
  veces. `mailLog` registra cada envío real con un id automático.
- **Agrupado (R9).** El correo sale cuando pasa la ventana (2 min por defecto) **sin nuevos informes** para ese
  usuario, con un máximo de 5 ventanas de espera. Al despachar se relee `userAccess`: si el informe se quitó (o se marcó
  «no avisar») antes del envío, no se avisa. Ventaja adicional: la caducidad (`{{vence}}`), que el admin suele cargar
  un instante después de habilitar, ya está disponible cuando sale el correo.
- **Purga a 90 días (R7)** con **TTL de Firestore** sobre `expiraEn`, en lugar de un job de borrado: sin código ni
  Cloud Scheduler extra.
- **Cupo diario (R4).** Solo se ve el consumo de este portal; `CORREO_CUPO_DIARIO` (1.500) deja margen para `paneles`.
  La validación es conservadora: cuenta todas las filas válidas del archivo, aunque algunas ya existan.
- **«Restablecer» también exige `{{enlace}}`** (la spec lo pide solo para «Bienvenida»): sin el enlace el correo no
  sirve para nada.
- **Interruptor «Enviar este correo»** solo en «Nuevo informe», como pide la spec. Las plantillas de acceso no se
  pueden apagar (dejarían altas sin forma de entrar).
- **Reenviar acceso** elige la plantilla sola: «Bienvenida» si la persona nunca ingresó, «Restablecer» si ya ingresó.
- **Alta de un email con cuenta en Auth pero sin ficha** (usuario borrado desde el panel, que conserva su credencial):
  no se crea otra cuenta ni se toca la clave, pero se **recrea `users/{uid}`** para que «Reenviar acceso» le sirva.
- **«¿Olvidaste tu contraseña?» (R11)**: responde siempre igual; solo envía si la cuenta existe **y** tiene ficha en
  el portal; tope de 3 por hora por dirección (sin registrar en `mailLog` los pedidos de direcciones desconocidas, para
  no acumular datos de terceros). Si la función no responde, el front usa el correo de Firebase.
- **Variables y textos por defecto en un solo lugar**: el backend (`functions/portal/plantillas.py`) se los pasa al
  panel con `infoCorreo`, así el editor, la vista previa y el envío no se desincronizan.
- **Regla de líneas vacías**: si una línea de la plantilla tiene variables y todas quedan vacías, se omite (evita
  «Carpeta: » sin valor).
- **Desarrollo local**: el front acepta `?emu=1` **solo en localhost** para usar los emuladores. No tiene efecto en
  producción.
