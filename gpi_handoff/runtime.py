"""Customer-owned local runtime for drafting GPI quote proposals.

The runtime deliberately has no hosted control plane.  It stores its SQLite
database and received documents on the machine selected by the operator.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sqlite3
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib import error, request
from urllib.parse import urlsplit

from .quote import QuoteError, calculate_quote, extract_quote_snapshot, load_policy


MAX_DOCUMENT_BYTES = 10 * 1024 * 1024


class RuntimeError(ValueError):
    """The local runtime cannot complete the requested operation."""


class Model(Protocol):
    def propose(self, contract_text: str) -> tuple[str, dict[str, Any]]: ...


def _now() -> int:
    return int(time.time())


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return cleaned[:100] or "contrato.pdf"


def _normalize_contract_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


class LocalStore:
    """A small SQLite audit trail, owned and retained by the customer."""

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.documents_dir = self.data_dir / "documents"
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.documents_dir.mkdir(exist_ok=True, mode=0o700)
        os.chmod(self.data_dir, 0o700)
        os.chmod(self.documents_dir, 0o700)
        self.db_path = self.data_dir / "gpi-local.sqlite3"
        self._init_db()
        os.chmod(self.db_path, 0o600)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY, created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, conversation_id TEXT NOT NULL,
                    created_at INTEGER NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL
                );
            """)

    def create_conversation(self) -> str:
        conversation_id = str(uuid.uuid4())
        with self._connect() as db:
            db.execute("INSERT INTO conversations VALUES (?, ?)", (conversation_id, _now()))
        return conversation_id

    def exists(self, conversation_id: str) -> bool:
        with self._connect() as db:
            return db.execute("SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)).fetchone() is not None

    def record(self, conversation_id: str, kind: str, payload: dict[str, Any]) -> None:
        if not self.exists(conversation_id):
            raise RuntimeError("Conversación no encontrada")
        with self._connect() as db:
            db.execute("INSERT INTO events (conversation_id, created_at, kind, payload) VALUES (?, ?, ?, ?)",
                       (conversation_id, _now(), kind, json.dumps(payload, ensure_ascii=False)))

    def history(self, conversation_id: str) -> list[dict[str, Any]]:
        if not self.exists(conversation_id):
            raise RuntimeError("Conversación no encontrada")
        with self._connect() as db:
            rows = db.execute("SELECT created_at, kind, payload FROM events WHERE conversation_id = ? ORDER BY id",
                              (conversation_id,)).fetchall()
        return [{"created_at": row["created_at"], "kind": row["kind"], "payload": json.loads(row["payload"])} for row in rows]

    def save_pdf(self, conversation_id: str, filename: str, encoded: str) -> tuple[Path, str]:
        if not self.exists(conversation_id):
            raise RuntimeError("Conversación no encontrada")
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise RuntimeError("El PDF codificado no es válido") from exc
        if not content.startswith(b"%PDF-"):
            raise RuntimeError("El archivo debe ser un PDF")
        if not content or len(content) > MAX_DOCUMENT_BYTES:
            raise RuntimeError("El PDF supera el límite de 10 MB")
        target = self.documents_dir / f"{conversation_id}-{_safe_filename(filename)}"
        target.write_bytes(content)
        os.chmod(target, 0o600)
        return target, _extract_pdf_text(content)


def _extract_pdf_text(content: bytes) -> str:
    """Use an optional local pdftotext command; never send the PDF elsewhere."""
    try:
        result = subprocess.run(["pdftotext", "-", "-"], input=content, capture_output=True,
                                timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode:
        return ""
    return result.stdout.decode("utf-8", errors="replace").strip()


@dataclass(frozen=True)
class OpenAIResponsesModel:
    """Small BYOK adapter for an OpenAI Responses-compatible endpoint.

    It is intentionally optional: constructing the local runtime does not
    create this adapter unless the operator explicitly selects it in the
    environment.
    """
    base_url: str
    api_key: str
    model: str
    timeout_seconds: int = 45

    def __post_init__(self) -> None:
        if not self.base_url or not self.api_key or not self.model:
            raise RuntimeError("Configure GPI_MODEL_BASE_URL, GPI_MODEL_API_KEY y GPI_MODEL_NAME para usar el modelo")
        try:
            parsed = urlsplit(self.base_url)
            host = parsed.hostname
            port = parsed.port
        except ValueError as exc:
            raise RuntimeError("GPI_MODEL_BASE_URL no es una URL válida") from exc
        if (parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username is not None or
                parsed.password is not None or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
            raise RuntimeError("GPI_MODEL_BASE_URL debe ser una URL base sin usuario, ruta, consulta ni fragmento")
        if parsed.scheme == "http" and host not in ("localhost", "127.0.0.1"):
            raise RuntimeError("GPI_MODEL_BASE_URL debe usar HTTPS o un proveedor local")
        object.__setattr__(self, "base_url", f"{parsed.scheme}://{parsed.netloc}")

    def propose(self, contract_text: str) -> tuple[str, dict[str, Any]]:
        prompt = (
            "Extrae una propuesta de fianzas exclusivamente del contrato siguiente. No inventes datos. "
            "Devuelve una respuesta breve para el operador y exactamente un bloque "
            "<gpi_quote_snapshot>{...}</gpi_quote_snapshot> con contratista, beneficiario, objeto y fianzas. "
            "Cada fianza requiere tipo, monto, vigencia_meses y fuente literal.\n\nCONTRATO:\n" + contract_text
        )
        body = json.dumps({"model": self.model, "input": prompt}).encode("utf-8")
        endpoint = self.base_url.rstrip("/") + "/v1/responses"
        req = request.Request(endpoint, data=body, method="POST", headers={
            "Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json",
        })
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
            raw = _response_text(payload)
        except (error.URLError, OSError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"El proveedor no devolvió una propuesta utilizable: {exc}") from None
        if not isinstance(raw, str):
            raise RuntimeError("El proveedor devolvió contenido no textual")
        try:
            return extract_quote_snapshot(raw)
        except QuoteError as exc:
            raise RuntimeError(f"La respuesta del proveedor no contiene un snapshot válido: {exc}") from None


def _response_text(payload: dict[str, Any]) -> str:
    """Read text from the official Responses shape without trusting one index."""
    if not isinstance(payload, dict):
        raise RuntimeError("El proveedor devolvió una respuesta no válida")
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    pieces: list[str] = []
    for output in payload.get("output", []):
        if not isinstance(output, dict):
            continue
        for content in output.get("content", []):
            if isinstance(content, dict) and content.get("type") == "output_text" and isinstance(content.get("text"), str):
                pieces.append(content["text"])
    result = "".join(pieces)
    if not result:
        raise RuntimeError("El proveedor no devolvió texto de salida")
    return result


class QuoteRuntime:
    def __init__(self, policy_path: str | Path, data_dir: str | Path, model: Model | None = None):
        self.policy_path = Path(policy_path)
        self.store = LocalStore(data_dir)
        self.model = model

    def add_contract_text(self, conversation_id: str, text: str) -> None:
        text = text.strip()
        if not text:
            raise RuntimeError("Incluya el texto del contrato")
        if len(text) > 250_000:
            raise RuntimeError("El texto del contrato supera el límite permitido")
        self.store.record(conversation_id, "contract_text", {"text": text})

    def add_pdf(self, conversation_id: str, filename: str, pdf_base64: str) -> dict[str, str]:
        path, extracted = self.store.save_pdf(conversation_id, filename, pdf_base64)
        self.store.record(conversation_id, "contract_pdf", {"filename": path.name, "extracted_text": extracted})
        return {"filename": path.name, "extracted_text": extracted}

    def _contract_text(self, conversation_id: str) -> str:
        events = self.store.history(conversation_id)
        pieces = [event["payload"].get("text") or event["payload"].get("extracted_text", "")
                  for event in events if event["kind"] in ("contract_text", "contract_pdf")]
        text = "\n\n".join(piece for piece in pieces if piece)
        if not text:
            raise RuntimeError("No hay texto de contrato. Pegue el texto o cargue un PDF con texto seleccionable.")
        return text

    def submit_proposal(self, conversation_id: str, proposal: dict[str, Any], visible: str = "") -> dict[str, Any]:
        result = calculate_quote(proposal, load_policy(self.policy_path))
        draft = {"respuesta_visible": visible.strip(), "precotizacion": result,
                 "estado": "revision_humana_obligatoria", "accion_final": "bloqueada"}
        self.store.record(conversation_id, "quote_draft", draft)
        return draft

    @staticmethod
    def _ensure_model_sources_are_anchored(proposal: dict[str, Any], contract_text: str) -> None:
        normalized_contract = _normalize_contract_text(contract_text)
        rows = proposal.get("fianzas") if isinstance(proposal, dict) else None
        if not isinstance(rows, list):
            raise RuntimeError("La propuesta del modelo no contiene fianzas")
        for position, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                raise RuntimeError(f"Fianza {position} inválida en la propuesta del modelo")
            source = str(row.get("fuente") or row.get("clausula") or "")
            if not source or _normalize_contract_text(source) not in normalized_contract:
                raise RuntimeError(f"La fuente de la fianza {position} no aparece en el contrato almacenado")

    def propose_with_model(self, conversation_id: str) -> dict[str, Any]:
        if self.model is None:
            raise RuntimeError("No hay proveedor configurado. Envíe una propuesta estructurada para calcularla localmente.")
        contract_text = self._contract_text(conversation_id)
        visible, proposal = self.model.propose(contract_text)
        self._ensure_model_sources_are_anchored(proposal, contract_text)
        self.store.record(conversation_id, "model_proposal", {"visible": visible, "proposal": proposal})
        return self.submit_proposal(conversation_id, proposal, visible)


def model_from_environment(environment: dict[str, str] | None = None) -> Model | None:
    env = environment if environment is not None else os.environ
    provider = env.get("GPI_MODEL_PROVIDER", "").strip()
    if not provider:
        return None
    if provider != "openai_responses":
        raise RuntimeError("GPI_MODEL_PROVIDER solo admite openai_responses")
    return OpenAIResponsesModel(env.get("GPI_MODEL_BASE_URL", ""), env.get("GPI_MODEL_API_KEY", ""),
                                env.get("GPI_MODEL_NAME", ""))
