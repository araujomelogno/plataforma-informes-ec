/**
 * Cloud Functions — Portal de Informes (Equipos Consultores)
 * ==========================================================
 *
 * notifyNewReportAccess
 * ---------------------
 * Cuando un admin le concede a un usuario acceso a un informe, se escribe el id
 * del informe dentro del array `reportIds` del documento `userAccess/{uid}`
 * (ver grantReportToUser() en index.html). NO se crea un documento por acceso:
 * hay UN documento por usuario y el acceso se agrega/quita de ese array.
 *
 * Por eso escuchamos CUALQUIER escritura sobre `userAccess/{uid}` y comparamos
 * el array `reportIds` de ANTES y DESPUÉS. Los ids que aparecen sólo en el
 * "después" son accesos nuevos → por cada uno (o por el lote) le mandamos al
 * usuario un correo avisándole que tiene un informe nuevo disponible.
 *
 * El correo NO se envía directamente desde acá: escribimos un documento en la
 * colección `mail` y de ahí lo toma la extensión oficial "Trigger Email from
 * Firestore" (firestore-send-email), que lo envía por el SMTP de Google
 * Workspace configurado en la extensión. Así el diseño y el remitente quedan
 * 100% bajo nuestro control.
 */

const { onDocumentWritten } = require('firebase-functions/v2/firestore');
const { defineString } = require('firebase-functions/params');
const logger = require('firebase-functions/logger');
const admin = require('firebase-admin');

admin.initializeApp();
const db = admin.firestore();

// ── Parámetros configurables al desplegar (sin tocar código) ──
// PORTAL_URL   : dirección del portal para el botón "Ingresar" del correo.
// MAIL_COLLECTION : colección que observa la extensión Trigger Email. DEBE
//                   coincidir con el parámetro "Email documents collection" de
//                   la extensión (por defecto, 'mail').
const PORTAL_URL = defineString('PORTAL_URL', {
  default: 'https://portal-informes-ec.web.app',
});
const MAIL_COLLECTION = defineString('MAIL_COLLECTION', { default: 'mail' });

/** Escapa texto para insertarlo con seguridad dentro del HTML del correo. */
function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** Devuelve los ids presentes en `after` que no estaban en `before`. */
function newlyAdded(beforeIds, afterIds) {
  const prev = new Set(beforeIds || []);
  return (afterIds || []).filter((id) => !prev.has(id));
}

/** Lee el nombre de cada informe; si no existe, cae a un texto genérico. */
async function fetchReportNames(reportIds) {
  const snaps = await Promise.all(
    reportIds.map((id) => db.collection('reports').doc(id).get())
  );
  return snaps.map((s) =>
    s.exists ? String(s.data().name || 'Informe').trim() || 'Informe' : 'Informe'
  );
}

