"""Localhost-only web interface for the customer-owned quote runtime."""

from __future__ import annotations

import argparse
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .quote import QuoteError
from .runtime import QuoteRuntime, RuntimeError, model_from_environment


PAGE = """<!doctype html><meta charset=utf-8><title>GPI Cotizador local</title>
<style>body{font:16px system-ui;max-width:800px;margin:2rem auto;padding:0 1rem}textarea{width:100%;min-height:15rem}button{padding:.6rem 1rem;margin:.5rem 0}pre{white-space:pre-wrap;background:#f3f3f3;padding:1rem}</style>
<h1>Precotización local Grupo GPI</h1><p>El resultado queda en borrador: requiere revisión humana y esta aplicación no envía correos ni emite fianzas.</p>
<textarea id=contract placeholder="Pegue el texto del contrato"></textarea><br><input id=pdf type=file accept=application/pdf><br><button onclick=start()>Guardar contrato</button><button onclick=propose()>Proponer con modelo configurado</button><button onclick=history()>Ver historial local</button><p>También puede enviar una propuesta JSON para calcularla localmente:</p><textarea id=proposal placeholder='{"contratista":"...","beneficiario":"...","objeto":"...","fianzas":[...]}'></textarea><br><button onclick=calculate()>Calcular borrador</button><pre id=output></pre>
<script>let id;const out=document.querySelector('#output');async function call(path,data){let r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});let j=await r.json();if(!r.ok)throw Error(j.error);return j}function as64(bytes){let s='';for(let i=0;i<bytes.length;i+=8192)s+=String.fromCharCode(...bytes.subarray(i,i+8192));return btoa(s)}async function start(){let c=await call('/api/conversations',{});id=c.id;let text=contract.value;if(text)await call('/api/conversations/'+id+'/contract',{text});let f=pdf.files[0];if(f){let b=await f.arrayBuffer(),s=as64(new Uint8Array(b));await call('/api/conversations/'+id+'/pdf',{filename:f.name,pdf_base64:s})}out.textContent='Contrato guardado localmente. Conversación: '+id}async function propose(){try{out.textContent=JSON.stringify(await call('/api/conversations/'+id+'/propose',{}),null,2)}catch(e){out.textContent=e.message}}async function calculate(){try{out.textContent=JSON.stringify(await call('/api/conversations/'+id+'/proposal',{proposal:JSON.parse(proposal.value)}),null,2)}catch(e){out.textContent=e.message}}async function history(){try{let r=await fetch('/api/conversations/'+id+'/history'),j=await r.json();if(!r.ok)throw Error(j.error);out.textContent=JSON.stringify(j,null,2)}catch(e){out.textContent=e.message}}</script>"""


class App:
    def __init__(self, runtime: QuoteRuntime): self.runtime = runtime

    def handler(self):
        app = self
        class Handler(BaseHTTPRequestHandler):
            def _json(self, status: int, data: dict[str, Any]) -> None:
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
            def do_GET(self) -> None:
                if self.path == "/":
                    body = PAGE.encode("utf-8"); self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
                else:
                    parts = [part for part in urlparse(self.path).path.split("/") if part]
                    if len(parts) == 4 and parts[:2] == ["api", "conversations"] and parts[3] == "history":
                        try: self._json(200, {"events": app.runtime.store.history(parts[2])})
                        except RuntimeError as exc: self._json(404, {"error": str(exc)})
                    else: self._json(404, {"error": "No encontrado"})
            def do_POST(self) -> None:
                try:
                    if self.headers.get_content_type() != "application/json":
                        raise RuntimeError("La solicitud debe usar Content-Type application/json")
                    content_length = self.headers.get("Content-Length")
                    if content_length is None:
                        raise RuntimeError("La solicitud requiere Content-Length")
                    try: size = int(content_length)
                    except ValueError as exc: raise RuntimeError("Content-Length no es válido") from exc
                    if size < 0: raise RuntimeError("Content-Length no puede ser negativo")
                    if size > 14 * 1024 * 1024: raise RuntimeError("La solicitud supera el límite permitido")
                    data = json.loads(self.rfile.read(size).decode("utf-8"))
                    parts = [part for part in urlparse(self.path).path.split("/") if part]
                    if parts == ["api", "conversations"]: result = {"id": app.runtime.store.create_conversation()}
                    elif len(parts) == 4 and parts[:2] == ["api", "conversations"]:
                        conversation_id, action = parts[2], parts[3]
                        if action == "contract": app.runtime.add_contract_text(conversation_id, data.get("text", "")); result = {"ok": True}
                        elif action == "pdf": result = app.runtime.add_pdf(conversation_id, data.get("filename", "contrato.pdf"), data.get("pdf_base64", ""))
                        elif action == "proposal": result = app.runtime.submit_proposal(conversation_id, data.get("proposal"), data.get("visible", ""))
                        elif action == "propose": result = app.runtime.propose_with_model(conversation_id)
                        else: raise RuntimeError("Acción no encontrada")
                    else: raise RuntimeError("Ruta no encontrada")
                    self._json(200, result)
                except (RuntimeError, QuoteError, json.JSONDecodeError, UnicodeDecodeError) as exc: self._json(400, {"error": str(exc)})
            def log_message(self, _format: str, *_args: object) -> None: pass
        return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description="Interfaz local de precotizaciones GPI")
    parser.add_argument("--policy", type=Path, default=Path(os.getenv("GPI_POLICY_PATH", "policy.local.json")))
    parser.add_argument("--data-dir", type=Path, default=Path(os.getenv("GPI_DATA_DIR", "customer_data")))
    parser.add_argument("--bind", default=os.getenv("GPI_BIND", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("GPI_PORT", "8787")))
    args = parser.parse_args()
    if args.bind not in ("127.0.0.1", "::1", "localhost"):
        parser.error("Por seguridad, el servidor local solo permite 127.0.0.1, ::1 o localhost")
    try: runtime = QuoteRuntime(args.policy, args.data_dir, model_from_environment())
    except RuntimeError as exc: parser.error(str(exc))
    server = ThreadingHTTPServer((args.bind, args.port), App(runtime).handler())
    print(f"GPI local activo en http://{args.bind}:{args.port} (sin envío ni emisión)")
    server.serve_forever()
    return 0


if __name__ == "__main__": raise SystemExit(main())
