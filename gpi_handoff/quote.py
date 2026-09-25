"""Valida una propuesta de fianzas y calcula cada importe fuera del modelo.

Las tarifas se reciben en un archivo local administrado por Grupo GPI. Este
módulo no contiene tarifas comerciales, expedientes ni datos de clientes.
"""

from __future__ import annotations

import json
import math
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any


MONEY = Decimal("0.01")
SNAPSHOT = re.compile(r"<gpi_quote_snapshot>\s*(\{.*?\})\s*</gpi_quote_snapshot>", re.I | re.S)
PLACEHOLDER = re.compile(r"^(?:n/?a|no\s+(?:identificado|disponible|indicado)|pendiente|por\s+confirmar|\[.*\])$", re.I)
POLICY_KEYS = ("annual_rate", "min_prima", "derechos_rate", "gastos_tramite", "iva_rate")


class QuoteError(ValueError):
    """La propuesta o la política comercial no se puede validar."""


def _decimal(value: Any, name: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise QuoteError(f"{name} debe ser un número")
    try:
        result = Decimal(str(value).replace(",", "").replace("$", "").strip())
    except (InvalidOperation, ValueError):
        raise QuoteError(f"{name} debe ser un número") from None
    if not result.is_finite():
        raise QuoteError(f"{name} debe ser finito")
    return result


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def load_policy(path: str | Path) -> dict[str, Decimal | int]:
    """Lee una política privada. Falla si falta un parámetro."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QuoteError(f"No se pudo leer la política: {exc}") from exc
    if not isinstance(raw, dict):
        raise QuoteError("La política debe ser un objeto JSON")
    policy: dict[str, Decimal | int] = {}
    for key in POLICY_KEYS:
        if key not in raw:
            raise QuoteError(f"Falta el parámetro {key}")
        value = _decimal(raw[key], key)
        if value < 0:
            raise QuoteError(f"{key} no puede ser negativo")
        policy[key] = value
    if policy["annual_rate"] == 0 or policy["min_prima"] == 0:
        raise QuoteError("La tasa anual y la prima mínima deben ser mayores que cero")
    for key in ("annual_rate", "derechos_rate", "iva_rate"):
        if policy[key] > 1:
            raise QuoteError(f"{key} debe expresarse como fracción entre 0 y 1")
    months = raw.get("minimum_billable_months")
    if isinstance(months, bool) or not isinstance(months, int) or months < 1 or months > 120:
        raise QuoteError("minimum_billable_months debe ser un entero entre 1 y 120")
    policy["minimum_billable_months"] = months
    return policy


def _fianza_type(value: Any) -> str:
    raw = re.sub(r"\s+", " ", str(value or "").strip().lower())
    if "cumplimiento" in raw and ("vicios" in raw or "calidad" in raw):
        raise QuoteError("Separe cumplimiento y vicios en dos fianzas")
    for term, canonical in (
        ("anticipo", "Anticipo"),
        ("cumplimiento", "Cumplimiento"),
        ("vicios", "Vicios ocultos / buena calidad"),
        ("buena calidad", "Vicios ocultos / buena calidad"),
        ("laboral", "Obligaciones laborales y seguridad social"),
        ("obrero", "Obligaciones laborales y seguridad social"),
        ("seguridad social", "Obligaciones laborales y seguridad social"),
        ("fidelidad", "Fidelidad"),
        ("fiscal", "Fiscal"),
    ):
        if term in raw:
            return canonical
    if raw == "calidad":
        return "Vicios ocultos / buena calidad"
    raise QuoteError(f"Tipo de fianza no reconocido: {value}")


def _required_text(payload: dict[str, Any], key: str, label: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value or PLACEHOLDER.match(value):
        raise QuoteError(f"Falta {label} verificable en el contrato")
    return value


def calculate_quote(payload: dict[str, Any], policy: dict[str, Decimal | int]) -> dict[str, Any]:
    """Devuelve una precotización calculada y validada, sin emitir una fianza."""
    if not isinstance(payload, dict):
        raise QuoteError("La propuesta debe ser un objeto JSON")
    contractor = str(payload.get("contratista") or payload.get("empresa") or "").strip()
    if not contractor or PLACEHOLDER.match(contractor):
        raise QuoteError("Falta contratista verificable en el contrato")
    beneficiary = _required_text(payload, "beneficiario", "beneficiario")
    purpose = _required_text(payload, "objeto", "objeto del contrato")
    rows = payload.get("fianzas")
    if not isinstance(rows, list) or not rows:
        raise QuoteError("La propuesta debe contener fianzas")
    if len(rows) > 30:
        raise QuoteError("Demasiadas fianzas en una propuesta")
    seen: set[str] = set()
    calculated: list[dict[str, Any]] = []
    minimum_months = int(policy["minimum_billable_months"])
    for position, item in enumerate(rows, 1):
        if not isinstance(item, dict):
            raise QuoteError(f"Fianza {position} inválida")
        kind = _fianza_type(item.get("tipo"))
        if kind in seen:
            raise QuoteError(f"Fianza duplicada: {kind}")
        seen.add(kind)
        amount = _decimal(item.get("monto", item.get("monto_afianzado")), "monto")
        months_raw = _decimal(item.get("vigencia_meses"), "vigencia_meses")
        if amount <= 0 or months_raw <= 0 or months_raw > 120:
            raise QuoteError(f"Monto o vigencia inválidos para {kind}")
        source = str(item.get("fuente") or item.get("clausula") or "").strip()
        if len(source) < 12:
            raise QuoteError(f"Falta texto fuente para {kind}")
        if kind == "Obligaciones laborales y seguridad social" and not re.search(r"fianza|p[oó]liza|cauci[oó]n", source, re.I):
            raise QuoteError("La fianza laboral requiere una cláusula expresa de fianza")
        months = math.ceil(months_raw)
        billed = max(minimum_months, months)
        effective_rate = Decimal(policy["annual_rate"]) * Decimal(billed) / Decimal(12)
        calculated_premium = _money(amount * effective_rate)
        premium = _money(max(calculated_premium, Decimal(policy["min_prima"])))
        rights = _money(premium * Decimal(policy["derechos_rate"]))
        fees = _money(Decimal(policy["gastos_tramite"]))
        subtotal = _money(premium + rights + fees)
        tax = _money(subtotal * Decimal(policy["iva_rate"]))
        total = _money(subtotal + tax)
        calculated.append({
            "tipo": kind,
            "monto": str(_money(amount)),
            "vigencia_meses": months,
            "meses_cobrados": billed,
            "fuente": source,
            "tarifa_efectiva": str(effective_rate),
            "prima_calculada": str(calculated_premium),
            "prima": str(premium),
            "derechos": str(rights),
            "gastos_tramite": str(fees),
            "subtotal": str(subtotal),
            "iva": str(tax),
            "total": str(total),
        })
    return {
        "snapshot_version": 1,
        "contratista": contractor,
        "beneficiario": beneficiary,
        "objeto": purpose,
        "fianzas": calculated,
        "total_general": str(_money(sum((Decimal(row["total"]) for row in calculated), Decimal(0)))),
        "estado": "estimacion_sujeta_a_revision",
    }


def extract_quote_snapshot(raw_reply: str) -> tuple[str, dict[str, Any]]:
    """Separa un bloque estructurado de la respuesta visible al cliente."""
    if len(raw_reply) > 250_000:
        raise QuoteError("La respuesta excede el tamaño permitido")
    matches = list(SNAPSHOT.finditer(raw_reply))
    if len(matches) != 1:
        raise QuoteError("Se requiere un único bloque gpi_quote_snapshot")
    try:
        payload = json.loads(matches[0].group(1))
    except json.JSONDecodeError as exc:
        raise QuoteError(f"Snapshot JSON inválido: {exc.msg}") from exc
    visible = SNAPSHOT.sub("", raw_reply).strip()
    return visible, payload