/** Arma el HTML (email-safe, tablas + estilos inline) del correo. */
function buildHtml(reportNames, portalUrl) {
  const items = reportNames
    .map(
      (n) =>
        `<tr><td style="padding:6px 0;font-size:15px;color:#3A3838;">` +
        `&#128196;&nbsp;<strong>${esc(n)}</strong></td></tr>`
    )
    .join('');

  const plural = reportNames.length > 1;
  const intro = plural
    ? 'Se habilitaron nuevos informes en tu cuenta del Portal de Informes:'
    : 'Se habilitó un nuevo informe en tu cuenta del Portal de Informes:';

  return `<!doctype html>
<html lang="es">
<body style="margin:0;padding:0;background:#F7F7F7;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F7F7F7;padding:24px 0;">
    <tr><td align="center">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#FFFFFF;border:1px solid #E2E2E2;border-radius:12px;overflow:hidden;font-family:'Segoe UI',Arial,Helvetica,sans-serif;">
        <tr><td style="background:#E96436;padding:22px 28px;">
          <span style="color:#FFFFFF;font-size:18px;font-weight:800;letter-spacing:-0.02em;">Equipos Consultores</span>
          <span style="color:#FDE7DE;font-size:13px;display:block;margin-top:2px;">Portal de Informes</span>
        </td></tr>
        <tr><td style="padding:28px 28px 8px 28px;">
          <h1 style="margin:0 0 12px 0;font-size:20px;color:#3A3838;font-weight:800;letter-spacing:-0.02em;">Tenés ${plural ? 'informes nuevos' : 'un informe nuevo'} disponible${plural ? 's' : ''}</h1>
          <p style="margin:0 0 16px 0;font-size:15px;color:#7A7A7A;line-height:1.55;">${esc(intro)}</p>
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#FDF0EB;border-radius:8px;padding:12px 16px;margin:0 0 20px 0;">
            ${items}
          </table>
          <table role="presentation" cellpadding="0" cellspacing="0" style="margin:4px 0 8px 0;">
            <tr><td style="border-radius:8px;background:#E96436;">
              <a href="${esc(portalUrl)}" style="display:inline-block;padding:12px 26px;font-size:15px;font-weight:700;color:#FFFFFF;text-decoration:none;border-radius:8px;">Ingresar al portal &rarr;</a>
            </td></tr>
          </table>
          <p style="margin:14px 0 0 0;font-size:13px;color:#7A7A7A;line-height:1.5;">Ingresá con tu email y contraseña habituales. Si olvidaste tu contraseña, usá el enlace «¿Olvidaste tu contraseña?» en la pantalla de ingreso.</p>
        </td></tr>
        <tr><td style="padding:20px 28px 26px 28px;border-top:1px solid #EEEEEE;">
          <p style="margin:0;font-size:12px;color:#9A9A9A;line-height:1.5;">Recibiste este correo porque tenés una cuenta en el Portal de Informes de Equipos Consultores. Si creés que es un error, contactá a tu administrador.</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>`;
}

/** Versión en texto plano (fallback para clientes sin HTML). */
function buildText(reportNames, portalUrl) {
  const lista = reportNames.map((n) => `  - ${n}`).join('\n');
  return (
    `Portal de Informes — Equipos Consultores\n\n` +
    `Se habilitó ${reportNames.length > 1 ? 'nuevo contenido' : 'un nuevo informe'} en tu cuenta:\n` +
    `${lista}\n\n` +
    `Ingresá al portal: ${portalUrl}\n\n` +
    `Ingresá con tu email y contraseña habituales.`
  );
}

exports.notifyNewReportAccess = onDocumentWritten(
  {
    document: 'userAccess/{uid}',
    // Región de la función. Debe ser compatible con la ubicación de Firestore.
    // Ajustala al desplegar si tu base NO está en us-central:
    //   FUNCTION_REGION=southamerica-east1 firebase deploy --only functions
    region: process.env.FUNCTION_REGION || 'us-central1',
  },
  async (event) => {
    const uid = event.params.uid;
    const before = event.data.before.exists ? event.data.before.data() : {};
    const after = event.data.after.exists ? event.data.after.data() : null;

    // Documento borrado (se le quitó todo el acceso) → nada que notificar.
    if (!after) return;

    const added = newlyAdded(before.reportIds, after.reportIds);
    if (!added.length) {
      // La escritura no agregó informes (p. ej. cambio de opciones/caducidad).
      return;
    }

    // Email del destinatario: está en users/{uid} (userAccess no lo guarda).
    const userSnap = await db.collection('users').doc(uid).get();
    const email = userSnap.exists ? (userSnap.data().email || '').trim() : '';
    if (!email) {
      logger.warn(`Sin email para uid=${uid}; no se envía el aviso.`, { added });
      return;
    }

    const names = await fetchReportNames(added);
    const portalUrl = PORTAL_URL.value();
    const subject =
      names.length > 1
        ? 'Tenés informes nuevos disponibles en el Portal'
        : `Nuevo informe disponible: ${names[0]}`;

    await db.collection(MAIL_COLLECTION.value()).add({
      to: [email],
      message: {
        subject,
        html: buildHtml(names, portalUrl),
        text: buildText(names, portalUrl),
      },
    });

    logger.info(`Aviso de acceso encolado para ${email}`, {
      uid,
      reportIds: added,
    });
  }
);
