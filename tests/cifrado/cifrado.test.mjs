// Tests del módulo de cifrado (OpenPGP simétrico, compatible con gpg).
// Correr con `npm test` en esta carpeta. Requiere Node 22+.
// Los tests de interoperabilidad usan `gpg` si está instalado (si no, se saltean).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import * as openpgp from '../../vendor/openpgp-6.3.2.min.mjs';
import {
  cifrar, tipoMensaje, esMensajeSimetrico, sessionKeyDesdePassword, descifrar, descifrarConPassword,
  sessionKeyAFragmento, fragmentoASessionKey, sessionKeyAGpg, generarClave,
} from '../../cifrado.js';

const enc = new TextEncoder();
const HTML = enc.encode('<!doctype html><h1>Informe confidencial ñ</h1>');
const CLAVE = 'una clave larga y segura';

// Cada derivación S2K (65M de iteraciones) tarda; el archivo base se cifra una sola vez.
const base = await cifrar(HTML, { password: CLAVE, filename: 'informe.html' });

test('el archivo es OpenPGP simétrico y no contiene el texto plano', async () => {
  assert.equal(await tipoMensaje(base.bytes), 'simetrico');
  assert.equal(await esMensajeSimetrico(base.bytes), true);
  assert.ok(!Buffer.from(base.bytes).toString('latin1').includes('confidencial'));
  assert.equal(base.sessionKey.algorithm, 'aes256');
  assert.equal(base.sessionKey.data.length, 32);
});

test('ida y vuelta con la contraseña (devuelve nombre y clave de sesión)', async () => {
  const r = await descifrarConPassword(base.bytes, CLAVE);
  assert.deepEqual(r.bytes, HTML);
  assert.equal(r.filename, 'informe.html');
  assert.deepEqual(r.sessionKey.data, base.sessionKey.data);
  assert.deepEqual((await sessionKeyDesdePassword(base.bytes, CLAVE)).data, base.sessionKey.data);
});

test('ida y vuelta con la clave de sesión y con el fragmento', async () => {
  assert.deepEqual((await descifrar(base.bytes, base.sessionKey)).bytes, HTML);
  const frag = sessionKeyAFragmento(base.sessionKey);
  assert.deepEqual((await descifrar(base.bytes, fragmentoASessionKey(frag))).bytes, HTML);
});

test('contraseña incorrecta ⇒ clave-incorrecta', async () => {
  await assert.rejects(sessionKeyDesdePassword(base.bytes, 'otra clave cualquiera'), { code: 'clave-incorrecta' });
  await assert.rejects(descifrarConPassword(base.bytes, 'otra clave cualquiera'), { code: 'clave-incorrecta' });
});

test('clave de sesión incorrecta ⇒ error', async () => {
  await assert.rejects(descifrar(base.bytes, { data: new Uint8Array(32).fill(7), algorithm: 'aes256' }), { code: 'descifrado' });
});

test('un byte alterado ⇒ error de integridad', async () => {
  const b = base.bytes.slice();
  b[b.length - 10] ^= 0x01;
  await assert.rejects(descifrar(b, base.sessionKey), { code: 'descifrado' });
});

test('reescritura con la misma clave de sesión ⇒ abre con el mismo fragmento y la misma contraseña', async () => {
  const frag = sessionKeyAFragmento(base.sessionKey);
  const nuevo = enc.encode('<h1>versión 2</h1>');
  const r = await cifrar(nuevo, { password: CLAVE, filename: 'informe.html', sessionKey: base.sessionKey });
  assert.notDeepEqual(r.bytes, base.bytes);
  assert.deepEqual((await descifrar(r.bytes, fragmentoASessionKey(frag))).bytes, nuevo);
  assert.deepEqual((await descifrarConPassword(r.bytes, CLAVE)).bytes, nuevo);
});

test('fragmentoASessionKey(sessionKeyAFragmento(x)) devuelve x; base64url sin + / =', () => {
  for (let i = 0; i < 200; i++) {
    const x = { data: crypto.getRandomValues(new Uint8Array(32)), algorithm: 'aes256' };
    const f = sessionKeyAFragmento(x);
    assert.match(f, /^9\.[A-Za-z0-9_-]+$/);
    assert.deepEqual(fragmentoASessionKey(f), x);
  }
  const x128 = { data: new Uint8Array(16).fill(1), algorithm: 'aes128' };
  assert.deepEqual(fragmentoASessionKey(sessionKeyAFragmento(x128)), x128);
  for (const malo of ['', 'abc', '9.corta', '99.AAAA', '9.' + 'A'.repeat(10)]) {
    assert.throws(() => fragmentoASessionKey(malo), { code: 'fragmento-invalido' });
  }
});

test('sessionKeyAGpg tiene el formato de gpg --show-session-key', () => {
  assert.match(sessionKeyAGpg(base.sessionKey), /^9:[0-9A-F]{64}$/);
});

