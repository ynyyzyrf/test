#!/usr/bin/env python3
"""Intel gateway: serves TrendRadar + ai-daily data as JSON for MAG workbench."""
import json
import glob
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

GATEWAY_DIR = os.path.dirname(os.path.abspath(__file__))
TREND_DIR = "/opt/intel/TrendRadar/output"
AIDAILY_DIR = "/opt/intel/ai-daily/news-data"
TOKEN_FILE = os.path.join(GATEWAY_DIR, ".token")
PORT = int(os.environ.get("INTEL_PORT", "8899"))


def load_token():
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def query_db(path, sql, params=()):
    rows = []
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        cur = conn.execute(sql, params)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        conn.close()
    except (sqlite3.Error, OSError):
        pass
    return rows


def latest_date_dir(kind):
    files = sorted(glob.glob(os.path.join(TREND_DIR, kind, "*.db")))
    return files[-1] if files else None


def get_trendradar(date=None, limit=200):
    limit = max(1, min(int(limit or 200), 500))
    news_file = os.path.join(TREND_DIR, "news", f"{date}.db") if date else latest_date_dir("news")
    rss_file = os.path.join(TREND_DIR, "rss", f"{date}.db") if date else latest_date_dir("rss")
    out = {"date": "", "news": [], "rss": [], "platforms": []}
    if news_file and os.path.exists(news_file):
        out["date"] = os.path.basename(news_file).replace(".db", "")
        out["platforms"] = query_db(news_file, "select id, name from platforms")
        out["news"] = query_db(
            news_file,
            "select title, platform_id, rank, url, first_crawl_time, last_crawl_time, crawl_count "
            "from news_items order by last_crawl_time desc limit ?",
            (limit,),
        )
    if rss_file and os.path.exists(rss_file):
        out["rss"] = query_db(
            rss_file,
            "select title, feed_id, url, published_at, summary, author from rss_items "
            "order by last_crawl_time desc limit ?",
            (limit,),
        )
    return out


def get_aidaily():
    pushes = sorted(glob.glob(os.path.join(AIDAILY_DIR, "push-*.md")))
    notif = sorted(glob.glob(os.path.join(AIDAILY_DIR, "notify-*.md")))
    fetches = sorted(glob.glob(os.path.join(AIDAILY_DIR, "fetch-*.json")))
    return {
        "push_files": [os.path.basename(p) for p in pushes[-10:]],
        "notify_files": [os.path.basename(p) for p in notif[-10:]],
        "latest_push": os.path.basename(pushes[-1]) if pushes else "",
        "latest_notify": os.path.basename(notif[-1]) if notif else "",
        "latest_fetch": os.path.basename(fetches[-1]) if fetches else "",
    }


def get_aidaily_file(name):
    safe = os.path.basename(name or "")
    if not (safe.startswith(("push-", "notify-", "fetch-"))):
        return None
    path = os.path.join(AIDAILY_DIR, safe)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authed(self):
        token = load_token()
        if not token:
            return False
        got = self.headers.get("X-Intel-Token", "") or parse_qs(urlparse(self.path).query).get("token", [""])[0]
        return got == token

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)
        if path == "/health":
            self._send(200, {"ok": True, "service": "intel-gateway"})
            return
        if not self._authed():
            self._send(401, {"error": "unauthorized"})
            return
        try:
            if path == "/trendradar":
                self._send(200, get_trendradar(qs.get("date", [None])[0], qs.get("limit", [200])[0]))
            elif path == "/aidaily":
                self._send(200, get_aidaily())
            elif path == "/aidaily/file":
                content = get_aidaily_file(qs.get("name", [""])[0])
                if content is None:
                    self._send(404, {"error": "not found"})
                else:
                    self._send(200, content, ctype="text/markdown; charset=utf-8")
            else:
                self._send(404, {"error": "unknown path"})
        except Exception as exc:  # noqa: BLE001
            self._send(500, {"error": str(exc)})

    def log_message(self, fmt, *args):  # noqa: A003
        pass


if __name__ == "__main__":
    if not os.path.exists(TOKEN_FILE):
        import secrets

        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(secrets.token_urlsafe(24))
        os.chmod(TOKEN_FILE, 0o600)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
