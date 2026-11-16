"""Password-protected PDFs (docs/TECH_UPGRADE_PLAN.md, E5).

AES-256 with the PDF 2.0 key derivation (security handler revision 6, as
in ISO 32000-2). The older AES-256 revision 5, which reportlab offers, has
a password check weak enough to brute-force quickly, so it is not used.
The PDF is written as usual and encrypted afterwards with pypdf
(BSD-3-Clause) on the `cryptography` backend (Apache-2.0 / BSD).

* The password is needed to open the file; printing and copying stay
  allowed once it is open (the owner password is a separate random value,
  so nobody can change the permissions without re-creating the file).
* PDF/A forbids encryption, so the archive preset cannot have a password.
* The password is never written to disk, logs or run records.
"""
from __future__ import annotations

import os
import secrets
from typing import Optional

MIN_LENGTH = 6
MAX_LENGTH = 127  # revision 6 uses the first 127 UTF-8 bytes


class PasswordError(ValueError):
    """The password cannot be used (message is user-facing)."""


def check_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < MIN_LENGTH:
        raise PasswordError(f"Use a password of at least {MIN_LENGTH} characters.")
    if len(password.encode("utf-8")) > MAX_LENGTH:
        raise PasswordError("That password is too long; use at most 127 bytes.")
    if any(ord(c) < 32 for c in password):
        raise PasswordError("The password cannot contain control characters.")
    return password


def protect_pdf(src: str, dst: str, password: str, title: Optional[str] = None) -> str:
    """Write an AES-256 (R6) encrypted copy of `src` to `dst` (may be `src`)."""
    from pypdf import PdfReader, PdfWriter

    check_password(password)
    reader = PdfReader(src)
    if reader.is_encrypted:
        raise PasswordError("This PDF is already protected.")
    writer = PdfWriter(clone_from=reader)
    if title and not (reader.metadata or {}).get("/Title"):
        writer.add_metadata({"/Title": title})
    # Remove PDF/A claims: an encrypted file cannot conform.
    root = writer._root_object  # noqa: SLF001 - pypdf exposes the catalog this way
    for key in ("/Metadata", "/OutputIntents"):
        if key in root:
            del root[key]
    writer.encrypt(user_password=password, owner_password=secrets.token_urlsafe(32),
                   algorithm="AES-256")
    part = dst + ".part"
    try:
        with open(part, "wb") as f:
            writer.write(f)
        os.replace(part, dst)
    finally:
        if os.path.exists(part):
            os.remove(part)
    return dst
