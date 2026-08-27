# Correos automáticos con Trigger Email

Este documento explica cómo quedan armados los correos automáticos del portal
enviados con la extensión Trigger Email y cómo desplegarlos.

Correos incluidos en esta etapa:

1. **Informe nuevo** — aviso *"tenés un informe nuevo disponible"* cuando se le
   concede acceso a un informe (función `notifyNewReportAccess`).
2. **Activación de cuenta** — al crear un usuario, se le envía su **usuario
   (email) + un enlace seguro para elegir su propia contraseña** (función
   `sendAccountActivation`). **Nunca viaja una contraseña por correo.**

> Los correos de *restablecer contraseña* (autoservicio) y *verificación de
> email* del login **siguen saliendo por Firebase Authentication** (sin
> cambios). Migrarlos también a Trigger Email es una etapa posterior que reusa
> exactamente la misma mecánica que la activación de cuenta.

## Cómo funciona

### Informe nuevo (`notifyNewReportAccess`)

1. Un admin le concede a un usuario acceso a un informe. En el portal eso agrega
   el id del informe al array `reportIds` del documento `userAccess/{uid}`
   (un documento por usuario; el acceso se agrega/quita del array).
2. La función escucha toda escritura de `userAccess/{uid}`, compara `reportIds`
   antes/después y detecta los informes **recién agregados**.
3. Busca el email en `users/{uid}` y el nombre en `reports/{id}`, arma el HTML y
   **escribe un documento en la colección `mail`**.

### Activación de cuenta (`sendAccountActivation`)

1. El admin crea un usuario (formulario o import de Excel). Eso crea el
   documento `users/{uid}` (con `email` y `role: 'user'`).
2. La función escucha la **creación** de `users/{uid}`, genera con el Admin SDK
   un enlace de "elegí tu contraseña" (`generatePasswordResetLink`) y **escribe
   el correo de activación en `mail`**. No hace falta ningún cambio en el
   front-end: el alta sigue igual.
3. A los documentos con `role: 'admin'` **no** se les envía activación (los
   admins se crean a mano en la consola).

En ambos casos, la extensión **Trigger Email from Firestore**
(`firestore-send-email`) toma el documento de `mail` y envía el correo por el
**SMTP de Google Workspace**.

```
  Admin concede acceso ─▶ userAccess/{uid}.reportIds += id   (onWrite)  ┐
  Admin crea usuario  ─▶ users/{uid} creado                  (onCreate) ┤
                                                                        ▼
                                        Cloud Function → escribe { to, message }
                                                                        ▼
                        colección `mail` ─▶ extensión Trigger Email ─▶ 📧 SMTP Google Workspace
```

La colección `mail` está **cerrada a los clientes** en `firestore.rules`
(`allow read, write: if false`): sólo las funciones (Admin SDK) escriben ahí.
Así nadie puede encolar correos arbitrarios desde el navegador.

## Requisitos previos

- **Plan Blaze** (pago por uso) en el proyecto `portal-informes-ec`. Las
  Extensions y las Cloud Functions lo exigen. (Ya es necesario para la MFA.)
- **Firebase CLI** actualizado: `npm i -g firebase-tools` y `firebase login`.
- Una **casilla/alias de envío** del dominio `equipos.com.uy` (p. ej.
  `no-responder@equipos.com.uy`) habilitada para enviar por SMTP.

## Paso 1 — Elegir el método SMTP de Google Workspace

Hay dos opciones; elegí una:

### Opción A — SMTP relay de Google Workspace (recomendada)
Sirve para enviar como cualquier dirección del dominio, sin App Password.
1. En **Google Admin** (admin.google.com) → **Apps → Google Workspace → Gmail →
   Enrutamiento → Servicio de retransmisión SMTP (SMTP relay)**.
2. Creá una regla permitiendo el envío. Para autenticación por IP puede ser
   necesario fijar el rango de salida; lo más simple es **exigir autenticación
   SMTP** y usar una cuenta del dominio.
3. Cadena de conexión: `smtps://smtp-relay.gmail.com:465`
   (con autenticación SMTP, agregá el usuario: ver Paso 3).

### Opción B — Cuenta Gmail del dominio + App Password
1. La cuenta (p. ej. `no-responder@equipos.com.uy`) debe tener **verificación en
   2 pasos** activada.
2. Generá una **App Password** en la cuenta (Seguridad → Contraseñas de
   aplicaciones).
3. Cadena de conexión:
   `smtps://no-responder%40equipos.com.uy:APP_PASSWORD@smtp.gmail.com:465`
   (el `@` del usuario va codificado como `%40`).

> Recomendación de entregabilidad: configurá **SPF, DKIM y DMARC** del dominio
> `equipos.com.uy` para que los correos no caigan en spam.

## Paso 2 — Instalar la extensión Trigger Email

Los parámetros **no secretos** ya están versionados en
`extensions/firestore-send-email.env` (colección `mail`, remitente por defecto,
TTL, etc.). Instalá la extensión:

```bash
firebase ext:install firebase/firestore-send-email --project=portal-informes-ec
```

