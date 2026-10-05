"""VPN-network-only search and bounded, public-URL page extraction. No browser."""
from html.parser import HTMLParser
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
import secrets
import socket
import ssl
import time
from urllib.parse import urlsplit, urljoin, urlencode, quote
from urllib.request import build_opener, ProxyHandler

MAX_BYTES = 2 * 1024 * 1024
MAX_TEXT = 16000
LOCAL = build_opener(ProxyHandler({}))


def vpn_ready():
    # Local Gluetun health server, never the Docker/host DNS or a public fallback.
    try:
        with LOCAL.open("http://127.0.0.1:9999/", timeout=3) as response:
            if response.status != 200:
                raise RuntimeError("VPN unavailable. Web access is blocked.")
    except Exception as error:
        raise RuntimeError("VPN unavailable. Web access is blocked.") from error


def target(url):
    if not isinstance(url, str) or len(url) > 4096 or any(ord(c) < 33 for c in url):
        raise ValueError("Invalid URL.")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Only public HTTP/HTTPS URLs without credentials are supported.")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port != (443 if parsed.scheme == "https" else 80):
        raise ValueError("Only standard web ports are supported.")
    host = parsed.hostname.encode("idna").decode("ascii")
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not addresses:
        raise ValueError("URL did not resolve.")
    ips = {entry[4][0] for entry in addresses}
    for value in ips:
        address = ipaddress.ip_address(value)
        if not address.is_global or address.is_multicast or getattr(address, "ipv4_mapped", None):
            raise ValueError("Private, local, reserved and mixed public/private destinations are blocked.")
    # Pin the actual connection to a validated IP. Do not resolve the hostname again.
    return parsed, host, port, sorted(ips)[0]


class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.title_depth = 0
        self.parts = []
        self.title = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg", "template"}:
            self.skip += 1
        if tag == "title":
            self.title_depth += 1
        if tag in {"p", "br", "div", "li", "h1", "h2", "h3", "tr", "section"} and not self.skip:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg", "template"} and self.skip:
            self.skip -= 1
        if tag == "title" and self.title_depth:
            self.title_depth -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)
            if self.title_depth:
                self.title.append(data)


def page(url):
    deadline = time.monotonic() + 35
    for _ in range(6):
        vpn_ready()
        parsed, host, port, ip = target(url)
        timeout = max(1, min(12, deadline - time.monotonic()))
        connection = http.client.HTTPConnection(host, port, timeout=timeout)
        try:
            connection.sock = socket.create_connection((ip, port), timeout=timeout)
            if parsed.scheme == "https":
                connection.sock = ssl.create_default_context().wrap_socket(connection.sock, server_hostname=host)
            path = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
            if parsed.query:
                path += "?" + quote(parsed.query, safe="=&/%:@!$'()*+,;?-._~")
            connection.request("GET", path, headers={"User-Agent": "LocalAI-Reader/1.0",
                               "Accept": "text/html,text/plain", "Accept-Encoding": "identity"})
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location:
                    raise ValueError("Redirect had no destination.")
                new_url = urljoin(url, location)
                if parsed.scheme == "https" and urlsplit(new_url).scheme != "https":
                    raise ValueError("HTTPS downgrade redirect blocked.")
                url = new_url
                continue
            if response.status != 200:
                raise ValueError(f"Page returned HTTP {response.status}.")
            if response.getheader("Content-Encoding", "identity").lower() not in {"", "identity"}:
                raise ValueError("Compressed responses are not supported.")
            kind = response.getheader("Content-Type", "").split(";", 1)[0].lower()
            if kind not in {"text/html", "application/xhtml+xml", "text/plain"}:
                raise ValueError("Only HTML and plain-text pages are supported, not PDFs or downloads.")
            data = bytearray()
            while True:
                if time.monotonic() >= deadline:
                    raise ValueError("Page read timed out.")
                block = response.read1(min(65536, MAX_BYTES + 1 - len(data)))
                if not block:
                    break
                data.extend(block)
                if len(data) > MAX_BYTES:
                    raise ValueError("Page exceeds the 2 MiB limit.")
            encoding = response.headers.get_content_charset() or "utf-8"
            try:
                raw = data.decode(encoding, errors="replace")
            except LookupError:
                raw = data.decode("utf-8", errors="replace")
            title = host
            if kind != "text/plain":
                parser = Text()
                parser.feed(raw)
                raw = "".join(parser.parts)
                title = " ".join("".join(parser.title).split())[:300] or host
            text = "\n".join(" ".join(line.split()) for line in raw.splitlines() if line.strip())
            if not text:
                raise ValueError("Page contained no readable text. It may require JavaScript or login.")
            vpn_ready()
            return {"url": url, "title": title, "text": text[:MAX_TEXT], "truncated": len(text) > MAX_TEXT}
        finally:
            connection.close()
    raise ValueError("Too many redirects.")


