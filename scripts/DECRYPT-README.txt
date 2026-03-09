Decrypting Downloaded Files
===========================

All files on this site are encrypted with AES-256-GCM + PBKDF2-SHA256.

HTML files (.html) have an embedded decryptor — open in a browser and
enter the passphrase to view.

Binary files (.enc) must be decrypted offline:

  python3 decrypt.py paper.pdf.enc
  python3 decrypt.py paper.pdf.enc -o output.pdf

Requirements: python3, cryptography module (pip install cryptography)

Verifying GPG signatures:

  gpg --import pubkey.asc
  gpg --verify paper.pdf.enc.sig paper.pdf.enc

The .enc format is JSON containing:
  salt     32-byte random salt (base64)
  iv       12-byte random IV (base64)
  ct       ciphertext + 16-byte GCM auth tag (base64)
  iter     PBKDF2 iteration count (260000)
  filename original filename
