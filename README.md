# 📊 Portal de Informes — Guía de configuración

Sistema para subir informes HTML y controlar qué usuario puede acceder a cuál.
**100% gratuito** usando Firebase (plan Spark).

---

## ✅ Requisitos previos

- Cuenta de Google (gratuita)
- Navegador moderno

---

## Paso 1 — Crear proyecto en Firebase

1. Entrá a https://console.firebase.google.com
2. Hacé clic en **"Agregar proyecto"**
3. Dale un nombre (ej: `portal-informes`)
4. Desactivá Google Analytics si no lo necesitás → **Crear proyecto**

---

## Paso 2 — Activar Authentication

1. En el menú lateral: **Build → Authentication**
2. Clic en **"Comenzar"**
3. En la pestaña **Sign-in method**, habilitá **Email/contraseña**
4. Guardá

---

## Paso 3 — Activar Firestore

1. En el menú: **Build → Firestore Database**
2. Clic en **"Crear base de datos"**
3. Elegí **modo de producción** → **Siguiente**
4. Elegí la región más cercana (ej: `us-east1`) → **Listo**

### Configurar reglas de Firestore

1. En Firestore → pestaña **Reglas**
2. Borrá el contenido y pegá todo el contenido del archivo `firestore.rules`
3. Clic en **Publicar**

---

## Paso 4 — Activar Storage

1. En el menú: **Build → Storage**
2. Clic en **"Comenzar"**
3. Elegí **modo de producción** → **Siguiente** → **Listo**

### Configurar reglas de Storage

1. En Storage → pestaña **Reglas**
2. Borrá el contenido y pegá todo el archivo `storage.rules`
3. Clic en **Publicar**

---

## Paso 5 — Obtener las credenciales de la app

1. En la pantalla principal del proyecto, hacé clic en el ícono **`</>`** (Web)
2. Dale un apodo a la app (ej: `portal-web`) → **Registrar app**
3. Vas a ver un bloque `firebaseConfig` así:

```javascript
const firebaseConfig = {
  apiKey: "AIzaSy...",
  authDomain: "tu-proyecto.firebaseapp.com",
  projectId: "tu-proyecto",
  storageBucket: "tu-proyecto.firebasestorage.app",
  messagingSenderId: "123456789",
  appId: "1:123456789:web:abc123"
};
```

4. Copiá esos valores y pegálos en el archivo `index.html`, reemplazando los `REEMPLAZAR_...` en la sección de configuración (cerca del final del archivo).

---

## Paso 6 — Crear tu usuario administrador

1. En Firebase Console → **Authentication** → **Usuarios** → **Agregar usuario**
2. Ingresá tu email y contraseña
3. Copiá el **UID** que aparece en la tabla (columna "Identificador de usuario")
4. Ahora andá a **Firestore** → **Datos** → clic en **"Agregar colección"**
5. ID de colección: `users` → **Siguiente**
6. ID del documento: pegá el UID copiado
7. Agregá el campo: `email` (string) = tu email
8. Agregá el campo: `role` (string) = `admin`
9. **Guardar**

---

## Paso 7 — Publicar la app (Firebase Hosting — gratis)

### Opción A — Subir el HTML manualmente (más simple)

1. En Firebase Console → **Hosting** → **Comenzar**
2. Seguí el wizard. Al final podés subir archivos desde la interfaz.
3. Subí el `index.html` como archivo principal.

### Opción B — Firebase CLI (recomendada)

```bash
npm install -g firebase-tools
firebase login
firebase init hosting
# Elegí tu proyecto, directorio público = . (punto), SPA = sí
firebase deploy
```

---

## Paso 8 — ¡Listo para usar!

1. Abrí la URL de tu app (ej: `https://tu-proyecto.web.app`)
2. Iniciá sesión con tu cuenta de **admin**
3. **Panel Admin:**
   - 📄 **Informes** → subí los archivos HTML
   - 👥 **Usuarios** → creá cuentas para tus usuarios
   - 🔐 **Permisos** → asigná qué informes puede ver cada usuario
4. Los usuarios ingresan y ven solo sus informes asignados

---