def search(query):
    if not isinstance(query, str) or not query.strip() or len(query) > 500:
        raise ValueError("Search query must contain 1–500 characters.")
    vpn_ready()
    url = "http://127.0.0.1:8080/search?" + urlencode({"q": query, "format": "json", "categories": "general"})
    with LOCAL.open(url, timeout=25) as response:
        data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("Search response too large.")
        results = json.loads(data).get("results", [])
    sources = []
    for result in results:
        url = result.get("url", "")
        if not isinstance(url, str) or urlsplit(url).scheme not in {"http", "https"}:
            continue
        sources.append({"url": url[:4096], "title": str(result.get("title", ""))[:300],
                        "text": str(result.get("content", ""))[:2000], "kind": "search snippet"})
        if len(sources) == 5:
            break
    if not sources:
        raise RuntimeError("Search returned no usable results. Engines may be blocking the VPN IP.")
    # Read up to two pages. Failures are explicit; snippets are never labelled full pages.
    for source in sources[:2]:
        try:
            fetched = page(source["url"])
            source.update(fetched, kind="page text")
            source["text"] = source["text"][:6000]
        except (ValueError, OSError, RuntimeError, http.client.HTTPException) as error:
            source["read_error"] = str(error)[:300]
    vpn_ready()
    return {"sources": sources}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Do not log queries, URLs or tokens.

    def reply(self, code, data):
        content = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def authorised(self):
        key = os.environ.get("WEB_API_KEY", "")
        return bool(key) and secrets.compare_digest(self.headers.get("Authorization", ""), "Bearer " + key)

    def do_GET(self):
        if not self.authorised():
            return self.reply(401, {"error": "Unauthorised"})
        if self.path != "/health":
            return self.reply(404, {"error": "Not found"})
        try:
            vpn_ready()
            return self.reply(200, {"status": "ready"})
        except RuntimeError as error:
            return self.reply(503, {"error": str(error)})

    def do_POST(self):
        if not self.authorised():
            return self.reply(401, {"error": "Unauthorised"})
        if self.path not in {"/search", "/read"}:
            return self.reply(404, {"error": "Not found"})
        if not self.server.busy.acquire(blocking=False):
            return self.reply(429, {"error": "Web service is busy"})
        try:
            self.connection.settimeout(5)
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 8192:
                raise ValueError("Invalid request size")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object")
            if self.path == "/search":
                result = search(data.get("query"))
            else:
                result = {"sources": [dict(page(data.get("url")), kind="page text")]}
            self.reply(200, result)
        except (ValueError, OSError, RuntimeError, http.client.HTTPException) as error:
            self.reply(503, {"error": str(error)[:500]})
        finally:
            self.server.busy.release()


if __name__ == "__main__":
    import threading
    if not os.environ.get("WEB_API_KEY"):
        raise SystemExit("WEB_API_KEY is required")
    server = ThreadingHTTPServer(("0.0.0.0", 8090), Handler)
    server.daemon_threads = True
    server.busy = threading.BoundedSemaphore(2)
    server.serve_forever()
