#!/usr/bin/env python3
"""Build a static snapshot of Agent News for GitHub Pages."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

from server import collect_articles, load_config


APP_DIR = Path(__file__).resolve().parent
SOURCE_APP = APP_DIR / "app"
DIST_DIR = APP_DIR / "dist"
NEWS_DIR = APP_DIR / "news"
AUTH_SALT = "agent-news-pages-2026-v1"
ALLOWED_IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif"}


def password_hash(password: str) -> str:
    return hashlib.sha256((AUTH_SALT + password).encode("utf-8")).hexdigest()


def build_auth_script(expected_hash: str) -> str:
    return f'''window.AGENT_NEWS_STATIC = true;
window.AGENT_NEWS_READY = new Promise((resolve) => {{
  document.addEventListener("DOMContentLoaded", () => {{
    const gate = document.querySelector("#authGate");
    const form = document.querySelector("#authForm");
    const input = document.querySelector("#authPassword");
    const error = document.querySelector("#authError");
    const sessionKey = "agent-news-pages-auth-v1";
    const salt = {json.dumps(AUTH_SALT)};
    const expected = {json.dumps(expected_hash)};

    if (sessionStorage.getItem(sessionKey) === expected) {{
      gate.hidden = true;
      resolve();
      return;
    }}

    gate.hidden = false;
    form.addEventListener("submit", async (event) => {{
      event.preventDefault();
      error.textContent = "";
      const bytes = new TextEncoder().encode(salt + input.value);
      const digest = await crypto.subtle.digest("SHA-256", bytes);
      const actual = [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
      if (actual === expected) {{
        sessionStorage.setItem(sessionKey, expected);
        input.value = "";
        gate.hidden = true;
        resolve();
      }} else {{
        error.textContent = "Неверный пароль";
        input.select();
      }}
    }});
  }});
}});
'''


def copy_media() -> None:
    for source in NEWS_DIR.rglob("*"):
        if not source.is_file() or source.suffix.lower() not in ALLOWED_IMAGES:
            continue
        relative = source.relative_to(NEWS_DIR)
        target = DIST_DIR / "media" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def static_articles() -> list[dict]:
    config = load_config()
    config["news_dir"] = str(NEWS_DIR)
    articles = collect_articles(config)
    for article in articles:
        article["image"] = article["image"].replace("/media/", "./media/")
        article["content"] = article["content"].replace("/media/", "./media/")
    return articles


def build(expected_hash: str) -> None:
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    DIST_DIR.mkdir(parents=True)

    for name in ("styles.css", "app.js"):
        shutil.copy2(SOURCE_APP / name, DIST_DIR / name)

    index = (SOURCE_APP / "index.html").read_text(encoding="utf-8")
    index = index.replace('href="/styles.css', 'href="./styles.css')
    index = index.replace('src="/app.js', 'src="./app.js')
    index = index.replace(
        '<script src="./app.js',
        '<script src="./pages-auth.js"></script>\n    <script src="./app.js',
    )
    (DIST_DIR / "index.html").write_text(index, encoding="utf-8")
    (DIST_DIR / "404.html").write_text(index, encoding="utf-8")
    (DIST_DIR / ".nojekyll").touch()
    (DIST_DIR / "pages-auth.js").write_text(build_auth_script(expected_hash), encoding="utf-8")

    articles = static_articles()
    signature = hashlib.sha1(
        "|".join(item["id"] + item["version"] for item in articles).encode("utf-8")
    ).hexdigest()[:16]
    payload = {
        "config": {"title": "Моя лента", "refresh_seconds": 60},
        "articles": articles,
        "count": len(articles),
        "signature": signature,
    }
    (DIST_DIR / "news.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    copy_media()
    print(f"Built {len(articles)} articles in {DIST_DIR}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the GitHub Pages snapshot")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--password-stdin", action="store_true", help="read the password from stdin")
    group.add_argument("--password-hash", help="reuse an existing salted SHA-256 hash")
    args = parser.parse_args()
    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
        if not password:
            raise SystemExit("Password cannot be empty")
        expected_hash = password_hash(password)
    else:
        expected_hash = args.password_hash.lower()
        if len(expected_hash) != 64 or any(char not in "0123456789abcdef" for char in expected_hash):
            raise SystemExit("Expected a 64-character SHA-256 hash")
    build(expected_hash)


if __name__ == "__main__":
    main()
