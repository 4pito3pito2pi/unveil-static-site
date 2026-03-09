// decrypt.js — paste into browser console to decrypt an encrypted HTML document
// Works on any page encrypted with encrypt-html.py
// Passphrase is typed into a prompt() — never sent anywhere.
// Uses native Web Crypto API — no external libraries.

(async () => {
  const el = document.getElementById('enc');
  if (!el) { console.error('No encrypted content found (#enc element missing).'); return; }

  const b64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
  const salt = b64(el.dataset.salt);
  const iv   = b64(el.dataset.iv);
  const ct   = b64(el.dataset.ct);
  const iter = parseInt(el.dataset.iter) || 260000;

  const passphrase = prompt('Passphrase:');
  if (!passphrase) return;

  try {
    const enc  = new TextEncoder();
    const raw  = await crypto.subtle.importKey(
      'raw', enc.encode(passphrase), 'PBKDF2', false, ['deriveKey']
    );
    const key  = await crypto.subtle.deriveKey(
      { name: 'PBKDF2', salt, iterations: iter, hash: 'SHA-256' },
      raw,
      { name: 'AES-GCM', length: 256 },
      false,
      ['decrypt']
    );
    const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, key, ct);
    const html  = new TextDecoder().decode(plain);

    // Replace page content with decrypted HTML
    document.open();
    document.write(html);
    document.close();

  } catch (e) {
    console.error('Decryption failed — wrong passphrase or corrupted data.');
    console.error(e);
  }
})();
