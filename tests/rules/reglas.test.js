// Tests de las reglas de Firestore y Storage (cierre de acceso a informes).
// Se corren con `npm test` en esta carpeta: levanta los emuladores de Firestore
// y Storage (firebase emulators:exec, con el firebase.json de la raíz) y corre
// este archivo con node --test.
import { test, before, after } from 'node:test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { initializeTestEnvironment, assertFails, assertSucceeds } from '@firebase/rules-unit-testing';

const raiz = fileURLToPath(new URL('../../', import.meta.url));
const PROJECT = 'demo-portal-informes';
let env;

// admin: rol admin. cli: tiene asignados X y Z (Z es un archivo viejo sin
// etiqueta). nada: usuario sin doc userAccess.
const BYTES = new TextEncoder().encode('<h1>informe</h1>');

before(async () => {
  env = await initializeTestEnvironment({
    projectId: PROJECT,
    firestore: { rules: readFileSync(raiz + 'firestore.rules', 'utf8'), host: '127.0.0.1', port: 8080 },
    storage: { rules: readFileSync(raiz + 'storage.rules', 'utf8'), host: '127.0.0.1', port: 9199 },
  });
  await env.clearFirestore();
  await env.clearStorage();
  await env.withSecurityRulesDisabled(async (ctx) => {
    const db = ctx.firestore();
    await db.doc('users/admin').set({ email: 'admin@x.uy', role: 'admin' });
    await db.doc('users/cli').set({ email: 'cli@x.uy', role: 'user' });
    await db.doc('users/nada').set({ email: 'nada@x.uy', role: 'user' });
    await db.doc('userAccess/cli').set({ reportIds: ['X', 'Z'] });
    for (const id of ['X', 'Y', 'Z']) {
      await db.doc(`reports/${id}`).set({ name: `${id}.html`, storagePath: `reports/${id}.html` });
    }
    await db.doc('publicLinks/tok1').set({ reportId: 'X', name: 'X.html', url: 'https://ejemplo', enabled: true, hitCount: 0 });
    const st = ctx.storage();
    await st.ref('reports/X.html').put(BYTES, { contentType: 'text/html', customMetadata: { reportId: 'X' } });
    await st.ref('reports/Y.html').put(BYTES, { contentType: 'text/html', customMetadata: { reportId: 'Y' } });
    await st.ref('reports/Z.html').put(BYTES, { contentType: 'text/html' });   // sin etiqueta
  });
});

after(async () => { if (env) await env.cleanup(); });

const como = (uid) => uid ? env.authenticatedContext(uid) : env.unauthenticatedContext();

// ── Storage (A4) ──
test('Storage: el cliente lee el informe asignado (X)', async () => {
  const ref = como('cli').storage().ref('reports/X.html');
  await assertSucceeds(ref.getMetadata());
  await assertSucceeds(ref.getDownloadURL());
});

test('Storage: el cliente NO lee un informe no asignado (Y)', async () => {
  const ref = como('cli').storage().ref('reports/Y.html');
  await assertFails(ref.getMetadata());
  await assertFails(ref.getDownloadURL());
});

test('Storage: el cliente NO lee un archivo asignado pero sin etiqueta (Z)', async () => {
  await assertFails(como('cli').storage().ref('reports/Z.html').getDownloadURL());
});

test('Storage: un usuario sin doc userAccess no lee nada', async () => {
  const st = como('nada').storage();
  await assertFails(st.ref('reports/X.html').getDownloadURL());
  await assertFails(st.ref('reports/Y.html').getDownloadURL());
});

test('Storage: sin login no se lee nada', async () => {
  await assertFails(como(null).storage().ref('reports/X.html').getDownloadURL());
});

test('Storage: el admin lee todo, también lo que no tiene etiqueta', async () => {
  const st = como('admin').storage();
  for (const p of ['X', 'Y', 'Z']) await assertSucceeds(st.ref(`reports/${p}.html`).getDownloadURL());
});

test('Storage: el admin sube, reescribe y borra; el cliente no escribe', async () => {
  const st = como('admin').storage();
  await assertSucceeds(st.ref('reports/N.html').put(BYTES, { customMetadata: { reportId: 'N' } }));
  await assertSucceeds(st.ref('reports/N.html').put(BYTES, { customMetadata: { reportId: 'N' } }));
  await assertSucceeds(st.ref('reports/N.html').delete());
  await assertFails(como('cli').storage().ref('reports/X.html').put(BYTES, { customMetadata: { reportId: 'X' } }));
  await assertFails(como('cli').storage().ref('reports/X.html').delete());
});

// ── Firestore: reports (A5) ──
test('Firestore: el cliente obtiene (get) su informe asignado', async () => {
  await assertSucceeds(como('cli').firestore().doc('reports/X').get());
});

test('Firestore: el cliente NO obtiene un informe no asignado', async () => {
  await assertFails(como('cli').firestore().doc('reports/Y').get());
});

test('Firestore: el cliente NO puede listar reports', async () => {
  await assertFails(como('cli').firestore().collection('reports').get());
});

test('Firestore: un usuario sin doc userAccess no obtiene ningún informe', async () => {
  await assertFails(como('nada').firestore().doc('reports/X').get());
});

test('Firestore: el admin lista y escribe reports', async () => {
  const db = como('admin').firestore();
  await assertSucceeds(db.collection('reports').get());
  await assertSucceeds(db.doc('reports/Y').get());
  await assertSucceeds(db.doc('reports/Y').update({ size: 1 }));
  await assertFails(como('cli').firestore().doc('reports/X').update({ size: 1 }));
});

// ── Firestore: publicLinks (A6) ──
test('Firestore: cualquiera sin login obtiene un enlace público por su token', async () => {
  await assertSucceeds(como(null).firestore().doc('publicLinks/tok1').get());
});

test('Firestore: nadie salvo el admin lista publicLinks', async () => {
  await assertFails(como(null).firestore().collection('publicLinks').get());
  await assertFails(como('cli').firestore().collection('publicLinks').get());
  await assertSucceeds(como('admin').firestore().collection('publicLinks').get());
});

test('Firestore: el visitante solo suma 1 al contador del enlace', async () => {
  const FieldValue = (await import('firebase/compat/app')).default.firestore.FieldValue;
  const db = como(null).firestore();
  await assertSucceeds(db.doc('publicLinks/tok1').update({ hitCount: FieldValue.increment(1), lastAccessAt: FieldValue.serverTimestamp() }));
  await assertFails(db.doc('publicLinks/tok1').update({ url: 'https://otra' }));
});
