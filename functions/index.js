/**
 * Cloud Functions — Portal de Informes (Equipos Consultores)
 * ==========================================================
 *
 * Los correos NO se envían directamente desde acá: cada función escribe un
 * documento en la colección `mail` y de ahí lo toma la extensión oficial
 * "Trigger Email from Firestore" (firestore-send-email), que lo manda por el
 * SMTP de Google Workspace. Así el diseño y el remitente quedan bajo nuestro
 * control. La colección `mail` está cerrada a los clientes en firestore.rules;
 * sólo el Admin SDK (estas funciones) escribe ahí.
 *
 * notifyNewReportAccess
 * ---------------------
 * Cuando un admin le concede a un usuario acceso a un informe, se agrega el id
 * al array `reportIds` del documento `userAccess/{uid}` (ver grantReportToUser()
 * en index.html). NO hay un documento por acceso: hay UNO por usuario y el
 * acceso se agrega/quita del array. Por eso escuchamos toda escritura de
 * `userAccess/{uid}` y comparamos `reportIds` antes/después: los ids nuevos son
 * accesos recién concedidos → le avisamos al usuario por correo.
 *
 * sendAccountActivation
 * ---------------------
 * Cuando se crea la cuenta de un usuario (documento nuevo en `users/{uid}`),
 * generamos con el Admin SDK un enlace seguro de "elegí tu contraseña"
 * (generatePasswordResetLink) y se lo mandamos como correo de activación. Así el
 * usuario define su propia contraseña: NUNCA viaja una contraseña por correo.
 */

const {
  onDocumentWritten,
  onDocumentCreated,
} = require('firebase-functions/v2/firestore');
const { defineString } = require('firebase-functions/params');
const logger = require('firebase-functions/logger');
const admin = require('firebase-admin');

admin.initializeApp();
const db = admin.firestore();

// ── Parámetros configurables al desplegar (sin tocar código) ──
// PORTAL_URL      : dirección del portal (botón de los correos + continue URL
//                   del enlace de activación).
// MAIL_COLLECTION : colección que observa la extensión Trigger Email. DEBE
//                   coincidir con el parámetro "Email documents collection" de
//                   la extensión (por defecto, 'mail').
const PORTAL_URL = defineString('PORTAL_URL', {
  default: 'https://portal-informes-ec.web.app',
});
const MAIL_COLLECTION = defineString('MAIL_COLLECTION', { default: 'mail' });

// Región de las funciones. Debe ser compatible con la ubicación de Firestore.
// Ajustala al desplegar si tu base NO está en us-central:
//   FUNCTION_REGION=southamerica-east1 firebase deploy --only functions
const REGION = process.env.FUNCTION_REGION || 'us-central1';

/** Escapa texto para insertarlo con seguridad dentro del HTML del correo. */
function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ── Plantillas de correo (email-safe: tablas + estilos inline) ────────────────

