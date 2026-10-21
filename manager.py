"""
Quote manager: a small web page, served only on this Mac, to browse, search, show and remove
quotes, and to see statistics and the display history.

    .venv/bin/python manager.py        # start it on its own and open the browser

The menu bar app starts the same server from ❦ → Manage Quotes…

Only 127.0.0.1 is served, and every API call needs a random token that is put in the page URL,
so other websites open in the browser can't read or change the quotes.
"""

import json
import logging
import secrets
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import shakespeare_wallpaper as sw

PAGE_PATH = Path(__file__).resolve().parent / "static" / "manage.html"

log = logging.getLogger("shakespeare.manager")


def quote_rows(quotes, state, history):
    """Quotes as shown in the table: id, fields, how often and when they were shown."""
    shown, last = {}, {}
    for entry in history:
        shown[entry["quote"]] = shown.get(entry["quote"], 0) + 1
        last[entry["quote"]] = entry["at"]
    current = (state.get("current") or {}).get("quote")
    recent = set(state.get("recent", []))
    return [{**q, "id": sw.quote_id(q), "work": sw.work_title(q), "shown_count": shown.get(q["quote"], 0),
             "last_shown": last.get(q["quote"]), "is_current": q["quote"] == current,
             "shown_this_round": q["quote"] in recent}
            for q in quotes]


class QuoteManager:
    """The server plus what it needs from its host (the menu bar app or the command line).

    run_on_main(fn) runs fn where AppKit may be used (the menu bar app passes
    AppHelper.callAfter); on_change() is called after quotes or the current quote changed.
    """

    def __init__(self, run_on_main=None, on_change=None, port=0):
        self.token = secrets.token_urlsafe(24)
        self.run_on_main = run_on_main or (lambda fn: fn())
        self.on_change = on_change or (lambda: None)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), self.handler_class())
        self.port = self.httpd.server_address[1]
        self.thread = None

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}/#token={self.token}"

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
            self.thread.start()
            log.info("Quote manager running on 127.0.0.1:%d", self.port)
        return self

    def stop(self):
        if self.thread is not None:
            self.httpd.shutdown()
            self.thread = None
        self.httpd.server_close()

    def open_in_browser(self):
        self.start()
        webbrowser.open(self.url)

    def wallpaper_action(self, fn):
        """Run a wallpaper change on the main thread and wait for it (raises its exception)."""
        done, result = threading.Event(), {}

        def task():
            try:
                result["value"] = fn()
            except Exception as e:  # passed back to the request thread
                result["error"] = e
            finally:
                done.set()

        self.run_on_main(task)
        if not done.wait(timeout=30):
            raise TimeoutError("Wallpaper change didn't finish")
        if "error" in result:
            raise result["error"]
        self.on_change()
        return result.get("value")

    # API

    def api(self, method, path):
        """(status, body) for an API request."""
        parts = path.strip("/").split("/")  # ["api", "quotes", id]
        if method == "GET" and parts == ["api", "quotes"]:
            state = sw.load_state(sw.STATE_PATH)
            return HTTPStatus.OK, quote_rows(sw.load_quotes(sw.QUOTES_PATH), state, sw.load_history())
        if method == "GET" and parts == ["api", "stats"]:
            return HTTPStatus.OK, sw.collection_stats(sw.load_quotes(sw.QUOTES_PATH),
                                                      sw.load_state(sw.STATE_PATH), sw.load_history())
        if method == "GET" and parts == ["api", "history"]:
            return HTTPStatus.OK, list(reversed(sw.load_history()))
        if len(parts) == 3 and parts[:2] in (["api", "quotes"], ["api", "show"]):
            quote = sw.find_quote(parts[2])
            if quote is None:
                return HTTPStatus.NOT_FOUND, {"error": "No such quote (it may have been removed)."}
            if method == "DELETE" and parts[1] == "quotes":
                return self.remove(quote)
            if method == "POST" and parts[1] == "show":
                self.wallpaper_action(lambda: sw.show_quote(quote, reason="manager"))
                return HTTPStatus.OK, {"shown": quote["quote"]}
        return HTTPStatus.NOT_FOUND, {"error": "Unknown request."}

    def remove(self, quote):
        try:
            sw.remove_quote(quote["quote"])
        except ValueError as e:
            return HTTPStatus.CONFLICT, {"error": str(e)}
        log.info("Removed quote from the manager: %s", quote["quote"])
        was_current = (sw.current_quote() or {}).get("quote") == quote["quote"]
        if was_current:
            self.wallpaper_action(lambda: sw.next_quote(reason="remove"))
        else:
            self.on_change()
        return HTTPStatus.OK, {"removed": quote["quote"], "new_quote_shown": was_current}

    def handler_class(self):
        manager = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                log.debug(fmt, *args)

            def send(self, status, body, content_type="application/json"):
                data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header("Content-Type", f"{content_type}; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(data)

            def allowed(self, need_token):
                # The Host check stops DNS-rebinding pages; the token stops other sites' requests
                if self.headers.get("Host") != f"127.0.0.1:{manager.port}":
                    return False
                return not need_token or secrets.compare_digest(self.headers.get("X-Token", ""), manager.token)

            def handle_request(self, method):
                path = self.path.split("?", 1)[0]
                if method == "GET" and path in ("/", "/index.html"):
                    if not self.allowed(need_token=False):
                        return self.send(HTTPStatus.FORBIDDEN, {"error": "Forbidden"})
                    return self.send(HTTPStatus.OK, PAGE_PATH.read_bytes(), "text/html")
                if not path.startswith("/api/"):
                    return self.send(HTTPStatus.NOT_FOUND, {"error": "Not found"})
                if not self.allowed(need_token=True):
                    return self.send(HTTPStatus.FORBIDDEN, {"error": "Forbidden"})
                try:
                    status, body = manager.api(method, path)
                except Exception as e:
                    log.exception("%s %s failed", method, path)
                    status, body = HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(e)}
                self.send(status, body)

            def do_GET(self):
                self.handle_request("GET")

            def do_POST(self):
                self.handle_request("POST")

            def do_DELETE(self):
                self.handle_request("DELETE")

        return Handler


def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(message)s")
    imported = sw.import_history_from_logs()
    if imported:
        log.info("Imported %d past quote changes from the logs into the history", imported)
    manager = QuoteManager().start()
    print(f"Quote manager: {manager.url}\nPress Ctrl+C to stop.")
    webbrowser.open(manager.url)
    try:
        manager.thread.join()
    except KeyboardInterrupt:
        manager.stop()


if __name__ == "__main__":
    main()
