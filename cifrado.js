/* ══════════════════════════════════════════════
   Cifrado de informes con OpenPGP (cifrado simétrico, igual que `gpg -c`)
   El archivo en Storage es un mensaje OpenPGP binario estándar:
     SKESK v4 (tag 3)   clave de sesión cifrada con la contraseña (S2K iterado
                        con salt, SHA-256, count 65.011.712)
     SEIPD v1 (tag 18)  contenido cifrado con AES-256 + chequeo de integridad (MDC)
     Literal data       bytes del archivo + nombre original
   Se abre fuera del portal con `gpg -d` y la misma contraseña.

   El portal cifra con una CLAVE DE SESIÓN aleatoria (256 bits) y la contraseña
   solo cifra esa clave. Así el enlace público lleva la clave de sesión en el
   fragmento (#k=…) y no la contraseña, y reescribir el informe reutiliza la
   clave de sesión (el #k= sigue sirviendo).

   OpenPGP.js va incluido en el repo (vendor/), no desde un CDN: es la librería
   que maneja las claves. Este módulo se carga con import() solo cuando hace
   falta. Nada de lo que hay acá toca la red ni guarda claves.
══════════════════════════════════════════════ */
import * as openpgp from './vendor/openpgp-6.3.2.min.mjs';

// Compatible con gpg 2.2 y 2.4: SEIPD v1 (no AEAD) y S2K iterado (no Argon2).
const CFG = {
  aeadProtect: false,
  preferredSymmetricAlgorithm: openpgp.enums.symmetric.aes256,
  s2kIterationCountByte: 255,   // count 65.011.712; el default de la librería es más bajo
};

const LARGOS = { aes128: 16, aes192: 24, aes256: 32 };

// Errores con un código estable para que el portal muestre el mensaje adecuado.
function error(code, msg) { const e = new Error(msg); e.code = code; return e; }

function aleatorio(n) { const a = new Uint8Array(n); globalThis.crypto.getRandomValues(a); return a; }

function comoBytes(data) {
  if (data instanceof Uint8Array) return data;
  if (data instanceof ArrayBuffer) return new Uint8Array(data);
  if (ArrayBuffer.isView(data)) return new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
  throw error('formato', 'Contenido inválido.');
}

