from http.server import BaseHTTPRequestHandler, HTTPServer

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(length)

        print("\n--- Alertmanager webhook payload ---", flush=True)
        print(body.decode("utf-8", errors="replace"), flush=True)

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"alert-dump ok")

HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()