## 🔒 Seguridad

- Los archivos solo son accesibles para usuarios autenticados
- Las reglas de Firestore y Storage previenen acceso no autorizado
- La creación de usuarios solo la puede hacer el admin (via REST API)
- Cada usuario solo ve los informes que vos le asignaste

---

## 💡 Límites del plan gratuito (Spark)

| Recurso | Límite gratuito |
|---------|----------------|
| Storage | 5 GB |
| Descargas Storage | 1 GB/día |
| Firestore lecturas | 50.000/día |
| Firestore escrituras | 20.000/día |
| Hosting | 10 GB / 360 MB deploy |
| Usuarios Auth | Ilimitados |

Para la mayoría de los casos de uso, el plan gratuito es más que suficiente.

---

## ❓ Preguntas frecuentes

**¿Puedo cambiar la contraseña de un usuario?**
Sí, desde Firebase Console → Authentication → seleccioná el usuario → Editar.

**¿Puedo eliminar un usuario?**
Sí, desde Firebase Console → Authentication. El documento en Firestore se puede eliminar manualmente de Firestore → colección `users`.

**¿Los informes HTML pueden tener imágenes/CSS/JS?**
Sí, siempre que sean recursos inline o URLs absolutas externas. Recursos relativos no van a cargar porque el HTML se sirve desde Firebase Storage.

---

## 📄 Formatos soportados y visor

El administrador puede subir **HTML, PDF, Word (.doc/.docx), PowerPoint (.ppt/.pptx) y video (.mp4/.webm/.mov/.m4v/.ogg)**.
El cliente los ve **inline** (dentro del portal), renderizados en su propio navegador:

| Formato | Cómo se muestra |
|---------|-----------------|
| PDF | Renderizado con PDF.js (páginas en canvas) |
| Word `.docx` | Renderizado con docx-preview |
| PowerPoint `.pptx` | Renderizado con PPTXjs (la fidelidad puede variar en diapositivas complejas) |
| HTML | En un `<iframe>` con sandbox |
| **Video** (`.mp4`, `.webm`, `.mov`, …) | Reproductor `<video>` nativo, inline. Aplican las protecciones (marca de agua, bloqueo de descarga/clic derecho) |
| `.doc` / `.ppt` (formatos viejos) | No se pueden previsualizar → se ofrece descarga. Convertí a `.docx`/`.pptx` o PDF |

Las librerías de render se cargan desde CDN bajo demanda (solo cuando se abre un documento de ese tipo). El video no usa librerías ni CORS.

> ⚠️ **Video y plan gratuito (Spark):** los videos son pesados y el plan gratuito tiene topes ajustados — **1 GB/día de descarga** y **5 GB de almacenamiento** total. Con videos se llega rápido a esos límites; para uso intensivo conviene el plan **Blaze** (pago por uso). El formato más compatible es **MP4 (H.264)**.

---

## 🔐 Protecciones por usuario e informe

En **Panel Admin → Permisos**, dentro de cada informe asignado a un usuario, se puede activar:

- 💧 **Marca de agua** — estampa el email del usuario + fecha/hora sobre el documento.
- 🖨️ **Bloquear impresión** — desactiva Ctrl/Cmd+P y la impresión sale en blanco.
- ⬇️ **Bloquear descarga** — oculta el botón de abrir/descargar.
- 🖱️ **Bloquear clic derecho / selección**.

> ⚠️ **Importante:** estas protecciones son **disuasivas**, no infalibles. En una web **no se puede impedir una captura de pantalla** (ni una foto con el celular), y un usuario técnico puede sortear los bloqueos. La protección más efectiva es la **marca de agua**, que deja rastro de quién visualizó el documento.

---

## 📂 Carpetas (organización de informes)

En **Panel Admin → Informes → Carpetas** se pueden crear carpetas (anidadas)
para organizar los informes:

- **Crear carpeta** eligiendo opcionalmente una carpeta "padre" (soporta
  carpetas dentro de carpetas).
- **Mover un informe** a una carpeta con el selector de la columna *Carpeta* de
  la tabla, o elegir la carpeta destino al subir.
