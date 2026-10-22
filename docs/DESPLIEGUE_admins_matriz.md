# Despliegue — Admins con parámetros e informes asignados, y matriz compacta

**Proyecto Firebase:** `portal-informes-ec` · **Spec:** `specs/SPEC — Admins con parámetros e informes asignados, y matriz compacta (plataforma-informes-ec).md`

Cambio chico: casi todo es front (`index.html`), más una línea de comportamiento en `functions/portal/avisos.py`.
**No hay colecciones nuevas, cambios de reglas de Firestore, índices ni secretos.**

## Qué cambia

| Requisito | Dónde | Qué hace |
| --- | --- | --- |
| B1–B3 | `renderMatrix()` | La matriz muestra solo los usuarios con algún ✓ en los informes visibles. Arriba muestra una línea con el conteo y, si no hay ninguno, un estado vacío propio. |
| B4 | `renderMatrix()` | Los admins con asignaciones aparecen como columna, marcados **ADMIN**. |
| B5, B6 (P1) | `tab-matrix` | Casillas «Mostrar todos los usuarios» y «Ocultar informes sin usuarios», que se guardan en `localStorage` (`matrix.showAllUsers`, `matrix.hideEmptyReports`). |
| A1 | `renderUsersTable()`, `saveUserParams()` | «⚙️ Parámetros» también para admins. Si son los propios, se actualiza `currentUserData.params`, así que la vista previa y «Mis informes» los usan sin recargar. |
| A2 | Permisos, modal 👥 Usuarios, tabla de usuarios | Los admins se pueden asignar y llevan la insignia admin. No se les muestran protecciones ni caducidad. Los contadores los incluyen. |
| A3 | `tab-mine`, `loadUserReports(containerId)`, `openUserReport()` | Nueva sección **⭐ Mis informes** con navegación por carpetas. Abre los informes sin protecciones y con los parámetros del admin. La pantalla de inicio sigue siendo «Informes». |
| A4 | `functions/portal/avisos.py` + casillas | Los admins ya no se excluyen del aviso «Nuevo informe». Para ellos la casilla «Avisar» viene destildada (en el modal, en una casilla aparte, «Avisar también a los admins»). |
| A5 (P1) | `setupDashboardAnalytics()`, `loadDashboardAnalytics()` | Los `dashboardEvents` guardan `role`. La analítica de dashboards excluye el uso de admins. `sessions` ya guardaba `role`. |

Respuestas que asume la implementación para las preguntas abiertas de la spec:

- El admin **no** cae en «Mis informes» al entrar.
- Las aperturas de admins **se registran marcadas** con `role: 'admin'` y quedan fuera de la analítica de clientes.
- Un admin **puede** editar sus propios parámetros.
- Si a un admin se le quita el rol, sus asignaciones pasan tal cual a ser accesos de cliente. Ya tienen `DEFAULT_OPTS`, que se graban al asignar.

## Pasos

Desde la raíz del repo, con `main` actualizado (PR mergeado) y `firebase use portal-informes-ec`:

1. **Funciones** (por A4; si se despliega solo el front, los admins simplemente no reciben avisos):

   ```bash
   firebase deploy --only functions:notificarAcceso,functions:despacharAvisos --project portal-informes-ec
   ```

   Alcanza con esas dos: son las que importan `avisos.py`. Si no, `firebase deploy --only functions`.

2. **Front:**

   ```bash
   firebase deploy --only hosting --project portal-informes-ec
   ```

El orden entre los dos no importa: el front nuevo funciona con las funciones viejas y viceversa.

## Verificación (criterios de aceptación)

Como admin, recargando con Ctrl/Cmd+Shift+R:

**Matriz**

1. ☐ Sin filtros, se ven solo usuarios con algún ✓ y la línea «Mostrando N de M usuarios…».
2. ☐ Al escribir un nombre en «🔎 Informe…», quedan solo los usuarios de esos informes; al borrarlo, vuelven. El conteo se actualiza con cada tecla.
3. ☐ «🔎 Usuario (email)…» se aplica encima de la regla.
4. ☐ La columna «Total» y la fila «Informes por usuario» muestran los mismos números de antes.
5. ☐ Con un filtro sin accesos aparece «Ningún usuario tiene acceso a estos informes».
6. ☐ «Mostrar todos los usuarios» vuelve a la matriz completa y se mantiene al recargar. «Ocultar informes sin usuarios» esconde las filas vacías.

**Admins**

7. ☐ Usuarios: la fila de un admin tiene «🔐 Permisos» y «⚙️ Parámetros».
8. ☐ Ponerse `region = Norte` en los propios parámetros. Sin recargar, la vista previa (👁) de un dashboard parametrizado lo muestra filtrado por Norte.
9. ☐ Permisos: el admin aparece «· admin», sin protecciones ni caducidad, con la casilla de aviso destildada. Asignarle 3 informes escribe `userAccess/{uid}` con `grantedBy…`.
10. ☐ ⭐ Mis informes muestra esos 3 en sus carpetas y los abre sin marca de agua y con los parámetros. Un admin sin asignaciones ve «No tenés informes asignados» con un enlace a Permisos.
11. ☐ Al entrar, el admin sigue cayendo en «Informes».
12. ☐ Asignar a un admin con la casilla destildada no envía nada, ni siquiera un intento en «Últimos envíos». Tildándola, llega «Nuevo informe».
13. ☐ El contador «usuarios con acceso» de la lista de informes cuenta también a los admins asignados.
14. ☐ Métricas → Analítica de dashboards no suma lo que un admin abrió desde «Mis informes».

## Pruebas automáticas

```bash
firebase emulators:exec --only firestore,auth --project demo-portal \
  "cd functions && venv/bin/python -m pytest -q"     # 34 passed
```

Se reemplazó «admin no recibe avisos» por dos casos: «admin con aviso → envía» y «admin sin aviso → no envía ni registra».

## Rollback

- **Front:** Hosting → Release history → versión anterior → Rollback.
- **Avisos a admins:** volver a la versión anterior de `avisos.py` y redesplegar `notificarAcceso` y `despacharAvisos`. Mientras tanto, alcanza con no tildar la casilla para admins.
- No hay datos que migrar ni revertir. Las asignaciones hechas a admins quedan en `userAccess` y el front viejo simplemente no las muestra.

## Costo

US$0 adicional. Solo hay lecturas de Firestore al abrir «Mis informes» (1 de `userAccess` + 1 por informe). Los avisos a admins salen del cupo diario de `notificaciones@`, compartido con `paneles`, y por eso la casilla viene destildada para ellos.
