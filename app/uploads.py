"""Upload type detection and safe text extraction for PDF, DOCX and plain text / CSV.

Uploaded files are untrusted. Defences, all covered by tests:
* the type is decided from the file's BYTES; the declared content type and extension are only
  hints and can never turn an unrecognised file into an accepted one;
* hard size caps (see config.py), a page cap for PDFs and zip-bomb checks for DOCX;
* parsing runs in a short-lived child process with a wall-clock timeout and a memory limit, so a
  hostile or pathological file cannot hang or exhaust the web worker;
* nothing is written to disk or logged, and the extracted text is only ever handed to the model
  as DATA inside a JSON field, never as instructions.

No OCR: a scanned PDF with no text layer is refused with a clear message (upload it as an image).
"""

from __future__ import annotations

import io
import multiprocessing as mp
import zipfile
from typing import Any

from app.errors import DeskError

KINDS = ("image", "pdf", "docx", "text")
TEXT_EXTENSIONS = {".txt", ".csv", ".tsv", ".md", ".eml"}
MAX_PDF_PAGES = 20
MAX_DOCX_UNCOMPRESSED = 25 * 1024 * 1024
MAX_DOCX_ENTRIES = 2000
MAX_EXTRACTED_CHARS = 400_000  # parser-side ceiling; the prompt cap truncates much sooner
PARSE_TIMEOUT_SECONDS = 20
CHILD_MEMORY_LIMIT = 768 * 1024 * 1024

_IMAGE_MAGIC = [(b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg")]


def sniff_image(data: bytes) -> str | None:
    for magic, mime in _IMAGE_MAGIC:
        if data.startswith(magic):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _ext(filename: str) -> str:
    return ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""


def _looks_like_text(data: bytes) -> bool:
    head = data[:8192]
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
    except UnicodeDecodeError as exc:
        if exc.start < len(head) - 4:  # a character cut at the 8 KiB edge is fine
            return False
    return True


def detect(data: bytes, filename: str = "", content_type: str = "") -> tuple[str, str]:
    """Return (kind, mime) from the content. Raises DeskError(415) for anything else."""
    if (mime := sniff_image(data)) is not None:
        return "image", mime
    if data.startswith(b"%PDF-"):
        return "pdf", "application/pdf"
    if data.startswith(b"PK\x03\x04"):
        try:
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        except zipfile.BadZipFile:
            names = []
        if "word/document.xml" in names:
            return "docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        raise DeskError(415, "This zip file is not a Word (.docx) document.", "unsupported_file")
    if data.startswith(b"\xd0\xcf\x11\xe0"):
        raise DeskError(
            415,
            "Legacy .doc files are not supported. Save the file as .docx or PDF.",
            "unsupported_file",
        )
    ext, ct = _ext(filename), content_type.split(";")[0].strip().lower()
    declared_text = ext in TEXT_EXTENSIONS or ct in {
        "text/plain",
        "text/csv",
        "text/tab-separated-values",
        "text/markdown",
        "message/rfc822",
    }
    if declared_text and _looks_like_text(data):
        return "text", "text/plain"
    raise DeskError(
        415,
        "Accepted files: PNG, JPEG or WebP images, PDF, DOCX, and plain text or CSV.",
        "unsupported_file",
    )


# ------------------------------------------------------------------------------- extraction


def _pdf_text(data: bytes) -> dict[str, Any]:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        total = len(pdf.pages)
        parts = []
        size = 0
        for page in pdf.pages[:MAX_PDF_PAGES]:
            t = page.extract_text() or ""
            parts.append(t)
            size += len(t)
            if size > MAX_EXTRACTED_CHARS:
                break
    return {"text": "\n\n".join(parts), "pages": total, "pages_read": min(total, MAX_PDF_PAGES)}


def _docx_text(data: bytes) -> dict[str, Any]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        infos = z.infolist()
        if len(infos) > MAX_DOCX_ENTRIES or sum(i.file_size for i in infos) > MAX_DOCX_UNCOMPRESSED:
            raise ValueError("zip_bomb")
    from docx import Document

    doc = Document(io.BytesIO(data))
    lines = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            lines.append(" | ".join(c.text.strip() for c in row.cells))
    return {"text": "\n".join(lines)[:MAX_EXTRACTED_CHARS]}


def _plain_text(data: bytes) -> dict[str, Any]:
    return {"text": data.decode("utf-8", "replace").replace("\x00", "")[:MAX_EXTRACTED_CHARS]}


_WORKERS = {"pdf": _pdf_text, "docx": _docx_text, "text": _plain_text}


def _child(kind: str, data: bytes, conn: Any) -> None:
    try:
        try:
            import resource

            resource.setrlimit(resource.RLIMIT_AS, (CHILD_MEMORY_LIMIT, CHILD_MEMORY_LIMIT))
        except (ImportError, ValueError, OSError):
            pass  # not available on this platform: the timeout still applies
        conn.send(("ok", _WORKERS[kind](data)))
    except BaseException as exc:  # noqa: BLE001 - report any parser failure as a plain error kind
        conn.send(("error", "zip_bomb" if str(exc) == "zip_bomb" else type(exc).__name__))
    finally:
        conn.close()


def extract_text(kind: str, data: bytes) -> dict[str, Any]:
    """Extract text in a child process. Returns {"text": str, ...} or raises DeskError."""
    ctx = mp.get_context("spawn")
    recv, send = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_child, args=(kind, data, send), daemon=True)
    proc.start()
    send.close()
    try:
        if not recv.poll(PARSE_TIMEOUT_SECONDS):
            raise DeskError(
                422,
                f"The file took longer than {PARSE_TIMEOUT_SECONDS}s to read and was refused.",
                "parse_timeout",
            )
        try:
            status, payload = recv.recv()
        except EOFError:
            raise DeskError(
                422,
                "The file could not be read (the parser stopped unexpectedly).",
                "unreadable_file",
            ) from None
    finally:
        if proc.is_alive():
            proc.terminate()
        proc.join(2)
        recv.close()
    if status != "ok":
        if payload == "zip_bomb":
            raise DeskError(
                422, "This document is too large once unpacked and was refused.", "unreadable_file"
            )
        raise DeskError(
            422,
            f"The {kind.upper()} could not be read. It may be corrupt or password-protected.",
            "unreadable_file",
        )
    text = payload["text"].strip()
    if not text:
        raise DeskError(
            422,
            "No text was found in this file. For a scan or a photo, upload it as an image instead.",
            "no_text",
        )
    return {**payload, "text": text}


def fit_to_bytes(text: str, limit: int) -> tuple[str, bool]:
    """Truncate to at most `limit` UTF-8 bytes without splitting a character."""
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text, False
    return raw[:limit].decode("utf-8", "ignore").rstrip(), True
