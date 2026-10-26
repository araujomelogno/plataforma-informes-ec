# Despliegue — Aviso «Nuevo informe» en el momento de asignar

**Proyecto Firebase:** `portal-informes-ec`

## El problema

Al asignar un informe a un usuario, el correo «Nuevo informe» no llegaba. Pasaba igual en los tres caminos para
asignar:

1. **Permisos** (elegir usuario → marcar informes).
2. **Informes → 👥 Usuarios** (modal del informe).
3. **Usuarios → 🔐 Permisos** (lleva a la pestaña Permisos con el usuario elegido).

Los tres escriben lo mismo (`grantReportToUser` → `userAccess/{uid}`), así que la falla no estaba en un camino en
particular sino en cómo salía el correo. Hasta ahora era **solo del lado del servidor y en diferido**:

- el trigger de Firestore `notificarAcceso` encolaba el aviso en `avisosPendientes`;
- la función programada `despacharAvisos` (Cloud Scheduler, cada minuto) lo mandaba a los 2–3 minutos.

Si cualquiera de esas dos piezas no quedó desplegada o no corre en producción, el aviso nunca sale y **ni siquiera
queda un intento en «Últimos envíos»**. Eso pasa, por ejemplo, si el primer deploy del trigger falló por los permisos
de Eventarc, si se desplegaron solo algunas funciones o si el job de Cloud Scheduler está pausado. Además, aunque
todo funcionara, el correo no salía «en el momento» sino minutos después, y el admin no veía ninguna confirmación.

> Desde este entorno no hay acceso a la consola ni a los logs de `portal-informes-ec`, así que no se pudo confirmar
> cuál de esas piezas falla en producción. Con la sección «Diagnóstico» de abajo se averigua en 2 minutos. El cambio
> hace que el aviso **ya no dependa de ellas**.

## La solución

- **El panel manda el aviso en el momento.** Después de marcar un informe, desde cualquiera de los tres caminos,
  el panel espera ~4 segundos por si se marcan más informes al mismo usuario y llama a la nueva función
  **`avisarAsignacion`**. Es una callable, igual que `crearUsuario`, que ya funciona en producción. La función manda
  **un solo correo** con la lista y devuelve el resultado.
- **El admin ve el resultado** abajo a la derecha:
  - «📧 Se avisó por correo a cliente@…»;
  - o «⚠️ El acceso quedó dado, pero el correo no salió: <motivo>», por ejemplo una credencial SMTP inválida.
- **El trigger y la función programada quedan de respaldo.** Mandan el aviso si el panel no llegó a hacerlo, por
  ejemplo si se cerró la pestaña enseguida. Al ocultar la pestaña, el panel manda lo pendiente en el acto.
- **Nunca hay correos duplicados.** El panel y el trigger encolan con el mismo id,
  `avisosPendientes/{uid}-{reportId}-{grantedAt}`, y el envío se reclama en una transacción. Volver a asignar un
  informe más tarde sí es otro aviso.
- **Se mantiene todo lo demás:** la casilla «📧 Avisar al usuario por correo» (destildada → no sale nada), marcar y
  desmarcar enseguida → no sale nada, varios informes seguidos → un correo con la lista, plantilla apagada → omitido.
- **Diagnóstico en Configuración → Correos:** junto al contador de 24 h se muestran los «⏳ Avisos en espera». Si el
  más viejo supera la espera de respaldo, se marca en rojo: la función programada no está corriendo.
- El campo «Agrupar avisos (minutos)» pasa a llamarse **«Espera de respaldo (minutos)»**. Es solo para el respaldo
  del servidor.

| Archivo | Cambio |
| --- | --- |
| `functions/portal/avisos.py` | `clave_aviso()`, `_encolar()` (id común panel/trigger) y `avisar_ahora()`. El despacho devuelve el detalle. |
| `functions/main.py` | Nueva callable `avisarAsignacion` (solo admin). |
| `index.html` | `grantReportToUser` encola el aviso; `queueAssignmentNotice`/`flushAssignmentNotice` (espera de 4 s + llamada); avisos en pantalla (`showToast`); diagnóstico de pendientes; textos de Configuración. |
| `functions/tests/test_avisos.py` | 5 pruebas nuevas (39 en total). |
| `docs/manual-usuario.html` | Cuándo sale el aviso y la espera de respaldo. |

No cambian reglas de Firestore, índices ni secretos.

## Diagnóstico (antes o después de desplegar)

1. **¿Están las funciones?**

   ```bash
   firebase functions:list --project portal-informes-ec
   ```

   Tienen que figurar `notificarAcceso` (trigger de Firestore) y `despacharAvisos` (programada). Si falta alguna, el
   respaldo no anda: se arregla con el deploy de abajo.
2. **¿Corre la programada?** En Google Cloud Console → *Cloud Scheduler*, el job de `despacharAvisos` tiene que estar
   *Enabled* y su última ejecución en *Success*.
