"""Opt-in local card artwork & description cache manager (YGOPRODeck ToS-compliant).

Features:
- Local disk cache under `<repo>/cache/` (gitignored; created on demand)
- Local user-supplied art directory via `TAGFORCE_ART_DIR`
- Token-bucket rate limiter (max 10 req/sec) + per-passcode single-flight lock
- Missing artwork negative cache (`cache/missing_art.json`) to avoid repeat 404s
- Opt-in local card description sync (`cache/card_descriptions.json`)
"""

import argparse
import json
import os
import tempfile
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Set, Tuple

from tagforce_save import load_card_db

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CACHE_DIR = os.path.join(_SCRIPT_DIR, "cache")

USER_AGENT = "DuelistHub-TagForce2-Editor/2.0 (Local-Cache; +https://github.com)"
YGOPRODECK_API_URL = "https://db.ygoprodeck.com/api/v7/cardinfo.php"
YGOPRODECK_IMG_SMALL = "https://images.ygoprodeck.com/images/cards_small/{card_id}.jpg"
YGOPRODECK_IMG_FULL = "https://images.ygoprodeck.com/images/cards/{card_id}.jpg"


class _TokenBucket:
    """Thread-safe token bucket rate limiter."""

    def __init__(self, rate_per_sec: float = 10.0, capacity: float = 10.0):
        self.rate = float(rate_per_sec)
        self.capacity = float(capacity)
        self.tokens = float(capacity)
        self.last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self.last_refill
                if elapsed > 0:
                    self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                    self.last_refill = now
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                wait_time = (1.0 - self.tokens) / self.rate
            time.sleep(min(wait_time, 0.25))


def _atomic_write_bytes(path: str, data: bytes) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".cache_", dir=parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise


def _atomic_write_json(path: str, obj: Any) -> None:
    raw = (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    _atomic_write_bytes(path, raw)


def normalize_passcode(passcode: Any) -> Optional[Tuple[str, str]]:
    """Validates a digits-only non-zero passcode, returning (padded_8, int_str) or None."""
    if not isinstance(passcode, str):
        return None
    s = passcode.strip()
    if not s or not s.isdigit():
        return None
    val = int(s)
    if val <= 0 or val > 999999999:
        return None
    return f"{val:08d}", str(val)


class CardCacheManager:
    """Manages local card art disk cache, TAGFORCE_ART_DIR, settings, and text cache."""

    def __init__(self, cache_dir: Optional[str] = None, art_dir: Optional[str] = None):
        self.cache_dir = os.path.abspath(cache_dir or DEFAULT_CACHE_DIR)
        self._explicit_art_dir = art_dir
        self._settings_path = os.path.join(self.cache_dir, "settings.json")
        self._small_dir = os.path.join(self.cache_dir, "cards_small")
        self._full_dir = os.path.join(self.cache_dir, "cards")
        self._missing_path = os.path.join(self.cache_dir, "missing_art.json")
        self._desc_path = os.path.join(self.cache_dir, "card_descriptions.json")

        self._meta_lock = threading.Lock()
        self._flight_locks_guard = threading.Lock()
        self._flight_locks: Dict[str, threading.Lock] = {}
        self._rate_limiter = _TokenBucket(rate_per_sec=10.0, capacity=10.0)

        self._settings = self._load_settings()
        self._missing_art: Set[str] = self._load_missing_art()

    def _get_art_dir(self) -> Optional[str]:
        candidate = self._explicit_art_dir if self._explicit_art_dir is not None else os.environ.get("TAGFORCE_ART_DIR")
        if candidate and os.path.isdir(candidate):
            return os.path.abspath(candidate)
        return None

    def is_art_dir_configured(self) -> bool:
        return self._get_art_dir() is not None

    def _load_settings(self) -> Dict[str, Any]:
        defaults = {
            "art_cache_enabled": False,
            "auto_unlock_default": True,
        }
        if not os.path.isfile(self._settings_path):
            return defaults
        try:
            with open(self._settings_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                defaults["art_cache_enabled"] = bool(loaded.get("art_cache_enabled", False))
                defaults["auto_unlock_default"] = bool(loaded.get("auto_unlock_default", True))
        except Exception:
            pass
        return defaults

    def get_settings(self) -> Dict[str, Any]:
        with self._meta_lock:
            return {
                "art_cache_enabled": bool(self._settings["art_cache_enabled"]),
                "auto_unlock_default": bool(self._settings["auto_unlock_default"]),
                "art_dir_configured": self.is_art_dir_configured(),
            }

    def update_settings(
        self,
        *,
        art_cache_enabled: Optional[bool] = None,
        auto_unlock_default: Optional[bool] = None,
    ) -> Dict[str, Any]:
        with self._meta_lock:
            if art_cache_enabled is not None:
                self._settings["art_cache_enabled"] = bool(art_cache_enabled)
            if auto_unlock_default is not None:
                self._settings["auto_unlock_default"] = bool(auto_unlock_default)
            _atomic_write_json(self._settings_path, self._settings)
            return {
                "art_cache_enabled": bool(self._settings["art_cache_enabled"]),
                "auto_unlock_default": bool(self._settings["auto_unlock_default"]),
                "art_dir_configured": self.is_art_dir_configured(),
            }

    def _load_missing_art(self) -> Set[str]:
        if not os.path.isfile(self._missing_path):
            return set()
        try:
            with open(self._missing_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return set(str(x) for x in data)
        except Exception:
            pass
        return set()

    def _record_missing_art(self, key: str) -> None:
        with self._meta_lock:
            if key not in self._missing_art:
                self._missing_art.add(key)
                _atomic_write_json(self._missing_path, sorted(self._missing_art))

    def _flight_lock_for(self, key: str) -> threading.Lock:
        with self._flight_locks_guard:
            lock = self._flight_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._flight_locks[key] = lock
            return lock

    def _read_from_art_dir(self, padded: str, int_str: str, size: str) -> Optional[Tuple[bytes, str]]:
        art_dir = self._get_art_dir()
        if not art_dir:
            return None

        search_dirs = [art_dir]
        if size == "small":
            small_sub = os.path.join(art_dir, "small")
            if os.path.isdir(small_sub):
                search_dirs.insert(0, small_sub)

        candidates = (
            (f"{padded}.jpg", "image/jpeg"),
            (f"{padded}.png", "image/png"),
            (f"{int_str}.jpg", "image/jpeg"),
            (f"{int_str}.png", "image/png"),
        )
        for directory in search_dirs:
            for fname, ctype in candidates:
                fpath = os.path.join(directory, fname)
                if os.path.isfile(fpath):
                    try:
                        with open(fpath, "rb") as f:
                            return f.read(), ctype
                    except OSError:
                        continue
        return None

    def get_card_image(self, passcode: str, size: str = "small") -> Optional[Tuple[bytes, str]]:
        """Resolves card artwork from TAGFORCE_ART_DIR, disk cache, or opt-in YGOPRODeck cache."""
        if size not in ("small", "full"):
            return None
        parsed = normalize_passcode(passcode)
        if not parsed:
            return None
        padded, int_str = parsed

        # 1. User-configured local art directory (TAGFORCE_ART_DIR)
        local_art = self._read_from_art_dir(padded, int_str, size)
        if local_art is not None:
            return local_art

        # 2. Local disk cache
        cache_subdir = self._small_dir if size == "small" else self._full_dir
        cached_path = os.path.join(cache_subdir, f"{int_str}.jpg")
        if os.path.isfile(cached_path):
            try:
                with open(cached_path, "rb") as f:
                    return f.read(), "image/jpeg"
            except OSError:
                pass

        # 3. Opt-in YGOPRODeck remote download (with negative cache + rate limit + single-flight)
        if not self.get_settings()["art_cache_enabled"]:
            return None

        flight_key = f"{size}:{int_str}"
        with self._meta_lock:
            if flight_key in self._missing_art:
                return None

        with self._flight_lock_for(flight_key):
            # Re-check after acquiring per-passcode lock
            if os.path.isfile(cached_path):
                try:
                    with open(cached_path, "rb") as f:
                        return f.read(), "image/jpeg"
                except OSError:
                    pass
            with self._meta_lock:
                if flight_key in self._missing_art:
                    return None

            self._rate_limiter.acquire()
            url_tpl = YGOPRODECK_IMG_SMALL if size == "small" else YGOPRODECK_IMG_FULL
            url = url_tpl.format(card_id=int_str)
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status != 200:
                        return None
                    img_bytes = resp.read()
                    if not img_bytes:
                        return None
                    _atomic_write_bytes(cached_path, img_bytes)
                    return img_bytes, "image/jpeg"
            except urllib.error.HTTPError as err:
                if err.code == 404:
                    self._record_missing_art(flight_key)
                return None
            except Exception:
                return None

    def get_descriptions(self) -> Dict[str, str]:
        """Returns locally cached card descriptions keyed by 8-digit passcode."""
        if not os.path.isfile(self._desc_path):
            return {}
        try:
            with open(self._desc_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    def get_text_cache_count(self) -> int:
        return len(self.get_descriptions())

    def sync_descriptions(self, cards_db: List[Dict[str, Any]]) -> int:
        """Fetches YGOPRODeck cardinfo once and caches descriptions for Tag Force 2 passcodes."""
        valid_by_int: Dict[int, str] = {}
        for card in cards_db:
            parsed = normalize_passcode(card.get("passcode", ""))
            if parsed:
                padded, int_str = parsed
                valid_by_int[int(int_str)] = padded

        req = urllib.request.Request(YGOPRODECK_API_URL, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))

        descriptions: Dict[str, str] = {}
        for item in payload.get("data", []):
            desc = item.get("desc")
            if not isinstance(desc, str) or not desc.strip():
                continue
            cid = item.get("id")
            if isinstance(cid, int) and cid in valid_by_int:
                descriptions[valid_by_int[cid]] = desc
            for img_entry in item.get("card_images", []) or []:
                alt_id = img_entry.get("id")
                if isinstance(alt_id, int) and alt_id in valid_by_int:
                    descriptions.setdefault(valid_by_int[alt_id], desc)

        _atomic_write_json(self._desc_path, descriptions)
        return len(descriptions)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Duelist Hub local card cache utility (YGOPRODeck ToS-compliant)."
    )
    parser.add_argument(
        "--sync-text",
        action="store_true",
        help="Download and cache card effect text locally in cache/card_descriptions.json.",
    )
    parser.add_argument(
        "--cache-dir",
        default=None,
        help="Override local cache directory (default: ./cache).",
    )
    args = parser.parse_args()

    if not args.sync_text:
        parser.print_help()
        return 0

    cards_db = load_card_db()
    mgr = CardCacheManager(cache_dir=args.cache_dir)
    print("Syncing card descriptions from YGOPRODeck API (local cache only)...")
    count = mgr.sync_descriptions(cards_db)
    print(f"Cached {count} card descriptions to {os.path.join(mgr.cache_dir, 'card_descriptions.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