test('esMensajeSimetrico rechaza un mensaje de clave pública y un archivo que no es OpenPGP', async () => {
  const { publicKey } = await openpgp.generateKey({ type: 'ecc', curve: 'curve25519Legacy', userIDs: [{ name: 'x', email: 'x@x.uy' }], format: 'object' });
  const pub = await openpgp.encrypt({ message: await openpgp.createMessage({ binary: HTML }), encryptionKeys: publicKey, format: 'binary' });
  assert.equal(await tipoMensaje(pub), 'clave-publica');
  assert.equal(await esMensajeSimetrico(pub), false);
  assert.equal(await tipoMensaje(HTML), 'no-openpgp');
  assert.equal(await esMensajeSimetrico(enc.encode('%PDF-1.4 hola')), false);
});

test('cifrar sin contraseña ⇒ error', async () => {
  await assert.rejects(cifrar(HTML, { filename: 'x.html' }), { code: 'sin-clave' });
});

test('generarClave: 20 caracteres útiles en grupos de 4', () => {
  const k = generarClave();
  assert.match(k, /^[A-Za-z2-9]{4}(-[A-Za-z2-9]{4}){4}$/);
  assert.notEqual(generarClave(), k);
});

// ── Interoperabilidad con gpg ──
const hayGpg = spawnSync('gpg', ['--version']).status === 0;
const gpgTest = (name, fn) => test(name, { skip: hayGpg ? false : 'gpg no está instalado' }, fn);

function conGpg(fn) {
  const dir = mkdtempSync(join(tmpdir(), 'gpg-test-'));
  const gpg = (...args) => execFileSync('gpg', ['--homedir', dir, '--batch', '--quiet', '--pinentry-mode', 'loopback', ...args], { stdio: ['ignore', 'pipe', 'pipe'] });
  try { return fn(gpg, dir); } finally { rmSync(dir, { recursive: true, force: true }); }
}

gpgTest('gpg descifra con la contraseña lo que cifra la librería', () => conGpg((gpg, dir) => {
  writeFileSync(join(dir, 'x.gpg'), base.bytes);
  assert.deepEqual(new Uint8Array(gpg('--passphrase', CLAVE, '-d', join(dir, 'x.gpg'))), HTML);
}));

gpgTest('gpg descifra con --override-session-key (original y reescrito)', async () => {
  const r = await cifrar(enc.encode('<h1>v2</h1>'), { password: CLAVE, filename: 'informe.html', sessionKey: base.sessionKey });
  conGpg((gpg, dir) => {
    writeFileSync(join(dir, 'a.gpg'), base.bytes);
    writeFileSync(join(dir, 'b.gpg'), r.bytes);
    const sk = sessionKeyAGpg(base.sessionKey);
    assert.deepEqual(new Uint8Array(gpg('--override-session-key', sk, '-d', join(dir, 'a.gpg'))), HTML);
    assert.equal(gpg('--override-session-key', sk, '-d', join(dir, 'b.gpg')).toString(), '<h1>v2</h1>');
  });
});

gpgTest('gpg --list-packets: symkey v4, cipher 9, aead 0, count 65011712', () => conGpg((gpg, dir) => {
  writeFileSync(join(dir, 'x.gpg'), base.bytes);
  // Sin la contraseña gpg sale con error al no poder descifrar, pero lista los paquetes igual.
  const out = spawnSync('gpg', ['--homedir', dir, '--batch', '--list-packets', join(dir, 'x.gpg')]).stdout.toString();
  assert.match(out, /symkey enc packet: version 4, cipher 9, aead 0/);
  assert.match(out, /count 65011712/);
}));

gpgTest('la librería descifra un gpg -c --cipher-algo AES256 (con contraseña y con clave de sesión)', async () => {
  const gpgBytes = conGpg((gpg, dir) => {
    writeFileSync(join(dir, 'informe.html'), HTML);
    gpg('--passphrase', CLAVE, '-c', '--cipher-algo', 'AES256', '--s2k-digest-algo', 'SHA256', '--s2k-count', '65011712',
        '-o', join(dir, 'informe.html.gpg'), join(dir, 'informe.html'));
    return new Uint8Array(readFileSync(join(dir, 'informe.html.gpg')));
  });
  assert.equal(await tipoMensaje(gpgBytes), 'simetrico');
  const r = await descifrarConPassword(gpgBytes, CLAVE);
  assert.deepEqual(r.bytes, HTML);
  assert.equal(r.filename, 'informe.html');
  assert.deepEqual((await descifrar(gpgBytes, fragmentoASessionKey(sessionKeyAFragmento(r.sessionKey)))).bytes, HTML);
  await assert.rejects(descifrarConPassword(gpgBytes, 'otra clave cualquiera'), { code: 'clave-incorrecta' });
});
