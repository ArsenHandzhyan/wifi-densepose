#!/usr/bin/env python3

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class NoCacheHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()


def main():
    ui_dir = Path(__file__).resolve().parent
    server = ThreadingHTTPServer(("127.0.0.1", 3000), lambda *args, **kwargs: NoCacheHandler(*args, directory=str(ui_dir), **kwargs))
    print("Serving UI on http://127.0.0.1:3000 (cache disabled)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
