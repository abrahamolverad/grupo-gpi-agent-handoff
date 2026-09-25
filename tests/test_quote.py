import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from gpi_handoff.quote import QuoteError, calculate_quote, extract_quote_snapshot, load_policy


POLICY = {
    "annual_rate": Decimal("0.02"),
    "min_prima": Decimal("100"),
    "derechos_rate": Decimal("0.03"),
    "gastos_tramite": Decimal("20"),
    "iva_rate": Decimal("0.10"),
    "minimum_billable_months": 12,
}
PROPOSAL = {
    "contratista": "Empresa de ejemplo",
    "beneficiario": "Entidad de ejemplo",
    "objeto": "Contrato ficticio para probar el cálculo",
    "fianzas": [{"tipo": "Anticipo", "monto": "1000", "vigencia_meses": 6,
                 "fuente": "Cláusula de fianza de anticipo ficticia"}],
}


class QuoteTests(unittest.TestCase):
    def test_minimum_premium_and_rounding(self):
        result = calculate_quote(PROPOSAL, POLICY)
        row = result["fianzas"][0]
        self.assertEqual(row["meses_cobrados"], 12)
        self.assertEqual(row["prima_calculada"], "20.00")
        self.assertEqual(row["prima"], "100.00")
        self.assertEqual(row["derechos"], "3.00")
        self.assertEqual(row["gastos_tramite"], "20.00")
        self.assertEqual(row["iva"], "12.30")
        self.assertEqual(result["total_general"], "135.30")

    def test_long_duration_and_policy_change(self):
        proposal = dict(PROPOSAL, fianzas=[dict(PROPOSAL["fianzas"][0],
                                                monto="10000", vigencia_meses=18)])
        row = calculate_quote(proposal, POLICY)["fianzas"][0]
        self.assertEqual(row["meses_cobrados"], 18)
        self.assertEqual(row["prima"], "300.00")
        changed = calculate_quote(proposal, dict(POLICY, annual_rate=Decimal("0.04")))
        self.assertEqual(changed["fianzas"][0]["prima"], "600.00")

    def test_rejects_missing_source_and_duplicates(self):
        invalid = dict(PROPOSAL, fianzas=[dict(PROPOSAL["fianzas"][0], fuente="pendiente")])
        with self.assertRaises(QuoteError):
            calculate_quote(invalid, POLICY)
        duplicated = dict(PROPOSAL, fianzas=PROPOSAL["fianzas"] * 2)
        with self.assertRaises(QuoteError):
            calculate_quote(duplicated, POLICY)

    def test_rejects_invalid_amount_and_unproven_labor_bond(self):
        invalid = dict(PROPOSAL, fianzas=[dict(PROPOSAL["fianzas"][0], monto=0)])
        with self.assertRaises(QuoteError):
            calculate_quote(invalid, POLICY)
        labor = dict(PROPOSAL, fianzas=[dict(PROPOSAL["fianzas"][0],
                                            tipo="Obligaciones laborales",
                                            fuente="El contratista pagará salarios")])
        with self.assertRaises(QuoteError):
            calculate_quote(labor, POLICY)

    def test_extracts_one_snapshot(self):
        raw = "Respuesta visible\n<gpi_quote_snapshot>" + json.dumps(PROPOSAL) + "</gpi_quote_snapshot>"
        visible, payload = extract_quote_snapshot(raw)
        self.assertEqual(visible, "Respuesta visible")
        self.assertEqual(payload, PROPOSAL)
        with self.assertRaises(QuoteError):
            extract_quote_snapshot(raw + raw)

    def test_policy_has_no_default_commercial_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(json.dumps({"annual_rate": "0.02"}), encoding="utf-8")
            with self.assertRaises(QuoteError):
                load_policy(path)
            path.write_text(json.dumps({key: value if isinstance(value, int) else str(value)
                                        for key, value in POLICY.items()}), encoding="utf-8")
            self.assertEqual(load_policy(path)["minimum_billable_months"], 12)


if __name__ == "__main__":
    unittest.main()
