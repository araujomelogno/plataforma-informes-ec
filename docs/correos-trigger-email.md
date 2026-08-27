# Correos automáticos con Trigger Email (correo de "informe nuevo")

Este documento explica cómo queda armado el envío del **correo nuevo** —el aviso
automático de *"tenés un informe nuevo disponible"*— y cómo desplegarlo.

> Alcance de esta etapa: **solo el correo nuevo.** Los correos de *restablecer
> contraseña* y *verificación de email* **siguen saliendo por Firebase
> Authentication** (sin cambios). Migrarlos a Trigger Email es una etapa
> posterior que requiere generar el enlace de acción con el Admin SDK
> (`generatePasswordResetLink` / `generateEmailVerificationLink`) desde una
> Cloud Function.

## Cómo funciona

1. Un admin le concede a un usuario acceso a un informe. En el portal eso agrega
   el id del informe al array `reportIds` del documento `userAccess/{uid}`
   (un documento por usuario; el acceso se agrega/quita del array).
2. La Cloud Function **`notifyNewReportAccess`** (`functions/index.js`) escucha
   toda escritura de `userAccess/{uid}`, compara `reportIds` antes/después y
   detecta los informes **recién agregados**.
3. Por cada alta de acceso, la función busca el email del usuario en
   `users/{uid}` y el nombre del informe en `reports/{id}`, arma el HTML del
   correo y **escribe un documento en la colección `mail`**.
4. La extensión **Trigger Email from Firestore** (`firestore-send-email`) toma
   ese documento y envía el correo por el **SMTP de Google Workspace**.

```
Admin concede acceso ──▶ userAccess/{uid}.reportIds += reportId
                                     │  (onWrite)
                                     ▼
                        notifyNewReportAccess (Cloud Function)
                                     │  escribe { to, message } 
                                     ▼
                           colección `mail`  ──▶  extensión Trigger Email  ──▶  📧 SMTP Google Workspace
```

La colección `mail` está **cerrada a los clientes** en `firestore.rules`
(`allow read, write: if false`): sólo la función (Admin SDK) escribe ahí. Así
nadie puede encolar correos arbitrarios desde el navegador.

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

## Paso 3 — Configurar y desplegar la Cloud Function

La función usa dos parámetros con valores por defecto (no hace falta tocarlos si
son correctos):

- `PORTAL_URL` (default `https://portal-informes-ec.web.app`): la URL del portal
  para el botón "Ingresar". **Cambialo si usás un dominio propio.**
- `MAIL_COLLECTION` (default `mail`): debe coincidir con la extensión.

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

1. En el portal, como admin, concedele acceso a un informe a un usuario de
   prueba (que tenga un email real en `users/{uid}`).
2. Revisá los **logs** de la función:
   `firebase functions:log --only notifyNewReportAccess`
   Debería decir `Aviso de acceso encolado para <email>`.
3. En Firestore, la colección `mail` tendrá un documento nuevo. La extensión le
   agrega un campo `delivery` con el estado (`SUCCESS` / `ERROR`). Si da error,
   ahí aparece el detalle SMTP.
4. Revisá la casilla del usuario (y la carpeta de spam).

## Personalizar el correo

- **Texto y diseño**: funciones `buildHtml()` / `buildText()` en
  `functions/index.js`. Los colores son los de marca (naranja `#E96436`).
- **Remitente**: `DEFAULT_FROM` en `extensions/firestore-send-email.env`
  (reconfigurar la extensión para aplicarlo).
- **Asunto**: variable `subject` en `notifyNewReportAccess`.

## Costos

- Cloud Functions + Extensions: dentro del *free tier* de Blaze el volumen de un
  portal interno suele ser gratis o de centavos.
- El SMTP de Google Workspace no tiene costo extra (usa tu licencia), con
  límites de envío por día según el plan.

## Notas / próximos pasos

- Si más adelante migran **restablecer contraseña** y **activación de cuenta** a
  Trigger Email, se agregan Callable Functions que generan el enlace con el
  Admin SDK y escriben en `mail` con la misma mecánica. La base (extensión +
  colección `mail` + reglas) ya queda lista con esta etapa.
