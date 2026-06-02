#!/usr/bin/env python3
"""Import a folder of Markdown files into Notion as child pages.

This script uses the user's existing local Notion login. It is not an official
Notion API client. It intentionally avoids printing decrypted cookie values.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path


DEFAULT_CLIENT_VERSION = "23.13.0.4030"


def normalize_page_id(value: str) -> str:
    raw = value.strip().split("?")[0].rstrip("/").split("/")[-1]
    dashed = re.search(
        r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$",
        raw,
    )
    if dashed:
        s = dashed.group(1).replace("-", "").lower()
    else:
        undashed = re.search(r"(?:^|[^0-9a-fA-F])([0-9a-fA-F]{32})$", raw)
        if not undashed:
            raise ValueError(f"Cannot parse Notion page id from {value!r}")
        # Slug URLs can look like "title-<32 hex id>"; choose the final hex run.
        s = undashed.group(1).lower()
    if len(s) != 32:
        raise ValueError(f"Cannot parse Notion page id from {value!r}")
    return f"{s[0:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:32]}"


def now_ms() -> int:
    return int(time.time() * 1000)


def random_id() -> str:
    return str(uuid.uuid4())


def key_from_keychain(service: str, account: str) -> bytes:
    password = subprocess.check_output(
        ["security", "find-generic-password", "-s", service, "-a", account, "-w"]
    ).rstrip(b"\n")
    return hashlib.pbkdf2_hmac("sha1", password, b"saltysalt", 1003, 16)


def decrypt_chromium_cookie(encrypted_value: bytes, key: bytes) -> str:
    payload = encrypted_value[3:] if encrypted_value.startswith(b"v10") else encrypted_value
    proc = subprocess.run(
        [
            "openssl",
            "enc",
            "-d",
            "-aes-128-cbc",
            "-K",
            key.hex(),
            "-iv",
            (b" " * 16).hex(),
            "-nopad",
        ],
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    out = proc.stdout
    if out:
        pad = out[-1]
        if 1 <= pad <= 16 and out.endswith(bytes([pad]) * pad):
            out = out[:-pad]
    if len(out) > 32:
        candidate = out[32:]
        try:
            return candidate.decode("utf-8")
        except UnicodeDecodeError:
            pass
    return out.decode("utf-8")


def cookie_db_for_profile(profile: str) -> tuple[Path, str, str]:
    home = Path.home()
    if profile == "notion-desktop":
        return (
            home / "Library/Application Support/Notion/Partitions/notion/Cookies",
            "Notion Safe Storage",
            "Notion Key",
        )
    if profile == "codex-iab":
        return (
            home / "Library/Application Support/Codex/Default/Partitions/codex-browser-app/Cookies",
            "Codex Safe Storage",
            "Codex Key",
        )
    raise ValueError(f"Unknown cookie profile: {profile}")


def load_cookies(profile: str) -> dict[str, str]:
    cookie_db, service, account = cookie_db_for_profile(profile)
    if not cookie_db.exists():
        raise FileNotFoundError(f"Cookie database not found: {cookie_db}")
    key = key_from_keychain(service, account)
    wanted = {
        "token_v2",
        "device_id",
        "notion_user_id",
        "notion_users",
        "notion_locale",
        "NEXT_LOCALE",
        "notion_browser_id",
        "csrf",
    }
    conn = sqlite3.connect(cookie_db)
    rows = conn.execute(
        """
        select host_key, name, value, encrypted_value
        from cookies
        where host_key like '%notion.%' or host_key like '%notion.com'
        """
    ).fetchall()
    conn.close()
    cookies: dict[str, str] = {}
    for _host, name, value, encrypted_value in rows:
        if name not in wanted:
            continue
        cookies[name] = value or decrypt_chromium_cookie(encrypted_value, key)
    if "token_v2" not in cookies:
        raise RuntimeError("No token_v2 cookie found. Confirm the selected Notion profile is logged in.")
    return cookies


def make_headers(cookies: dict[str, str], space_id: str | None = None) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items()),
        "User-Agent": "Mozilla/5.0 NotionDesktop Chrome",
        "notion-client-version": DEFAULT_CLIENT_VERSION,
        "notion-client-platform": "web",
    }
    if cookies.get("notion_user_id"):
        headers["x-notion-active-user-header"] = cookies["notion_user_id"]
    if space_id:
        headers["x-notion-space-id"] = space_id
        headers["x-notion-client-version"] = DEFAULT_CLIENT_VERSION
    return headers


def local_cache_context(parent_id: str) -> tuple[str | None, str | None]:
    db = Path.home() / "Library/Application Support/Notion/notion.db"
    if not db.exists():
        return None, None
    try:
        conn = sqlite3.connect(db)
        row = conn.execute(
            "select space_id, created_by_id from block where id = ? limit 1",
            (parent_id,),
        ).fetchone()
        conn.close()
    except sqlite3.Error:
        return None, None
    if not row:
        return None, None
    return row[0], row[1]


def notion_post(path: str, payload: dict, headers: dict[str, str]) -> dict:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        f"https://www.notion.so/api/v3/{path}",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {exc.code}: {raw[:1200]}") from exc


def rich_text(text: str) -> list:
    if not text:
        return []
    text = text.replace("<br>", "\n")
    parts = []
    pattern = re.compile(r"(\*\*.+?\*\*|`.+?`|\[.+?\]\(.+?\)|\*[^*\n]+?\*)")
    pos = 0
    for match in pattern.finditer(text):
        if match.start() > pos:
            parts.append([text[pos : match.start()]])
        token = match.group(0)
        if token.startswith("**") and token.endswith("**"):
            parts.append([token[2:-2], [["b"]]])
        elif token.startswith("`") and token.endswith("`"):
            parts.append([token[1:-1], [["c"]]])
        elif token.startswith("[") and "](" in token and token.endswith(")"):
            label, url = token[1:-1].split("](", 1)
            parts.append([label] if url.endswith(".md") else [label, [["a", url]]])
        elif token.startswith("*") and token.endswith("*"):
            parts.append([token[1:-1], [["i"]]])
        else:
            parts.append([token])
        pos = match.end()
    if pos < len(text):
        parts.append([text[pos:]])
    return [p for p in parts if p[0]]


def rt(text: str, annotations=None) -> list:
    if not text:
        return []
    return [[text, annotations]] if annotations else [[text]]


def split_long_text(text: str, limit: int = 1800) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks, current = [], ""
    for sentence in re.split(r"(?<=[。！？.!?])\s*", text):
        if not sentence:
            continue
        if current and len(current) + len(sentence) > limit:
            chunks.append(current)
            current = sentence
        else:
            current += sentence
    if current:
        chunks.append(current)
    return chunks


def make_block(block_id: str, block_type: str, parent_id: str, space_id: str, user_id: str, **extra) -> dict:
    ts = now_ms()
    block = {
        "id": block_id,
        "version": 1,
        "type": block_type,
        "properties": extra.pop("properties", None),
        "content": extra.pop("content", None),
        "format": extra.pop("format", None),
        "parent_id": parent_id,
        "parent_table": "block",
        "alive": True,
        "created_time": ts,
        "last_edited_time": ts,
        "space_id": space_id,
        "created_by_table": "notion_user",
        "created_by_id": user_id,
        "last_edited_by_table": "notion_user",
        "last_edited_by_id": user_id,
    }
    block.update(extra)
    return {k: v for k, v in block.items() if v is not None}


def parse_table(lines: list[str], parent_id: str, space_id: str, user_id: str, blocks: list[dict]) -> str:
    rows = []
    for line in lines:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and all(re.fullmatch(r":?-{3,}:?", c.replace(" ", "")) for c in cells):
            continue
        rows.append(cells)
    if not rows:
        return ""
    max_cols = max(len(r) for r in rows)
    columns = [f"col_{i}" for i in range(max_cols)]
    table_id = random_id()
    row_ids = []
    for row in rows:
        row_id = random_id()
        row_ids.append(row_id)
        props = {}
        for i, col in enumerate(columns):
            props[col] = rich_text(row[i] if i < len(row) else "")
        blocks.append(make_block(row_id, "table_row", table_id, space_id, user_id, properties=props))
    blocks.append(
        make_block(
            table_id,
            "table",
            parent_id,
            space_id,
            user_id,
            content=row_ids,
            format={"table_block_column_order": columns, "table_block_column_header": True},
        )
    )
    return table_id


def markdown_to_blocks(path: Path, page_id: str, space_id: str, user_id: str, title_prefix: str = "") -> tuple[str, list[str], list[dict]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    title = path.stem
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip()
        lines = lines[1:]
    title = f"{title_prefix}{title}"
    blocks, content_ids = [], []
    i = 0

    def add_textual(block_type: str, text: str) -> None:
        for chunk in split_long_text(text):
            block_id = random_id()
            blocks.append(make_block(block_id, block_type, page_id, space_id, user_id, properties={"title": rich_text(chunk)}))
            content_ids.append(block_id)

    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            i += 1
            continue
        if stripped == "---":
            block_id = random_id()
            blocks.append(make_block(block_id, "divider", page_id, space_id, user_id))
            content_ids.append(block_id)
            i += 1
            continue
        if stripped == "$$":
            formula = []
            i += 1
            while i < len(lines) and lines[i].strip() != "$$":
                formula.append(lines[i])
                i += 1
            i += 1
            formula_text = "\n".join(formula).strip()
            if formula_text:
                block_id = random_id()
                blocks.append(make_block(block_id, "equation", page_id, space_id, user_id, properties={"title": rt(formula_text)}))
                content_ids.append(block_id)
            continue
        if stripped.startswith("|"):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1
            table_id = parse_table(table_lines, page_id, space_id, user_id, blocks)
            if table_id:
                content_ids.append(table_id)
            continue
        if stripped.startswith("```"):
            language = stripped.strip("`").strip() or "plain text"
            code = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            block_id = random_id()
            blocks.append(
                make_block(
                    block_id,
                    "code",
                    page_id,
                    space_id,
                    user_id,
                    properties={"title": rt("\n".join(code))},
                    format={"code_language": language},
                )
            )
            content_ids.append(block_id)
            continue
        header = re.match(r"^(#{2,6})\s+(.+)$", stripped)
        if header:
            add_textual("sub_header" if len(header.group(1)) == 2 else "sub_sub_header", header.group(2).strip())
            i += 1
            continue
        if stripped.startswith(">"):
            quote_lines = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote_lines.append(lines[i].strip()[1:].strip())
                i += 1
            add_textual("quote", "\n".join(quote_lines).strip())
            continue
        bullet = re.match(r"^[-*]\s+(.+)$", stripped)
        if bullet:
            add_textual("bulleted_list", bullet.group(1).strip())
            i += 1
            continue
        numbered = re.match(r"^\d+\.\s+(.+)$", stripped)
        if numbered:
            add_textual("numbered_list", numbered.group(1).strip())
            i += 1
            continue
        paragraph = [stripped]
        i += 1
        while i < len(lines):
            nxt = lines[i].strip()
            if (
                not nxt
                or nxt == "$$"
                or nxt == "---"
                or nxt.startswith("|")
                or nxt.startswith("```")
                or nxt.startswith(">")
                or re.match(r"^#{1,6}\s+", nxt)
                or re.match(r"^[-*]\s+", nxt)
                or re.match(r"^\d+\.\s+", nxt)
            ):
                break
            paragraph.append(nxt)
            i += 1
        add_textual("text", "\n".join(paragraph).strip())
    return title, content_ids, blocks


def op_set(block: dict) -> dict:
    return {"table": "block", "id": block["id"], "path": [], "command": "set", "args": block}


def op_list_after(parent_id: str, child_id: str, after_id: str | None = None) -> dict:
    args = {"id": child_id}
    if after_id:
        args["after"] = after_id
    return {"table": "block", "id": parent_id, "path": ["content"], "command": "listAfter", "args": args}


def op_list_remove(parent_id: str, child_id: str) -> dict:
    return {"table": "block", "id": parent_id, "path": ["content"], "command": "listRemove", "args": {"id": child_id}}


def get_parent(headers: dict, parent_id: str, space_id: str | None = None) -> dict:
    request = {"table": "block", "id": parent_id, "version": -1}
    if space_id:
        request["spaceId"] = space_id
    resp = notion_post("getRecordValues", {"requests": [request]}, headers)
    value = (resp.get("results") or [{}])[0].get("value")
    if not value:
        raise RuntimeError("Parent page did not return a value. Check page id, login, and spaceId routing.")
    return value


def discover_context(cookies: dict[str, str], parent_id: str) -> tuple[str, str, dict, dict]:
    headers = make_headers(cookies)
    parent = None
    space_id = None
    user_id = None
    cached_space_id, cached_user_id = local_cache_context(parent_id)
    if cached_space_id:
        space_id = cached_space_id
        user_id = cached_user_id
    else:
        try:
            parent = get_parent(headers, parent_id)
            space_id = parent.get("space_id") or parent.get("spaceId")
        except RuntimeError as exc:
            if "MemcachedCrossCellError" not in str(exc):
                raise
    if not space_id:
        raise RuntimeError("Could not discover parent space_id. Open the page in Notion once, then retry.")
    scoped_headers = make_headers(cookies, space_id)
    parent = get_parent(scoped_headers, parent_id, space_id)
    user_id = parent.get("created_by_id") or user_id or cookies.get("notion_user_id")
    if not user_id:
        raise RuntimeError("Could not discover Notion user id")
    return space_id, user_id, parent, scoped_headers


def save_transaction(headers: dict, space_id: str, operations: list[dict], debug_name: str) -> None:
    payload = {
        "requestId": str(uuid.uuid4()),
        "transactions": [{"id": str(uuid.uuid4()), "spaceId": space_id, "debug": {"userAction": debug_name}, "operations": operations}],
    }
    notion_post("saveTransactions", payload, headers)


def verify_pages(headers: dict, space_id: str, page_ids: list[str]) -> list[tuple[str, str, int]]:
    requests = [{"table": "block", "id": page_id, "version": -1, "spaceId": space_id} for page_id in page_ids]
    resp = notion_post("getRecordValues", {"requests": requests}, headers)
    rows = []
    for result in resp.get("results", []):
        value = result.get("value") or {}
        title = ""
        try:
            title = value.get("properties", {}).get("title", [[""]])[0][0]
        except Exception:
            title = ""
        rows.append((value.get("id", ""), title, len(value.get("content") or [])))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Markdown files into Notion as child pages.")
    parser.add_argument("--parent-page-id", required=True, help="Notion parent page URL or page id.")
    parser.add_argument("--notes-dir", required=True, type=Path, help="Folder containing .md files.")
    parser.add_argument("--cookie-profile", default="notion-desktop", choices=["notion-desktop", "codex-iab"])
    parser.add_argument("--page-title-prefix", default="")
    parser.add_argument("--clean-parent", action="store_true", help="Remove all parent children except created pages after import.")
    parser.add_argument("--remove-child-id", action="append", default=[], help="Remove a known bad child id from the parent content list.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    parent_id = normalize_page_id(args.parent_page_id)
    note_paths = sorted(args.notes_dir.glob("*.md"))
    if not note_paths:
        raise RuntimeError(f"No Markdown files found in {args.notes_dir}")

    cookies = load_cookies(args.cookie_profile)
    space_id, user_id, parent, headers = discover_context(cookies, parent_id)
    parent_content = parent.get("content") or []
    after_id = parent_content[-1] if parent_content else None

    if args.dry_run:
        print(json.dumps({"parent_id": parent_id, "space_id": space_id, "markdown_files": [str(p) for p in note_paths]}, ensure_ascii=False, indent=2))
        return 0

    created_ids = []
    for path in note_paths:
        page_id = random_id()
        title, content_ids, blocks = markdown_to_blocks(path, page_id, space_id, user_id, args.page_title_prefix)
        page = make_block(page_id, "page", parent_id, space_id, user_id, properties={"title": rt(title)}, content=content_ids)
        operations = [op_set(page), *(op_set(block) for block in blocks), op_list_after(parent_id, page_id, after_id)]
        save_transaction(headers, space_id, operations, "CodexMarkdownImport")
        created_ids.append(page_id)
        after_id = page_id
        print(f"OK {path.name} {page_id}")

    cleanup_ids = [normalize_page_id(x) for x in args.remove_child_id]
    if args.clean_parent:
        latest_parent = get_parent(headers, parent_id, space_id)
        cleanup_ids.extend([child_id for child_id in latest_parent.get("content", []) if child_id not in set(created_ids)])
    if cleanup_ids:
        for i in range(0, len(cleanup_ids), 150):
            save_transaction(headers, space_id, [op_list_remove(parent_id, x) for x in cleanup_ids[i : i + 150]], "CodexMarkdownImportCleanup")
        print(f"REMOVED {len(cleanup_ids)} parent entries")

    for page_id, title, count in verify_pages(headers, space_id, created_ids):
        print(f"VERIFY {page_id} | {title} | blocks={count}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
