"""Duelist Hub local web server for Yu-Gi-Oh! GX: Tag Force 2 Save File Deck Editor.

Zero external dependencies (Python 3.8+ standard library only).
- Hardened `ThreadingHTTPServer` bound to 127.0.0.1 by default
- Strict static file allowlist (blocks .git, *.py, DATA0, *.bak, tests/, cache/)
- Auto-loads decrypted PPSSPP DATA0 save or seamlessly falls back to Demo Mode
- Supports browser DATA0 upload/download, backup restoration, and opt-in local card cache
"""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import sys
import threading
from urllib.parse import parse_qs, urlparse
import webbrowser
from typing import Any, Dict, Optional, Tuple

from card_cache import CardCacheManager
from tagforce_save import (
    DEFAULT_DB_PATH,
    DEFAULT_SAMPLE_DECK_PATH,
    DeckValidationError,
    EncryptedSaveError,
    InvalidSaveError,
    _atomic_write_bytes,
    detect_region,
    find_save_path,
    list_backups,
    load_card_db,
    load_sample_deck,
    read_deck_bytes,
    restore_backup,
    save_deck_to_path,
    validate_deck_payload,
)

DIRECTORY = os.path.dirname(os.path.abspath(__file__))

MAX_JSON_BODY_BYTES = 1 * 1024 * 1024     # 1 MB
MAX_UPLOAD_SAVE_BYTES = 2 * 1024 * 1024   # 2 MB

ALLOWED_STATIC_FILES: Dict[str, Tuple[str, str]] = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/index.css": ("index.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/cards_db.json": ("cards_db.json", "application/json; charset=utf-8"),
    "/sample_deck.json": ("sample_deck.json", "application/json; charset=utf-8"),
    "/favicon.ico": ("favicon.ico", "image/x-icon"),
}

_FORBIDDEN_PREFIXES = ("/.git", "/tests", "/cache")
_FORBIDDEN_SUFFIXES = (".py", ".pyc", ".bak", ".ehp", ".bin", ".sav")


