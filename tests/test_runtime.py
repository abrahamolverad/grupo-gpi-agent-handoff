import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import ANY, patch

from gpi_handoff.runtime import OpenAIResponsesModel, QuoteRuntime, RuntimeError, model_from_environment


POLICY = {
    "annual_rate": "0.02", "min_prima": "100", "derechos_rate": "0.03",
    "gastos_tramite": "20", "iva_rate": "0.10", "minimum_billable_months": 12,
}
PROPOSAL = {
    "contratista": "Empresa de ejemplo", "beneficiario": "Entidad de ejemplo",
    "objeto": "Contrato ficticio para probar el cálculo",
    "fianzas": [{"tipo": "Anticipo", "monto": "1000", "vigencia_meses": 6,
                  "fuente": "Cláusula de fianza de anticipo ficticia"}],
}


class FakeModel:
    def __init__(self): self.contracts = []
    def propose(self, contract_text):
        self.contracts.append(contract_text)
        return "Datos extraídos para revisión.", PROPOSAL


class FakeResponse:
    def __init__(self, body): self.body = body
    def read(self): return self.body
    def __enter__(self): return self
    def __exit__(self, *_args): return False


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.policy = self.root / "policy.json"
        self.policy.write_text(json.dumps(POLICY), encoding="utf-8")
    def tearDown(self): self.temp.cleanup()

    def test_offline_manual_proposal_is_a_human_review_draft_and_is_audited(self):
        runtime = QuoteRuntime(self.policy, self.root / "data")
        conversation_id = runtime.store.create_conversation()
        runtime.add_contract_text(conversation_id, "Texto contractual verificable")
        result = runtime.submit_proposal(conversation_id, PROPOSAL)
        self.assertEqual(result["estado"], "revision_humana_obligatoria")
        self.assertEqual(result["accion_final"], "bloqueada")
        self.assertEqual(result["precotizacion"]["total_general"], "135.30")
        self.assertEqual([event["kind"] for event in runtime.store.history(conversation_id)],
                         ["contract_text", "quote_draft"])

    def test_fake_model_is_explicit_and_only_receives_stored_contract_text(self):
        fake = FakeModel()
        runtime = QuoteRuntime(self.policy, self.root / "data", fake)
        conversation_id = runtime.store.create_conversation()
        runtime.add_contract_text(conversation_id, "Contrato para extracción local")
        result = runtime.propose_with_model(conversation_id)
        self.assertEqual(fake.contracts, ["Contrato para extracción local"])
        self.assertEqual(result["respuesta_visible"], "Datos extraídos para revisión.")
        self.assertEqual([event["kind"] for event in runtime.store.history(conversation_id)],
                         ["contract_text", "model_proposal", "quote_draft"])

    def test_pdf_stays_local_and_requires_extracted_text_for_model_path(self):
        runtime = QuoteRuntime(self.policy, self.root / "data")
        conversation_id = runtime.store.create_conversation()
        encoded = base64.b64encode(b"%PDF-1.4\\nsynthetic").decode("ascii")
        response = runtime.add_pdf(conversation_id, "contrato.pdf", encoded)
        self.assertTrue((self.root / "data" / "documents" / response["filename"]).exists())
        self.assertTrue((self.root / "data" / "gpi-local.sqlite3").exists())
        with self.assertRaises(RuntimeError): runtime.propose_with_model(conversation_id)

    def test_model_environment_defaults_to_offline_and_rejects_unsecured_remote_url(self):
        self.assertIsNone(model_from_environment({}))
        with self.assertRaises(RuntimeError):
            model_from_environment({"GPI_MODEL_PROVIDER": "openai_responses", "GPI_MODEL_BASE_URL": "http://example.test",
                                    "GPI_MODEL_API_KEY": "key", "GPI_MODEL_NAME": "fake"})

    def test_responses_adapter_uses_byok_request_shape_without_a_network_call(self):
        snapshot = "Operador\n<gpi_quote_snapshot>" + json.dumps(PROPOSAL) + "</gpi_quote_snapshot>"
        adapter = OpenAIResponsesModel("https://api.openai.com", "test-key", "customer-model")
        with patch("gpi_handoff.runtime.request.urlopen", return_value=FakeResponse(json.dumps({"output_text": snapshot}).encode())) as mocked:
            visible, proposal = adapter.propose("texto contractual")
        sent = mocked.call_args.args[0]
        self.assertEqual(sent.full_url, "https://api.openai.com/v1/responses")
        self.assertEqual(json.loads(sent.data), {"model": "customer-model", "input": ANY})
        self.assertIn("texto contractual", json.loads(sent.data)["input"])
        self.assertEqual(visible, "Operador")
        self.assertEqual(proposal, PROPOSAL)


if __name__ == "__main__": unittest.main()