- **Renombrar** y **borrar** carpetas. Al borrar una carpeta con contenido, sus
  subcarpetas e informes se **mueven a la carpeta padre** (no se borra ningún
  informe).

Del lado del **cliente**, la vista "Mis Informes" se navega como un árbol: se
ven las carpetas y los informes, y al entrar a una carpeta se ve su contenido
(con "migas de pan" para volver). El acceso sigue siendo **por informe**: el
cliente solo ve una carpeta si dentro (a cualquier nivel) tiene algún informe
asignado a él.

> Requiere **publicar las reglas de Firestore** actualizadas (incluyen la
> colección `folders`): pegá el contenido de `firestore.rules` en Firebase
> Console → Firestore → Reglas → Publicar. Solo el admin puede crear/editar
> carpetas; cualquier usuario autenticado puede leerlas para navegar.

---

## ⚙️ Configurar CORS del bucket (requerido para el visor)

Para que el navegador pueda **leer** los PDF/Word/PowerPoint y renderizarlos inline, el bucket de Storage necesita permitir CORS desde el dominio del portal. Se hace **una sola vez** con el archivo `cors.json` incluido:

```bash
# Necesitás gcloud/gsutil instalado y autenticado en el proyecto
gsutil cors set cors.json gs://portal-informes-ec.firebasestorage.app
```

- Editá `cors.json` para incluir tus dominios reales (`web.app` / `firebaseapp.com` / dominio propio).
- Si no configurás CORS, el visor mostrará un aviso y ofrecerá la descarga del archivo.
- Los HTML **no** requieren CORS (se muestran vía `<iframe>`).

---

## 📊 Métricas de acceso

En **Panel Admin → Métricas** se registra cada acceso al portal:

- **Quién ingresa** (email del usuario)
- **Cuántas veces** (cantidad de accesos por usuario)
- **Por cuánto tiempo** (duración de cada sesión)
- **Desde qué IP**

Cómo funciona:

- Cada carga autenticada crea un documento en la colección `sessions` de Firestore.
- La **duración** se estima con un "latido" (`lastSeenAt`) que se actualiza cada 60 s mientras la pestaña está visible, más el cierre al hacer *Cerrar sesión* o dejar la página. (No se puede medir con exactitud al milisegundo en una web sin backend; es una estimación robusta.)
- La **IP** se obtiene de un servicio público (`api.ipify.org`) al iniciar la sesión. Si ese servicio no responde, la IP queda vacía.

Requiere **publicar las reglas de Firestore** actualizadas (incluyen la colección `sessions`): pegá el contenido de `firestore.rules` en Firebase Console → Firestore → Reglas → Publicar. Solo el admin puede leer las métricas.

> Nota de consumo (plan gratuito): el latido escribe ~1 vez por minuto por sesión activa. Para un portal interno es despreciable; si tuvieras muchas sesiones largas simultáneas, se puede subir el intervalo.

---

## 📈 Analítica de uso dentro de los dashboards (informes HTML)

En **Panel Admin → Métricas → "Analítica de dashboards"** se ve, por informe, **qué pestañas/secciones usan** los clientes: cantidad de visitas y tiempo (total y promedio) por pestaña.

Cómo funciona: el dashboard (dentro del iframe) manda eventos por `postMessage`; el portal —que sabe quién es el usuario, su sesión y qué informe abrió— los guarda en la colección `dashboardEvents` de Firestore. No hace falta Firebase ni claves dentro del dashboard.

### Qué agregar en cada dashboard HTML

1. Marcá cada pestaña con `data-track="Nombre"` en el elemento donde se hace clic, y la inicial con `data-track-default`:

```html
<button data-track="Ventas" data-track-default>Ventas</button>
<button data-track="Stock">Stock</button>
```

2. Pegá este bloque una vez, antes de `</body>`:

```html
<!-- Analítica del portal (uso por pestaña) -->
<script>
(function () {
  var current = null, since = 0;
  function send(event, section, extra) {
    var msg = { __portalAnalytics: true, event: event, section: section || null, ts: Date.now() };
    if (extra) for (var k in extra) msg[k] = extra[k];
    try { parent.postMessage(msg, '*'); } catch (e) {}
  }
  function activate(name) {
    if (!name || name === current) return;
    if (current !== null) send('tab', current, { dwellMs: Date.now() - since });
    current = name; since = Date.now();
  }
  function flush() { if (current !== null) { send('tab', current, { dwellMs: Date.now() - since }); since = Date.now(); } }
  function init() {
    send('open');
    var def = document.querySelector('[data-track-default]') || document.querySelector('[data-track]');
    if (def) activate(def.getAttribute('data-track'));
  }
  document.addEventListener('click', function (e) {
    var t = e.target.closest && e.target.closest('[data-track]');
    if (t) activate(t.getAttribute('data-track'));
  }, true);
  document.addEventListener('visibilitychange', function () { if (document.hidden) flush(); });
  window.addEventListener('pagehide', flush);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
</script>
```

> Requiere publicar el `firestore.rules` actualizado (colección `dashboardEvents`). Solo el admin lee la analítica. Cada cambio de pestaña genera 1 escritura en Firestore (despreciable para uso interno).

---

## ⚙️ Parámetros por usuario en los informes HTML

Cada informe HTML puede **renderizarse dinámicamente según el usuario** que lo abre.
El portal —que sabe quién está logueado— le envía al informe (dentro del `<iframe>`)
la **identidad del usuario** (`email`, `uid`) y un objeto **`params`** con los pares
clave/valor que el admin haya definido para ese usuario.

### Definir los parámetros de un usuario

En **Panel Admin → Usuarios → ⚙️ Parámetros** (botón en cada usuario) se abren los
parámetros clave/valor de ese usuario (ej: `clienteId = 123`, `region = norte`). Se
guardan en el propio documento del usuario, así que no requieren reglas nuevas.

### Qué agregar en cada dashboard HTML

Pegá este bloque una vez, antes de `</body>`:

```html
<!-- Parámetros del portal (por usuario) -->
<script>
(function () {
  window.addEventListener('message', function (e) {
    var d = e.data;
    if (!d || d.__portalParams !== true) return;
    // Disponibles: d.email, d.uid, y d.params (objeto con las claves del admin)
    // Ejemplo: filtrar el dashboard por el cliente del usuario
    if (window.renderConParametros) window.renderConParametros(d);
  });
  // Avisar al portal que el dashboard está listo para recibir los parámetros
  try { parent.postMessage({ __portalParamsRequest: true }, '*'); } catch (e) {}
})();
</script>
```

> ⚠️ Como todo ocurre en el navegador del cliente, estos parámetros sirven para
> **personalizar la vista** (filtrar por su cliente, mostrar su nombre, etc.). Si los
> datos fueran sensibles, la protección real debe estar en la fuente de donde el HTML
> obtiene los datos, no en estos parámetros (un usuario técnico podría alterarlos).

---

### Mostrar/ocultar secciones según el parámetro (sin programar filtros)

Para que **una misma plantilla** muestre distinto contenido a cada usuario, marcá
cada sección con un atributo y dejá que un pequeño *runtime* la muestre u oculte
según los parámetros del usuario. No hay que escribir lógica de filtrado.

| Lo que querés | Atributo en el contenedor de la sección |
|---|---|
| Visible **solo** si `region=norte` | `data-portal-show="region=norte"` |
| Visible si `clienteId` es 777 **o** 888 | `data-portal-show="clienteId=777,888"` |
| Visible si `plan=premium` **y** `region=norte` | `data-portal-show="plan=premium;region=norte"` |
| Visible si el usuario **tiene** el parámetro `betaAccess` | `data-portal-show="betaAccess"` |
| **Ocultar** para `region=sur` (visible al resto) | `data-portal-hide="region=sur"` |

Sintaxis: `,` = varios valores (OR) · `;` = varios parámetros (AND) · solo el
nombre = "tiene ese parámetro (con cualquier valor)".

```html
<section data-portal-show="region=norte">… contenido solo para region=norte …</section>
```

Pegá este bloque una vez, antes de `</body>` (reemplaza al snippet simple de más
arriba: ya hace el handshake y además resuelve los `data-portal-show/hide`):