class DuelistHubState:
    """Thread-safe runtime state shared across HTTP handler threads."""

    def __init__(
        self,
        *,
        static_dir: str = DIRECTORY,
        db_path: str = DEFAULT_DB_PATH,
        sample_deck_path: str = DEFAULT_SAMPLE_DECK_PATH,
        cache_dir: Optional[str] = None,
        art_dir: Optional[str] = None,
        explicit_save: Optional[str] = None,
        force_demo: bool = False,
    ):
        self.static_dir = os.path.abspath(static_dir)
        self.db_path = os.path.abspath(db_path)
        self.sample_deck_path = os.path.abspath(sample_deck_path)
        self.cards_db = load_card_db(self.db_path)
        self.cache = CardCacheManager(cache_dir=cache_dir, art_dir=art_dir)
        self._lock = threading.RLock()

        self.mode: str = "demo"
        self.save_path: Optional[str] = None
        self.region: Optional[str] = None
        self.encrypted: bool = False
        self.deck_offset: Optional[int] = None
        self.deck: Dict[str, Any] = load_sample_deck(self.sample_deck_path)

        if not force_demo:
            self._init_from_disk(explicit_save)

    def _init_from_disk(self, explicit_save: Optional[str]) -> None:
        discovered = find_save_path(explicit_path=explicit_save, search_root=self.static_dir)
        if not discovered:
            return
        self.save_path = discovered
        self.region = detect_region(discovered)
        try:
            with open(discovered, "rb") as f:
                raw = f.read()
            loaded = read_deck_bytes(raw, self.cards_db)
            self.mode = "save"
            self.encrypted = False
            self.deck_offset = loaded["deck_offset"]
            self.deck = {
                "name": loaded["name"],
                "main": loaded["main"],
                "side": loaded["side"],
                "extra": loaded["extra"],
            }
        except EncryptedSaveError:
            self.mode = "demo"
            self.encrypted = True
            self.deck_offset = None
        except (InvalidSaveError, OSError) as err:
            print(f"[WARN] Could not load save at {discovered}: {err}. Falling back to Demo Mode.")
            self.mode = "demo"
            self.encrypted = False
            self.deck_offset = None

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            settings = self.cache.get_settings()
            backups = list_backups(self.save_path) if (self.mode == "save" and self.save_path) else []
            return {
                "mode": self.mode,
                "save_path": self.save_path,
                "region": self.region,
                "encrypted": self.encrypted,
                "deck_offset": self.deck_offset,
                "backups": backups,
                "art_cache_enabled": settings["art_cache_enabled"],
                "art_dir_configured": settings["art_dir_configured"],
                "text_cache_count": self.cache.get_text_cache_count(),
                "auto_unlock_default": settings["auto_unlock_default"],
            }

    def get_deck(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "mode": self.mode,
                "name": self.deck["name"],
                "main": list(self.deck["main"]),
                "side": list(self.deck["side"]),
                "extra": list(self.deck["extra"]),
            }

    def save_deck(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            settings = self.cache.get_settings()
            auto_unlock = payload.get("auto_unlock", settings["auto_unlock_default"])
            if not isinstance(auto_unlock, bool):
                auto_unlock = bool(auto_unlock)

            clean_deck = validate_deck_payload(payload, self.cards_db)

            if self.mode == "save" and self.save_path:
                res = save_deck_to_path(
                    self.save_path,
                    clean_deck,
                    self.cards_db,
                    auto_unlock=auto_unlock,
                )
                updated = res["deck"]
                self.deck_offset = updated["deck_offset"]
                self.deck = {
                    "name": updated["name"],
                    "main": updated["main"],
                    "side": updated["side"],
                    "extra": updated["extra"],
                }
                return {
                    "status": "success",
                    "mode": "save",
                    "message": (
                        f"Saved '{self.deck['name']}' to DATA0 "
                        f"(Main={len(self.deck['main'])}, Side={len(self.deck['side'])}, Extra={len(self.deck['extra'])})."
                    ),
                    "deck": self.get_deck(),
                    "backup": res["backup"],
                    "backups": res["backups"],
                }

            # Demo Mode in-memory session save
            self.deck = {
                "name": clean_deck["name"],
                "main": list(clean_deck["main"]),
                "side": list(clean_deck["side"]),
                "extra": list(clean_deck["extra"]),
            }
            return {
                "status": "success",
                "mode": "demo",
                "message": (
                    f"Saved '{self.deck['name']}' in Demo Mode session "
                    f"(Main={len(self.deck['main'])}, Side={len(self.deck['side'])}, Extra={len(self.deck['extra'])})."
                ),
                "deck": self.get_deck(),
                "backups": [],
            }

    def upload_save(self, raw_bytes: bytes) -> Dict[str, Any]:
        with self._lock:
            loaded = read_deck_bytes(raw_bytes, self.cards_db)
            upload_path = os.path.join(self.cache.cache_dir, "uploaded_DATA0")
            # Clear prior uploaded backups so a newly uploaded save starts clean
            for old_bak in list_backups(upload_path):
                try:
                    os.remove(os.path.join(self.cache.cache_dir, old_bak))
                except OSError:
                    pass
            _atomic_write_bytes(upload_path, raw_bytes)

            self.mode = "save"
            self.save_path = upload_path
            self.region = "Uploaded"
            self.encrypted = False
            self.deck_offset = loaded["deck_offset"]
            self.deck = {
                "name": loaded["name"],
                "main": loaded["main"],
                "side": loaded["side"],
                "extra": loaded["extra"],
            }
            return {
                "status": "success",
                "message": f"Loaded uploaded DATA0 save ('{self.deck['name']}').",
                "deck": self.get_deck(),
                "status_info": self.get_status(),
            }

    def read_current_save_bytes(self) -> Optional[bytes]:
        with self._lock:
            if self.mode != "save" or not self.save_path or not os.path.isfile(self.save_path):
                return None
            with open(self.save_path, "rb") as f:
                return f.read()

    def restore_save_backup(self, backup_name: str) -> Dict[str, Any]:
        with self._lock:
            if self.mode != "save" or not self.save_path:
                raise FileNotFoundError("Cannot restore backup while in Demo Mode.")
            res = restore_backup(self.save_path, backup_name, cards_db=self.cards_db)
            loaded = res["deck"]
            self.deck_offset = loaded["deck_offset"]
            self.deck = {
                "name": loaded["name"],
                "main": loaded["main"],
                "side": loaded["side"],
                "extra": loaded["extra"],
            }
            return {
                "status": "success",
                "message": f"Restored backup '{backup_name}'.",
                "deck": self.get_deck(),
                "backups": res["backups"],
                "status_info": self.get_status(),
            }


def _make_handler(state: DuelistHubState):
    class DuelistHubHandler(BaseHTTPRequestHandler):
        server_version = "DuelistHub/2.0"

        def log_message(self, format: str, *args: Any) -> None:
            if not getattr(self.server, "quiet", False):
                super().log_message(format, *args)

        def _send_json(self, status_code: int, payload: Any) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_bytes(
            self,
            status_code: int,
            data: bytes,
            content_type: str,
            cache_control: str = "no-store",
            extra_headers: Optional[Dict[str, str]] = None,
        ) -> None:
            self.send_response(status_code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", cache_control)
            if extra_headers:
                for k, v in extra_headers.items():
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _read_body(self, max_bytes: int) -> Tuple[Optional[bytes], Optional[Tuple[int, str]]]:
            raw_len = self.headers.get("Content-Length")
            if raw_len is None:
                return None, (400, "Missing Content-Length header.")
            try:
                length = int(raw_len)
            except ValueError:
                return None, (400, "Invalid Content-Length header.")
            if length < 0:
                return None, (400, "Negative Content-Length header.")
            if length > max_bytes:
                return None, (413, f"Request payload exceeds {max_bytes} byte limit.")
            return self.rfile.read(length), None

        def _read_json_body(self) -> Tuple[Optional[Dict[str, Any]], Optional[Tuple[int, str]]]:
            raw, err = self._read_body(MAX_JSON_BODY_BYTES)
            if err is not None:
                return None, err
            try:
                parsed = json.loads((raw or b"").decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                return None, (400, f"Malformed JSON body: {exc}")
            if not isinstance(parsed, dict):
                return None, (400, "JSON body must be an object.")
            return parsed, None

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path

            # API endpoints
            if path == "/api/status":
                self._send_json(200, state.get_status())
                return

            if path == "/api/deck":
                self._send_json(200, state.get_deck())
                return

            if path == "/api/settings":
                self._send_json(200, state.cache.get_settings())
                return

            if path == "/api/card_descriptions":
                self._send_json(200, state.cache.get_descriptions())
                return

            if path == "/api/download_save":
                raw = state.read_current_save_bytes()
                if raw is None:
                    self._send_json(404, {"status": "error", "message": "No active DATA0 save loaded."})
                    return
                self._send_bytes(
                    200,
                    raw,
                    "application/octet-stream",
                    cache_control="no-store",
                    extra_headers={"Content-Disposition": 'attachment; filename="DATA0"'},
                )
                return

            if path.startswith("/api/card_image/"):
                passcode = path[len("/api/card_image/") :].strip("/")
                qs = parse_qs(parsed.query)
                size = (qs.get("size", ["small"])[0] or "small").lower()
                result = state.cache.get_card_image(passcode, size=size)
                if result is None:
                    self._send_json(404, {"status": "error", "message": "Card artwork unavailable."})
                    return
                img_bytes, ctype = result
                self._send_bytes(200, img_bytes, ctype, cache_control="private, max-age=86400")
                return

            # Strict static file allowlist
            if path in ALLOWED_STATIC_FILES:
                filename, content_type = ALLOWED_STATIC_FILES[path]
                file_path = os.path.join(state.static_dir, filename)
                if not os.path.isfile(file_path):
                    self._send_json(404, {"status": "error", "message": "Asset not found."})
                    return
                with open(file_path, "rb") as f:
                    data = f.read()
                cache_hdr = "no-cache" if filename.endswith((".html", ".js", ".css", ".json")) else "public, max-age=3600"
                self._send_bytes(200, data, content_type, cache_control=cache_hdr)
                return

            # Explicitly forbid path traversal and internal/source files
            lower_path = path.lower()
            if (
                ".." in path
                or lower_path.startswith(_FORBIDDEN_PREFIXES)
                or lower_path.endswith(_FORBIDDEN_SUFFIXES)
                or lower_path.endswith("/data0")
            ):
                self._send_json(403, {"status": "error", "message": "Forbidden."})
                return

            self._send_json(404, {"status": "error", "message": "Not found."})

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path

            if path == "/api/save_deck":
                body, err = self._read_json_body()
                if err is not None:
                    self._send_json(err[0], {"status": "error", "message": err[1]})
                    return
                try:
                    res = state.save_deck(body)  # type: ignore[arg-type]
                    self._send_json(200, res)
                except (DeckValidationError, EncryptedSaveError, InvalidSaveError, FileNotFoundError) as exc:
                    self._send_json(400, {"status": "error", "message": str(exc)})
                except Exception as exc:
                    self._send_json(500, {"status": "error", "message": f"Server error: {exc}"})
                return

            if path == "/api/upload_save":
                raw, err = self._read_body(MAX_UPLOAD_SAVE_BYTES)
                if err is not None:
                    self._send_json(err[0], {"status": "error", "message": err[1]})
                    return
                try:
                    res = state.upload_save(raw or b"")
                    self._send_json(200, res)
                except EncryptedSaveError as exc:
                    self._send_json(400, {"status": "error", "encrypted": True, "message": str(exc)})
                except InvalidSaveError as exc:
                    self._send_json(400, {"status": "error", "message": str(exc)})
                except Exception as exc:
                    self._send_json(500, {"status": "error", "message": f"Upload failed: {exc}"})
                return

            if path == "/api/restore_backup":
                body, err = self._read_json_body()
                if err is not None:
                    self._send_json(err[0], {"status": "error", "message": err[1]})
                    return
                backup_name = (body or {}).get("backup")
                if not isinstance(backup_name, str) or not backup_name:
                    self._send_json(400, {"status": "error", "message": "Missing 'backup' filename."})
                    return
                try:
                    res = state.restore_save_backup(backup_name)
                    self._send_json(200, res)
                except (ValueError, FileNotFoundError, EncryptedSaveError, InvalidSaveError) as exc:
                    self._send_json(400, {"status": "error", "message": str(exc)})
                except Exception as exc:
                    self._send_json(500, {"status": "error", "message": f"Restore failed: {exc}"})
                return

            if path == "/api/settings":
                body, err = self._read_json_body()
                if err is not None:
                    self._send_json(err[0], {"status": "error", "message": err[1]})
                    return
                updated = state.cache.update_settings(
                    art_cache_enabled=(body or {}).get("art_cache_enabled"),
                    auto_unlock_default=(body or {}).get("auto_unlock_default"),
                )
                self._send_json(200, {"status": "success", **updated})
                return

            if path == "/api/sync_descriptions":
                try:
                    count = state.cache.sync_descriptions(state.cards_db)
                    self._send_json(
                        200,
                        {
                            "status": "success",
                            "count": count,
                            "message": f"Cached {count} card descriptions locally.",
                        },
                    )
                except Exception as exc:
                    self._send_json(502, {"status": "error", "message": f"Failed to sync descriptions: {exc}"})
                return

            self._send_json(404, {"status": "error", "message": "Unknown API endpoint."})

    return DuelistHubHandler


class _ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def create_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    *,
    state: Optional[DuelistHubState] = None,
    auto_fallback_port: bool = True,
    quiet: bool = False,
) -> Tuple[ThreadingHTTPServer, int, DuelistHubState]:
    """Creates and binds the ThreadingHTTPServer, optionally falling back to a free port."""
    hub_state = state or DuelistHubState()
    handler_cls = _make_handler(hub_state)

    if port == 0 or not auto_fallback_port:
        httpd = _ReusableThreadingHTTPServer((host, port), handler_cls)
        httpd.quiet = quiet  # type: ignore[attr-defined]
        actual_port = httpd.server_address[1]
        return httpd, actual_port, hub_state

    last_err: Optional[OSError] = None
    for candidate_port in range(port, port + 25):
        try:
            httpd = _ReusableThreadingHTTPServer((host, candidate_port), handler_cls)
            httpd.quiet = quiet  # type: ignore[attr-defined]
            return httpd, candidate_port, hub_state
        except OSError as err:
            last_err = err
    raise OSError(f"Could not bind to any port in range {port}..{port + 24}: {last_err}")


def main(argv: Optional[list] = None) -> int:
    default_port = int(os.environ.get("TAGFORCE_PORT", "8000"))
    parser = argparse.ArgumentParser(
        description="Duelist Hub - Yu-Gi-Oh! GX: Tag Force 2 Save File Deck Editor"
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1).")
    parser.add_argument(
        "--port",
        type=int,
        default=default_port,
        help="Bind port (default: $TAGFORCE_PORT or 8000; auto-increments if busy).",
    )
    parser.add_argument("--save", default=None, help="Explicit path to decrypted DATA0 save file.")
    parser.add_argument("--demo", action="store_true", help="Force Demo Mode using sample_deck.json.")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open the web browser.")
    args = parser.parse_args(argv)

    state = DuelistHubState(explicit_save=args.save, force_demo=args.demo)
    httpd, actual_port, _ = create_server(
        host=args.host,
        port=args.port,
        state=state,
        auto_fallback_port=True,
    )

    url = f"http://{args.host}:{actual_port}"
    print("Starting Duelist Hub - Yu-Gi-Oh! GX: Tag Force 2 Deck Editor")
    if actual_port != args.port:
        print(f"[INFO] Port {args.port} was busy; using port {actual_port} instead.")

    status = state.get_status()
    if status["mode"] == "save":
        print(f"[SAVE] Connected to {status['save_path']} ({status['region']}) @ 0x{status['deck_offset']:X}")
    elif status["encrypted"]:
        print(f"[WARN] Found encrypted save at {status['save_path']}; running in Demo Mode until decrypted.")
    else:
        print("[DEMO] No decrypted DATA0 found (or --demo active); running in Demo Mode.")

    print(f"[HTTP] Server listening at {url}")
    print("Press Ctrl+C to stop.")

    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
    finally:
        httpd.shutdown()
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
