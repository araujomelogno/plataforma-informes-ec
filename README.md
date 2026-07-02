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

El administrador puede subir **HTML, PDF, Word (.doc/.docx) y PowerPoint (.ppt/.pptx)**.
El cliente los ve **inline** (dentro del portal), renderizados en su propio navegador:

| Formato | Cómo se muestra |
|---------|-----------------|
| PDF | Renderizado con PDF.js (páginas en canvas) |
| Word `.docx` | Renderizado con docx-preview |
| PowerPoint `.pptx` | Renderizado con PPTXjs (la fidelidad puede variar en diapositivas complejas) |
| HTML | En un `<iframe>` con sandbox |
| `.doc` / `.ppt` (formatos viejos) | No se pueden previsualizar → se ofrece descarga. Convertí a `.docx`/`.pptx` o PDF |

Las librerías de render se cargan desde CDN bajo demanda (solo cuando se abre un documento de ese tipo).

---

## 🔐 Protecciones por usuario e informe

En **Panel Admin → Permisos**, dentro de cada informe asignado a un usuario, se puede activar:

- 💧 **Marca de agua** — estampa el email del usuario + fecha/hora sobre el documento.
- 🖨️ **Bloquear impresión** — desactiva Ctrl/Cmd+P y la impresión sale en blanco.
- ⬇️ **Bloquear descarga** — oculta el botón de abrir/descargar.
- 🖱️ **Bloquear clic derecho / selección**.

> ⚠️ **Importante:** estas protecciones son **disuasivas**, no infalibles. En una web **no se puede impedir una captura de pantalla** (ni una foto con el celular), y un usuario técnico puede sortear los bloqueos. La protección más efectiva es la **marca de agua**, que deja rastro de quién visualizó el documento.

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
# plataforma-informes-ec