function aBase64url(bytes) {
  let s = '';
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
function deBase64url(s) {
  const b64 = String(s).replace(/-/g, '+').replace(/_/g, '/');
  const bin = atob(b64 + '='.repeat((4 - b64.length % 4) % 4));
  return Uint8Array.from(bin, c => c.charCodeAt(0));
}

async function leerMensaje(data) {
  try { return await openpgp.readMessage({ binaryMessage: comoBytes(data), config: CFG }); }
  catch (e) { throw error('formato', 'El archivo no es un mensaje OpenPGP.'); }
}

/* Cifra un archivo. opciones: { password, filename, sessionKey? }
   - Archivo nuevo: se genera una clave de sesión AES-256 aleatoria.
   - Reescritura: sessionKey del informe actual (+ la misma contraseña), así el
     #k= del enlace público sigue sirviendo.
   Devuelve { bytes, sessionKey } (sessionKey: { data: Uint8Array, algorithm }). */
export async function cifrar(data, { password, filename, sessionKey } = {}) {
  if (!password) throw error('sin-clave', 'Falta la clave del informe.');
  const sk = sessionKey || { data: aleatorio(32), algorithm: 'aes256' };
  const message = await openpgp.createMessage({ binary: comoBytes(data), filename: filename || '', format: 'binary' });
  const bytes = await openpgp.encrypt({ message, passwords: [password], sessionKey: sk, format: 'binary', config: CFG });
  return { bytes, sessionKey: sk };
}

// 'simetrico' (al menos un SKESK: se abre con contraseña), 'clave-publica'
// (solo cifrado para claves GPG) o 'no-openpgp'.
export async function tipoMensaje(data) {
  let msg;
  try { msg = await leerMensaje(data); } catch (e) { return 'no-openpgp'; }
  const tags = msg.packets.map(p => p.constructor.tag);
  if (tags.includes(openpgp.enums.packet.symEncryptedSessionKey)) return 'simetrico';
  if (tags.includes(openpgp.enums.packet.publicKeyEncryptedSessionKey)) return 'clave-publica';
  return 'no-openpgp';
}
export async function esMensajeSimetrico(data) { return (await tipoMensaje(data)) === 'simetrico'; }

// Clave de sesión a partir de la contraseña. Con un `gpg -c` hecho en local la
// clave de sesión se deriva directo de la contraseña, así que una contraseña
// incorrecta recién se detecta al descifrar: para validarla, usar
// descifrarConPassword.
export async function sessionKeyDesdePassword(data, password) {
  const message = await leerMensaje(data);
  try {
    const [sk] = await openpgp.decryptSessionKeys({ message, passwords: [password], config: CFG });
    return { data: sk.data, algorithm: sk.algorithm };
  } catch (e) {
    throw error('clave-incorrecta', 'Clave incorrecta.');
  }
}

// Descifra con la clave de sesión. Devuelve { bytes, filename }.
export async function descifrar(data, sessionKey) {
  const message = await leerMensaje(data);
  try {
    const r = await openpgp.decrypt({ message, sessionKeys: sessionKey, format: 'binary', config: CFG });
    return { bytes: r.data, filename: r.filename || '' };
  } catch (e) {
    throw error('descifrado', 'No se pudo descifrar: la clave no corresponde o el archivo fue alterado.');
  }
}

// Contraseña → { bytes, filename, sessionKey }. Cualquier falla con la
// contraseña se informa como 'clave-incorrecta'.
export async function descifrarConPassword(data, password) {
  const sessionKey = await sessionKeyDesdePassword(data, password);
  try { return { ...(await descifrar(data, sessionKey)), sessionKey }; }
  catch (e) { throw error('clave-incorrecta', 'Clave incorrecta.'); }
}

// #k=<id de algoritmo>.<clave en base64url>, p. ej. 9.Hi3Jyk… (9 = AES-256):
// el mismo dato que `gpg --show-session-key` (9:1E2DC9…), en base64url.
export function sessionKeyAFragmento(sk) {
  return `${openpgp.enums.write(openpgp.enums.symmetric, sk.algorithm)}.${aBase64url(sk.data)}`;
}
export function fragmentoASessionKey(frag) {
  const m = /^(\d+)\.([A-Za-z0-9_-]+)$/.exec(String(frag || ''));
  let algorithm = null, data = null;
  if (m) {
    try { algorithm = openpgp.enums.read(openpgp.enums.symmetric, Number(m[1])); data = deBase64url(m[2]); } catch (e) {}
  }
  if (!algorithm || !LARGOS[algorithm] || !data || data.length !== LARGOS[algorithm]) {
    throw error('fragmento-invalido', 'La clave del enlace no es válida.');
  }
  return { data, algorithm };
}

// Para `gpg --override-session-key '9:<HEX>' -d archivo.gpg`.
export function sessionKeyAGpg(sk) {
  const hex = Array.from(sk.data, b => b.toString(16).padStart(2, '0')).join('').toUpperCase();
  return `${openpgp.enums.write(openpgp.enums.symmetric, sk.algorithm)}:${hex}`;
}

// Clave sugerida: 20 caracteres sin ambiguos (0/O, 1/l/I), en grupos de 4.
export function generarClave() {
  const alfabeto = 'abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  const lim = 256 - (256 % alfabeto.length);   // evita sesgo de módulo
  let s = '';
  while (s.length < 20) {
    for (const b of aleatorio(32)) { if (b < lim && s.length < 20) s += alfabeto[b % alfabeto.length]; }
  }
  return s.match(/.{4}/g).join('-');
}
