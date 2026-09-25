"""Interfaz local para validar y calcular propuestas de fianzas."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .quote import QuoteError, calculate_quote, extract_quote_snapshot, load_policy


def main() -> int:
    parser = argparse.ArgumentParser(description="Cálculo determinista de precotizaciones GPI")
    parser.add_argument("policy", type=Path, help="archivo JSON local con parámetros comerciales")
    parser.add_argument("proposal", type=Path, help="propuesta JSON o respuesta de agente en texto")
    parser.add_argument("mode", nargs="?", choices=("proposal", "agent-reply"), default="proposal",
                        help="usar agent-reply para extraer gpi_quote_snapshot")
    args = parser.parse_args()
    try:
        policy = load_policy(args.policy)
        content = args.proposal.read_text(encoding="utf-8")
        if args.mode == "agent-reply":
            visible, proposal = extract_quote_snapshot(content)
        else:
            visible, proposal = "", json.loads(content)
        result = calculate_quote(proposal, policy)
    except (OSError, json.JSONDecodeError, QuoteError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"respuesta_visible": visible, "precotizacion": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
