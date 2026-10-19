"""OpenAI-compatible mock LLM for end-to-end tests. Standard library only.

POST /v1/chat/completions   answers "mock: <last user message>", supports stream=true
POST /v1/embeddings         returns a deterministic 8-dimensional vector per input
GET  /v1/models             lists the mock models
GET  /_requests             every request body received since the last reset (JSON list)
POST /_reset                clears the request log

A model whose name starts with "fail" always answers HTTP 500, to test fallbacks.
"""

import hashlib
import json
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", "8000"))
_lock = threading.Lock()
_requests: list[dict] = []


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _json(self, status: int, body) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/_requests":
            with _lock:
                return self._json(200, list(_requests))
        if self.path in ("/v1/models", "/models"):
            return self._json(200, {"object": "list", "data": [
                {"id": m, "object": "model", "owned_by": "mock"} for m in ("mock-small", "mock-large", "fail-always")]})
        if self.path == "/health":
            return self._json(200, {"status": "ok"})
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        if self.path == "/_reset":
            with _lock:
                _requests.clear()
            return self._json(200, {"ok": True})
        if self.path in ("/v1/embeddings", "/embeddings"):
            body = json.loads(raw or b"{}")
            with _lock:
                _requests.append({"headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
            texts = body.get("input") or []
            texts = [texts] if isinstance(texts, str) else texts
            data = []
            for i, t in enumerate(texts):
                h = hashlib.sha256(str(t).encode()).digest()
                vector = [x / 255 for x in h[:8]]
                data.append({"object": "embedding", "index": i, "embedding": vector})
            tokens = max(1, sum(len(str(t).split()) for t in texts))
            return self._json(200, {"object": "list", "data": data, "model": body.get("model", "mock-embed"),
                                    "usage": {"prompt_tokens": tokens, "total_tokens": tokens}})
        if self.path not in ("/v1/chat/completions", "/chat/completions"):
            return self._json(404, {"error": "not found"})
        body = json.loads(raw or b"{}")
        with _lock:
            _requests.append({"headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
        model = body.get("model", "mock")
        if model.startswith("fail"):
            return self._json(500, {"error": {"message": "mock failure", "type": "server_error"}})

        messages = body.get("messages") or []
        last_user = next((_text(m.get("content")) for m in reversed(messages) if m.get("role") == "user"), "")
        answer = f"mock: {last_user}"
        prompt_tokens = max(1, sum(len(_text(m.get("content")).split()) for m in messages))
        completion_tokens = max(1, len(answer.split()))
        usage = {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                 "total_tokens": prompt_tokens + completion_tokens}
        cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        created = int(time.time())

        if not body.get("stream"):
            return self._json(200, {
                "id": cid, "object": "chat.completion", "created": created, "model": model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}],
                "usage": usage,
            })

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        def send(obj) -> None:
            self.wfile.write(f"data: {json.dumps(obj)}\n\n".encode())
            self.wfile.flush()

        base = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model}
        send({**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}]})
        for word in answer.split(" "):
            send({**base, "choices": [{"index": 0, "delta": {"content": word + " "}, "finish_reason": None}]})
        send({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": usage})
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
