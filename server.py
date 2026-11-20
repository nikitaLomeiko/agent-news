#!/usr/bin/env python3
"""Local, dependency-free Markdown news reader."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import mimetypes
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse


APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "app"
CONFIG_FILE = APP_DIR / "config.json"
APP_VERSION = "2.3-no-avatars"
DEFAULT_CONFIG = {
    "title": "Моя лента",
    "news_dir": str(APP_DIR / "news"),
    "host": "127.0.0.1",
    "port": 8765,
    "refresh_seconds": 8,
}


def load_config() -> dict:
    config = DEFAULT_CONFIG.copy()
    if CONFIG_FILE.exists():
        try:
            saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                config.update({key: saved[key] for key in DEFAULT_CONFIG if key in saved})
        except (OSError, json.JSONDecodeError):
            pass
    config["news_dir"] = str(Path(config["news_dir"]).expanduser().resolve())
    config["port"] = int(config["port"])
    config["refresh_seconds"] = max(3, int(config["refresh_seconds"]))
    return config


def save_config(config: dict) -> None:
    clean = {key: config[key] for key in DEFAULT_CONFIG}
    temporary = CONFIG_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(clean, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(CONFIG_FILE)


def parse_scalar(value: str):
    value = value.strip()
    if not value:
        return ""
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    if value.startswith("[") and value.endswith("]"):
        return [part.strip().strip("'\"") for part in value[1:-1].split(",") if part.strip()]
    lowered = value.lower()
    if lowered in {"true", "yes", "да"}:
        return True
    if lowered in {"false", "no", "нет"}:
        return False
    return value


def split_front_matter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
    if end is None:
        return {}, text
    metadata: dict = {}
    active_list: str | None = None
    for line in lines[1:end]:
        if active_list and line.lstrip().startswith("-"):
            metadata[active_list].append(line.lstrip()[1:].strip().strip("'\""))
            continue
        match = re.match(r"^([A-Za-zА-Яа-яЁё0-9_-]+)\s*:\s*(.*)$", line)
        if not match:
            continue
        key, value = match.groups()
        key = key.lower()
        parsed = parse_scalar(value)
        if value.strip() == "":
            parsed = []
            active_list = key
        else:
            active_list = None
        metadata[key] = parsed
    return metadata, "\n".join(lines[end + 1 :]).strip()


def plain_text(markdown: str) -> str:
    value = re.sub(r"```.*?```", " ", markdown, flags=re.S)
    value = re.sub(r"!\[[^]]*]\([^)]*\)", " ", value)
    value = re.sub(r"\[([^]]+)]\([^)]*\)", r"\1", value)
    value = re.sub(r"[#>*_`~|=-]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def resolve_media_url(value: str, article_path: Path, root: Path) -> str:
    """Turn an article-relative image path into a safe local media URL."""
    value = value.strip().strip("<>")
    if not value:
        return ""
    if re.match(r"^https?://", value, flags=re.I):
        return value
    try:
        target = (article_path.parent / unquote(value)).resolve()
        relative = target.relative_to(root.resolve())
    except (OSError, ValueError):
        return ""
    return "/media/" + quote(relative.as_posix(), safe="/")


def rewrite_markdown_images(markdown: str, article_path: Path, root: Path) -> str:
    pattern = re.compile(r"(!\[[^\]]*\]\()(<[^>]+>|[^)\s]+)(\))")

    def replace(match: re.Match) -> str:
        resolved = resolve_media_url(match.group(2), article_path, root)
        return match.group(1) + (resolved or match.group(2)) + match.group(3)

    return pattern.sub(replace, markdown)


def normalized_date(value, fallback: float) -> tuple[str, float]:
    if value:
        candidate = str(value).strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.isoformat(), parsed.timestamp()
        except ValueError:
            pass
    parsed = datetime.fromtimestamp(fallback, tz=timezone.utc)
    return parsed.isoformat(), fallback


def read_article(path: Path, root: Path) -> dict | None:
    try:
        stat = path.stat()
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    metadata, body = split_front_matter(raw)
    relative = path.relative_to(root).as_posix()
    article_id = hashlib.sha1(relative.encode("utf-8")).hexdigest()[:14]
    heading = re.search(r"^#\s+(.+?)\s*$", body, flags=re.M)
    title = str(metadata.get("title") or (heading.group(1) if heading else path.stem.replace("_", " ").replace("-", " ")))
    if heading and not metadata.get("title"):
        body = body[: heading.start()] + body[heading.end() :]
        body = body.strip()
    published, timestamp = normalized_date(
        metadata.get("date") or metadata.get("published") or metadata.get("created"), stat.st_mtime
    )
    tags = metadata.get("tags", [])
    if isinstance(tags, str):
        tags = [part.strip() for part in tags.split(",") if part.strip()]
    summary = str(metadata.get("summary") or metadata.get("description") or "")
    if not summary:
        summary = plain_text(body)[:280]
        if len(plain_text(body)) > 280:
            summary = summary.rstrip() + "…"
    priority = str(metadata.get("priority") or "normal").lower()
    if metadata.get("important") is True:
        priority = "high"
    image = resolve_media_url(str(metadata.get("image") or ""), path, root)
    body = rewrite_markdown_images(body, path, root)
    return {
        "id": article_id,
        "file": relative,
        "title": title,
        "summary": summary,
        "content": body,
        "category": str(metadata.get("category") or metadata.get("rubric") or "Общее"),
        "source": str(metadata.get("source") or metadata.get("author") or "Агент"),
        "date": published,
        "timestamp": timestamp,
        "tags": tags[:12],
        "priority": priority,
        "url": str(metadata.get("url") or metadata.get("link") or ""),
        "image": image,
        "version": f"{stat.st_mtime_ns}-{stat.st_size}",
    }


def collect_articles(config: dict) -> list[dict]:
    root = Path(config["news_dir"])
    root.mkdir(parents=True, exist_ok=True)
    articles = []
    for path in root.rglob("*.md"):
        if path.name.startswith(".") or any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        article = read_article(path, root)
        if article:
            articles.append(article)
    articles.sort(key=lambda item: (item["timestamp"], item["file"]), reverse=True)
    return articles


class NewsServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, handler, config):
        super().__init__(address, handler)
        self.config = config
        self.started_at = time.time()


class Handler(BaseHTTPRequestHandler):
    server_version = "AgentNews/1.0"

    def log_message(self, format: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")

    def send_json(self, payload, status=HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path.startswith("/media/"):
            self.serve_media(path)
            return
        if path == "/api/news":
            articles = collect_articles(self.server.config)
            signature = hashlib.sha1(
                "|".join(item["id"] + item["version"] for item in articles).encode("utf-8")
            ).hexdigest()[:16]
            self.send_json({"articles": articles, "signature": signature, "count": len(articles)})
            return
        if path == "/api/config":
            public = {key: self.server.config[key] for key in ("title", "news_dir", "refresh_seconds")}
            self.send_json(public)
            return
        if path == "/api/health":
            self.send_json(
                {"ok": True, "version": APP_VERSION, "uptime": round(time.time() - self.server.started_at)}
            )
            return
        self.serve_static(path)

    def serve_media(self, url_path: str) -> None:
        root = Path(self.server.config["news_dir"]).resolve()
        relative = unquote(url_path.removeprefix("/media/"))
        target = (root / relative).resolve()
        allowed = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif"}
        if (root not in target.parents or target.suffix.lower() not in allowed or not target.is_file()):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            data = target.read_bytes()
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        mime = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802
        self.send_json({"error": "Не найдено"}, HTTPStatus.NOT_FOUND)

    def serve_static(self, url_path: str) -> None:
        relative = "index.html" if url_path in {"", "/"} else unquote(url_path.lstrip("/"))
        target = (STATIC_DIR / relative).resolve()
        if STATIC_DIR.resolve() not in target.parents and target != STATIC_DIR.resolve():
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not target.is_file():
            target = STATIC_DIR / "index.html"
        try:
            data = target.read_bytes()
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        mime = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{mime}; charset=utf-8" if mime.startswith("text/") else mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)


def open_later(url: str) -> None:
    def opener():
        time.sleep(0.45)
        try:
            subprocess.Popen(
                ["firefox", "--new-window", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except OSError:
            webbrowser.open_new(url)

    threading.Thread(target=opener, daemon=True).start()


def already_running(url: str) -> bool:
    try:
        with urllib.request.urlopen(url + "/api/health", timeout=0.6) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError):
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Локальная лента новостей из Markdown")
    parser.add_argument("--open", action="store_true", help="открыть интерфейс в браузере")
    parser.add_argument("--no-open", action="store_true", help="не открывать браузер")
    args = parser.parse_args()
    config = load_config()
    save_config(config)
    Path(config["news_dir"]).mkdir(parents=True, exist_ok=True)
    url = f"http://{config['host']}:{config['port']}"
    if already_running(url):
        if not args.no_open:
            open_later(url)
            time.sleep(0.8)
        return
    server = NewsServer((config["host"], config["port"]), Handler, config)
    print(f"Агентская лента: {url}")
    print(f"Папка новостей: {config['news_dir']}")
    if args.open and not args.no_open:
        open_later(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
