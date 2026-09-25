import base64
import http.client
import json
import os
import socket
import stat
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import ANY, patch

from gpi_handoff.local_app import App
from gpi_handoff.runtime import OpenAIResponsesModel, QuoteRuntime, RuntimeError, model_from_environment
from http.server import ThreadingHTTPServer


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
    def __init__(self, proposal=PROPOSAL): self.contracts = []; self.proposal = proposal
    def propose(self, contract_text):
        self.contracts.append(contract_text)
        return "Datos extraídos para revisión.", self.proposal


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
        runtime.add_contract_text(conversation_id, "Cláusula de fianza de anticipo ficticia. Contrato para extracción local")
        result = runtime.propose_with_model(conversation_id)
        self.assertEqual(fake.contracts, ["Cláusula de fianza de anticipo ficticia. Contrato para extracción local"])
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
        self.assertEqual(stat.S_IMODE((self.root / "data" / "gpi-local.sqlite3").stat().st_mode), 0o600)
        with self.assertRaises(RuntimeError): runtime.propose_with_model(conversation_id)

    def test_existing_data_directories_are_restricted_and_unknown_pdf_id_creates_no_file(self):
        data_dir = self.root / "data"
        documents_dir = data_dir / "documents"
        documents_dir.mkdir(parents=True)
        os.chmod(data_dir, 0o755); os.chmod(documents_dir, 0o755)
        runtime = QuoteRuntime(self.policy, data_dir)
        self.assertEqual(stat.S_IMODE(data_dir.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(documents_dir.stat().st_mode), 0o700)
        os.chmod(runtime.store.db_path, 0o644)
        QuoteRuntime(self.policy, data_dir)
        self.assertEqual(stat.S_IMODE(runtime.store.db_path.stat().st_mode), 0o600)
        encoded = base64.b64encode(b"%PDF-1.4\\nsynthetic").decode("ascii")
        with self.assertRaises(RuntimeError): runtime.add_pdf("unknown", "contrato.pdf", encoded)
        self.assertEqual(list(documents_dir.iterdir()), [])

    def test_model_environment_defaults_to_offline_and_rejects_unsecured_remote_url(self):
        self.assertIsNone(model_from_environment({}))
        with self.assertRaises(RuntimeError):
            model_from_environment({"GPI_MODEL_PROVIDER": "openai_responses", "GPI_MODEL_BASE_URL": "http://example.test",
                                    "GPI_MODEL_API_KEY": "key", "GPI_MODEL_NAME": "fake"})

    def test_byok_url_rejects_lookalikes_userinfo_and_url_extras(self):
        for base_url in ("http://localhost.evil.test", "http://127.0.0.1.evil.test", "http://[::1]", "https://key@api.openai.com",
                         "https://api.openai.com?x=1", "https://api.openai.com#fragment", "https://api.openai.com/base"):
            with self.subTest(base_url=base_url):
                with self.assertRaises(RuntimeError): OpenAIResponsesModel(base_url, "key", "model")
        self.assertEqual(OpenAIResponsesModel("http://127.0.0.1:8080", "key", "model").base_url,
                         "http://127.0.0.1:8080")

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

    def test_model_sources_must_appear_in_the_stored_contract(self):
        invalid = dict(PROPOSAL, fianzas=[dict(PROPOSAL["fianzas"][0], fuente="Cláusula inventada que no aparece")])
        runtime = QuoteRuntime(self.policy, self.root / "data", FakeModel(invalid))
        conversation_id = runtime.store.create_conversation()
        runtime.add_contract_text(conversation_id, "Cláusula de fianza de anticipo ficticia")
        with self.assertRaisesRegex(RuntimeError, "no aparece"):
            runtime.propose_with_model(conversation_id)

    def _server(self, runtime):
        server = ThreadingHTTPServer(("127.0.0.1", 0), App(runtime).handler())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join); self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        return server

    def test_http_requires_json_and_exposes_local_history(self):
        runtime = QuoteRuntime(self.policy, self.root / "data")
        server = self._server(runtime)
        port = server.server_address[1]
        connection = http.client.HTTPConnection("127.0.0.1", port)
        connection.request("POST", "/api/conversations", body=b"{}", headers={"Content-Type": "text/plain"})
        response = connection.getresponse()
        self.assertEqual(response.status, 400); self.assertIn("application/json", response.read().decode())
        conversation_id = runtime.store.create_conversation()
        runtime.add_contract_text(conversation_id, "Contrato para auditoría")
        connection.request("GET", f"/api/conversations/{conversation_id}/history")
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Cache-Control"), "no-store")
        self.assertEqual(json.loads(response.read())["events"][0]["kind"], "contract_text")

    def test_http_rejects_foreign_host_and_origin(self):
        runtime = QuoteRuntime(self.policy, self.root / "data")
        server = self._server(runtime)
        port = server.server_address[1]
        connection = http.client.HTTPConnection("127.0.0.1", port)
        connection.request("POST", "/api/conversations", body=b"{}", headers={
            "Host": f"evil.test:{port}", "Content-Type": "application/json",
        })
        response = connection.getresponse()
        self.assertEqual(response.status, 403); self.assertEqual(response.getheader("Cache-Control"), "no-store"); response.read()
        connection.request("GET", "/", headers={"Origin": f"http://evil.test:{port}"})
        response = connection.getresponse()
        self.assertEqual(response.status, 403); self.assertEqual(response.getheader("Cache-Control"), "no-store"); response.read()

    def test_http_rejects_missing_and_negative_content_length(self):
        runtime = QuoteRuntime(self.policy, self.root / "data")
        server = self._server(runtime)
        port = server.server_address[1]
        for request_bytes in (
            b"POST /api/conversations HTTP/1.1\\r\\nHost: 127.0.0.1\\r\\nContent-Type: application/json\\r\\n\\r\\n",
            b"POST /api/conversations HTTP/1.1\\r\\nHost: 127.0.0.1\\r\\nContent-Type: application/json\\r\\nContent-Length: -1\\r\\n\\r\\n",
        ):
            with self.subTest(request_bytes=request_bytes):
                with socket.create_connection(("127.0.0.1", port)) as client:
                    client.sendall(request_bytes); client.shutdown(socket.SHUT_WR)
                    self.assertIn(b"400", client.recv(1024))


if __name__ == "__main__": unittest.main()