```html
<script>
(function () {
  var GATES = '[data-portal-show],[data-portal-hide]';
  function matchExpr(expr, params) {
    return String(expr).split(';').every(function (cond) {
      cond = cond.trim(); if (!cond) return true;
      var i = cond.indexOf('=');
      if (i < 0) { var p = params[cond]; return p != null && String(p).trim() !== ''; }
      var key = cond.slice(0, i).trim();
      var allowed = cond.slice(i + 1).split(',').map(function (s) { return s.trim(); });
      var val = params[key]; val = (val == null) ? '' : String(val).trim();
      return allowed.indexOf(val) !== -1;
    });
  }
  document.querySelectorAll('[data-portal-show]').forEach(function (el) { el.style.display = 'none'; });
  var applied = false;
  function apply(data, preview) {
    if (applied) return; applied = true;
    data = data || {}; var params = data.params || {};
    window.PORTAL = { email: data.email || null, uid: data.uid || null, params: params, preview: !!preview };
    document.querySelectorAll('[data-portal-show]').forEach(function (el) {
      el.style.display = matchExpr(el.getAttribute('data-portal-show'), params) ? '' : 'none';
    });
    document.querySelectorAll('[data-portal-hide]').forEach(function (el) {
      el.style.display = matchExpr(el.getAttribute('data-portal-hide'), params) ? 'none' : '';
    });
    if (preview) document.querySelectorAll(GATES).forEach(function (el) { el.style.display = ''; });
    if (window.onPortalParams) { try { window.onPortalParams(window.PORTAL); } catch (e) {} }
  }
  window.addEventListener('message', function (e) {
    if (e.data && e.data.__portalParams === true) apply(e.data, false);
  });
  try { parent.postMessage({ __portalParamsRequest: true }, '*'); } catch (e) {}
  setTimeout(function () { if (!applied) apply({ params: {} }, true); }, 1500);   // fuera del portal: mostrar todo
})();
</script>
```

> Dentro del HTML podés usar `window.PORTAL` (`email`, `uid`, `params`) y opcionalmente
> definir `window.onPortalParams(portal)` para personalizar textos.
> Hay un ejemplo completo y funcional en [`examples/dashboard-parametros.html`](examples/dashboard-parametros.html).

---

## 🔄 Actualizar un informe por API (sin backend)

Podés **sobrescribir el contenido de un informe** de forma programática (desde otro
sistema, un cron, una GitHub Action, etc.) sin usar el panel y sin montar un
servidor. Se apoya en la **REST API de Firebase**, así que sigue funcionando en el
plan gratuito (Spark).

El repositorio incluye un script listo: [`scripts/update_report.py`](scripts/update_report.py)
(solo requiere Python 3, sin dependencias).

### Cómo funciona
1. Se autentica como un **usuario admin** (email/contraseña) y obtiene un token.
2. Sube el archivo nuevo a la **misma ruta de Storage** del informe → lo sobrescribe.
3. Actualiza el tamaño en la metadata y, si el informe tiene un **enlace público**,
   refresca su URL (al sobrescribir, el token de descarga cambia).

Como el ID del informe y su ruta no cambian, **los accesos por usuario y los
permisos existentes se mantienen**.

### Uso

```bash
# Credenciales por variables de entorno (recomendado)
export PORTAL_EMAIL='admin-servicio@equipos.com.uy'
export PORTAL_PASSWORD='••••••••'

# 1) Listar los informes para conocer sus IDs
python3 scripts/update_report.py --list

# 2) Sobrescribir un informe por su ID
python3 scripts/update_report.py --report-id <ID> --file ./nuevo.html
```

### Recomendaciones
- Creá un **usuario admin "de servicio"** dedicado para esta integración (no reutilices
  tu usuario personal), así podés rotar o revocar sus credenciales sin afectar tu acceso.
- Cualquier cliente HTTP sirve (curl, Node, n8n, etc.): el script solo hace 3 llamadas
  REST (login → subir a Storage → PATCH en Firestore). El `.py` sirve de referencia.

---
# plataforma-informes-ec