3. **¿Hay avisos trabados?** En Firebase Console → Firestore → `avisosPendientes`, mirar los documentos con
   `estado: "pendiente"` y un `creadoEn` de hace más de unos minutos. Desde este cambio también se ven en
   Configuración → Correos.
4. **Logs:**

   ```bash
   firebase functions:log --only notificarAcceso --project portal-informes-ec
   firebase functions:log --only despacharAvisos --project portal-informes-ec
   ```

5. Si en «Últimos envíos» los avisos figuran **fallidos**, el problema es el SMTP (motivo en la fila). Ver la guía
   `DESPLIEGUE_alta_usuarios_correo.md` §12.

## ⚠️ Antes de desplegar funciones: vaciar los avisos trabados

Si «⏳ Avisos en espera» muestra avisos viejos (por ejemplo, 68 con el más viejo de hace días), **no hay que
mandarlos**: avisar días después de una asignación confunde. Con versiones anteriores a este cambio, desplegar las
funciones los habría enviado todos de golpe.

Hay que vaciar la cola **antes** de `firebase deploy --only functions`. Borrarla no cambia ningún acceso: solo hace
que esos correos no salgan. Cualquiera de estas opciones sirve:

```bash
firebase firestore:delete avisosPendientes --recursive --project portal-informes-ec
```

o Firebase Console → Firestore → `avisosPendientes` → ⋮ → **Delete collection**.

Ya desplegado este cambio, además:

- los avisos con más de **60 minutos** en espera **vencen**: se cierran como `vencido` sin enviarse, ni por la
  función programada ni sumados al correo de un informe nuevo;
- en Configuración → Correos, junto a «⏳ Avisos en espera», está el botón **«🗑 Descartar sin enviar»**.

## Despliegue

Desde la raíz del repo, con `main` actualizado (PR mergeado):

```bash
firebase use portal-informes-ec
firebase deploy --only functions --project portal-informes-ec   # crea avisarAsignacion y actualiza el resto
firebase deploy --only hosting   --project portal-informes-ec
```

- Desplegar **todas** las funciones, no solo la nueva: así también se crean o reparan `notificarAcceso` y
  `despacharAvisos` si les faltaba algo.
- Si el deploy de `notificarAcceso` falla con permisos del *Eventarc Service Agent*, esperar 5 minutos y repetir. Es
  la propagación inicial de permisos de Google. Mientras tanto, el aviso en el momento ya funciona porque no depende
  del trigger.
- Orden: primero funciones, después hosting. Si el front nuevo sale antes, al asignar se ve «no se pudo enviar el
  aviso ahora… el servidor lo reintenta» y el aviso queda en manos del respaldo.

## Verificación

Con un usuario de prueba con una casilla real, recargando el panel con Ctrl/Cmd+Shift+R:

1. ☐ **Permisos:** elegir el usuario, marcar 2 informes seguidos. A los ~5 s aparece «📧 Se avisó por correo a …
   (2 informes)» y llega **un** correo con los dos.
2. ☐ **Informes → 👥 Usuarios:** marcar el usuario en otro informe. Aparece la confirmación y llega el correo.
3. ☐ **Usuarios → 🔐 Permisos:** marcar otro informe. Aparece la confirmación y llega el correo.
4. ☐ Marcar y desmarcar enseguida: no llega nada.
5. ☐ Con «📧 Avisar al usuario por correo» destildada: no llega nada y no hay intento en «Últimos envíos».
6. ☐ Marcar un informe y cerrar la pestaña antes de 4 s: el correo llega igual, en el momento si el navegador
   alcanzó a mandarlo o si no a los pocos minutos por el respaldo.
7. ☐ En Configuración → Correos no quedan «⏳ Avisos en espera» en rojo.
8. ☐ Ninguna de las pruebas generó correos duplicados (revisar «Últimos envíos»).

## Rollback

- **Front:** Hosting → Release history → versión anterior. Se vuelve al aviso solo por servidor.
- **Funciones:** `firebase functions:delete avisarAsignacion --region <REGION>` y redesplegar la versión anterior de
  `functions/`. El trigger y la programada siguen funcionando como antes.

## Pruebas automáticas

```bash
firebase emulators:exec --only firestore,auth --project demo-portal \
  "cd functions && venv/bin/python -m pytest -q"     # 39 passed
```

Las 5 pruebas nuevas cubren:

- el panel manda en el momento y el trigger posterior no duplica;
- el trigger primero y el panel después dan un solo correo;
- reasignar más tarde es otro aviso;
- se respetan «no avisar» y los accesos quitados;
- con el SMTP caído, el resultado es «fallido» y no se revierte el permiso.

Además, se probaron los tres caminos de punta a punta en el navegador contra los emuladores: un intento por
asignación, ninguno con la casilla destildada o al marcar y desmarcar, y sin duplicados del respaldo.