/** Envoltura de marca común: encabezado naranja + contenido + pie. */
function emailShell(contentHtml) {
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
          ${contentHtml}
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

/** Botón de acción (naranja). `label` es texto de confianza (no dato externo). */
function button(href, label) {
  return `<table role="presentation" cellpadding="0" cellspacing="0" style="margin:4px 0 8px 0;">
            <tr><td style="border-radius:8px;background:#E96436;">
              <a href="${esc(href)}" style="display:inline-block;padding:12px 26px;font-size:15px;font-weight:700;color:#FFFFFF;text-decoration:none;border-radius:8px;">${label}</a>
            </td></tr>
          </table>`;
}

/** Contenido del correo "tenés informe(s) nuevo(s)". */
function buildReportContent(reportNames, portalUrl) {
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

  return `<h1 style="margin:0 0 12px 0;font-size:20px;color:#3A3838;font-weight:800;letter-spacing:-0.02em;">Tenés ${plural ? 'informes nuevos' : 'un informe nuevo'} disponible${plural ? 's' : ''}</h1>
          <p style="margin:0 0 16px 0;font-size:15px;color:#7A7A7A;line-height:1.55;">${esc(intro)}</p>
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#FDF0EB;border-radius:8px;padding:12px 16px;margin:0 0 20px 0;">
            ${items}
          </table>
          ${button(portalUrl, 'Ingresar al portal &rarr;')}
          <p style="margin:14px 0 0 0;font-size:13px;color:#7A7A7A;line-height:1.5;">Ingresá con tu email y contraseña habituales. Si olvidaste tu contraseña, usá el enlace «¿Olvidaste tu contraseña?» en la pantalla de ingreso.</p>`;
}

function buildReportText(reportNames, portalUrl) {
  const lista = reportNames.map((n) => `  - ${n}`).join('\n');
  return (
    `Portal de Informes — Equipos Consultores\n\n` +
    `Se habilitó ${reportNames.length > 1 ? 'nuevo contenido' : 'un nuevo informe'} en tu cuenta:\n` +
    `${lista}\n\n` +
    `Ingresá al portal: ${portalUrl}\n\n` +
    `Ingresá con tu email y contraseña habituales.`
  );
}

/** Contenido del correo de activación (elegí tu contraseña). */
function buildActivationContent(email, link) {
  return `<h1 style="margin:0 0 12px 0;font-size:20px;color:#3A3838;font-weight:800;letter-spacing:-0.02em;">Activá tu cuenta</h1>
          <p style="margin:0 0 12px 0;font-size:15px;color:#7A7A7A;line-height:1.55;">Te damos la bienvenida al Portal de Informes de Equipos Consultores. Tu usuario es <strong style="color:#3A3838;">${esc(email)}</strong>.</p>
          <p style="margin:0 0 20px 0;font-size:15px;color:#7A7A7A;line-height:1.55;">Para ingresar por primera vez, activá tu cuenta y elegí tu contraseña:</p>
          ${button(link, 'Activar cuenta y elegir contraseña &rarr;')}
          <p style="margin:14px 0 0 0;font-size:13px;color:#7A7A7A;line-height:1.5;">Por seguridad, este enlace tiene una validez limitada. Si ya no funciona, entrá al portal y usá el enlace «¿Olvidaste tu contraseña?» para recibir uno nuevo.</p>`;
}

function buildActivationText(email, link, portalUrl) {
  return (
    `Portal de Informes — Equipos Consultores\n\n` +
    `Te damos la bienvenida. Tu usuario es: ${email}\n\n` +
    `Activá tu cuenta y elegí tu contraseña acá:\n${link}\n\n` +
    `Por seguridad el enlace tiene validez limitada. Si ya no funciona, entrá a ${portalUrl} y usá «¿Olvidaste tu contraseña?».`
  );
}

// ── Helpers de datos ──────────────────────────────────────────────────────────

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

/**
 * Genera el enlace de activación (= elegí tu contraseña) con el Admin SDK.
 * Intenta con la continue URL al portal; si el dominio no está autorizado en
 * Firebase Auth, reintenta sin ella para no bloquear el alta.
 */
async function generateActivationLink(email) {
  const settings = { url: PORTAL_URL.value() };
  try {
    return await admin.auth().generatePasswordResetLink(email, settings);
  } catch (e) {
    logger.warn(
      `Enlace con continue URL falló (${e.code || e.message}); reintento sin ella.`
    );
    return await admin.auth().generatePasswordResetLink(email);
  }
}

// ── Triggers ──────────────────────────────────────────────────────────────────

exports.notifyNewReportAccess = onDocumentWritten(
  { document: 'userAccess/{uid}', region: REGION },
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
        html: emailShell(buildReportContent(names, portalUrl)),
        text: buildReportText(names, portalUrl),
      },
    });

    logger.info(`Aviso de acceso encolado para ${email}`, {
      uid,
      reportIds: added,
    });
  }
);

exports.sendAccountActivation = onDocumentCreated(
  { document: 'users/{uid}', region: REGION },
  async (event) => {
    const snap = event.data;
    if (!snap) return;
    const data = snap.data() || {};
    const uid = event.params.uid;
    const email = (data.email || '').trim();

    if (!email) {
      logger.warn(`users/${uid} sin email; no se envía activación.`);
      return;
    }
    // Los admins se dan de alta a mano en la consola: no reciben activación.
    if (data.role === 'admin') {
      logger.info(`users/${uid} es admin; se omite el correo de activación.`);
      return;
    }

    let link;
    try {
      link = await generateActivationLink(email);
    } catch (e) {
      // p. ej. la cuenta de Auth aún no existe (USER_NOT_FOUND). No reintentamos.
      logger.error(
        `No se pudo generar el enlace de activación para ${email}: ${e.code || e.message}`
      );
      return;
    }

    await db.collection(MAIL_COLLECTION.value()).add({
      to: [email],
      message: {
        subject: 'Activá tu cuenta del Portal de Informes',
        html: emailShell(buildActivationContent(email, link)),
        text: buildActivationText(email, link, PORTAL_URL.value()),
      },
    });

    logger.info(`Activación encolada para ${email}`, { uid });
  }
);