Durante la instalación, cuando pida los parámetros, tomará los valores del
archivo `.env` si desplegás con `firebase deploy --only extensions`. El único
valor **secreto** es la cadena de conexión SMTP:

- **SMTP connection URI** → pegá la cadena del Paso 1 (Opción A o B).
  Si tu proveedor requiere usuario/clave por separado, la extensión también
  ofrece los campos `SMTP_PASSWORD` (guardado en Secret Manager).

Verificá que el parámetro **"Email documents collection"** quede en `mail`
(coincide con `MAIL_COLLECTION` de la función).

**Región (`DATABASE_REGION`):** el instalador te va a preguntar dónde está tu
base de Firestore. Poné exactamente la ubicación real (Firebase Console →
Firestore Database, arriba figura la región, p. ej. `nam5`, `us-central` o
`southamerica-east1`). Si no coincide, la extensión no se dispara.

## Paso 3 — Configurar y desplegar las Cloud Functions

Las funciones usan dos parámetros con valores por defecto (no hace falta
tocarlos si son correctos):

- `PORTAL_URL` (default `https://portal-informes-ec.web.app`): la URL del portal
  para el botón de los correos y como *continue URL* del enlace de activación.
  **Cambialo si usás un dominio propio.**
- `MAIL_COLLECTION` (default `mail`): debe coincidir con la extensión.

> **Dominios autorizados (para la activación):** el `PORTAL_URL` que uses como
> *continue URL* debe estar en Firebase Console → Authentication → Settings →
> **Authorized domains**. Los dominios `*.web.app` y `*.firebaseapp.com` del
> proyecto ya vienen autorizados; si usás un dominio propio, agregalo ahí. (Si
> no lo está, la función igual manda la activación: reintenta generando el
> enlace sin *continue URL*.)

Instalá dependencias y desplegá:

```bash
cd functions
npm install
cd ..
firebase deploy --only functions,firestore:rules,extensions --project=portal-informes-ec
```

Para fijar `PORTAL_URL` a un dominio propio, tenés dos opciones:

- Editar el valor `default` en `functions/index.js` (línea del `defineString('PORTAL_URL', …)`), **o**
- Crear un archivo `functions/.env` (no se versiona) con:

  ```
  PORTAL_URL=https://informes.equipos.com.uy
  ```

  El Firebase CLI lee ese `.env` y completa el parámetro al desplegar.

**Región de la función (`FUNCTION_REGION`):** por defecto se despliega en
`us-central1`. Si tu base de Firestore está en otra región (la misma que pusiste
en `DATABASE_REGION`), desplegá la función ahí para que el disparador funcione:

```bash
FUNCTION_REGION="southamerica-east1" firebase deploy --only functions
```

## Paso 4 — Probar

**Activación de cuenta:**
1. En el portal, como admin, creá un usuario de prueba (con un email real).
2. Logs: `firebase functions:log --only sendAccountActivation` → debería decir
   `Activación encolada para <email>`.
3. El usuario recibe el correo, toca **"Activar cuenta y elegir contraseña"**,
   define su contraseña e ingresa.

**Informe nuevo:**
1. Concedele a ese usuario acceso a un informe.
2. Logs: `firebase functions:log --only notifyNewReportAccess` → `Aviso de
   acceso encolado para <email>`.

En ambos casos, la colección `mail` tendrá un documento nuevo; la extensión le
agrega un campo `delivery` con el estado (`SUCCESS` / `ERROR`). Si da error, ahí
aparece el detalle SMTP. Revisá también la carpeta de spam.

## Personalizar los correos

- **Texto y diseño**: funciones `build*Content()` / `build*Text()` y la
  envoltura `emailShell()` en `functions/index.js`. Colores de marca (naranja
  `#E96436`).
- **Remitente**: `DEFAULT_FROM` en `extensions/firestore-send-email.env`
  (reconfigurar la extensión para aplicarlo).
- **Asuntos**: variable `subject` en cada función.

## Costos

- Cloud Functions + Extensions: dentro del *free tier* de Blaze el volumen de un
  portal interno suele ser gratis o de centavos.
- El SMTP de Google Workspace no tiene costo extra (usa tu licencia), con
  límites de envío por día según el plan.

## Notas / próximos pasos

- **Contraseña del alta:** el formulario de creación de usuarios sigue pidiendo
  una contraseña temporal (el admin puede poner cualquier valor); con la
  activación por enlace, el usuario elige la suya y esa temporal deja de usarse.
  Opcional: hacer que el portal genere una contraseña aleatoria y ocultar el
  campo, para no tener que inventarla.
- **Reenviar activación / restablecer contraseña por Trigger Email:** se resuelve
  con la misma mecánica (una Callable Function que genera el enlace con el Admin
  SDK y escribe en `mail`). La base ya queda lista con esta etapa.
- **Recordá:** la contraseña *actual* de un usuario existente no se puede enviar
  por correo — Firebase sólo guarda un hash, no es recuperable. Por eso el
  enfoque es siempre "elegí/restablecé tu contraseña" con un enlace seguro.
