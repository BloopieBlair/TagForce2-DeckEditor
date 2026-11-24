"""Pure-stdlib save file engine for Yu-Gi-Oh! GX: Tag Force 2 (PSP / PPSSPP).

Handles decrypted DATA0 save discovery, structural deck-block detection,
inventory ownership diffing, safe in-memory binary patching, atomic writes,
and immutable + rotating timestamped backups — with zero external dependencies
and zero runtime dependency on extracted Konami binary files.
"""

from collections import Counter
from datetime import datetime
import glob
import json
import os
import re
import shutil
import struct
import tempfile
from typing import Any, Dict, List, Optional, Tuple

DECK_BLOCK_SIZE = 326          # 0x146 bytes
DECK_NAME_BYTES = 64           # 0x40 bytes UTF-16LE null-terminated
DECK_NAME_MAX_CONTENT = 60     # Leave at least 4 bytes for UTF-16LE null terminator
INVENTORY_OFFSET = 0x13F11     # 4 bytes per card: [main, trunk, side, extra]
DEFAULT_DECK_OFFSET = 0x5880
MAX_MAIN = 80
MAX_SIDE = 15
MAX_EXTRA = 30
ID13_MASK = 0x1FFF
NUM_CARDS = 2926
MIN_SAVE_SIZE = INVENTORY_OFFSET + NUM_CARDS * 4  # 0x16CE9 (93,417 bytes)

ENCRYPTED_HEADERS = (b"\x51\x66\x4e\x4f", b"~PSP")

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(_SCRIPT_DIR, "cards_db.json")
DEFAULT_SAMPLE_DECK_PATH = os.path.join(_SCRIPT_DIR, "sample_deck.json")

_TIMESTAMP_BAK_RE = re.compile(r"^\.(?P<ts>\d{8}_\d{6}(?:_\d{2})?)\.bak$")


class TagForceSaveError(Exception):
    """Base exception for Tag Force 2 save operations."""


class EncryptedSaveError(TagForceSaveError):
    """Raised when DATA0 is still encrypted by PSP/PPSSPP."""


class InvalidSaveError(TagForceSaveError):
    """Raised when DATA0 is truncated, malformed, or lacks a valid deck block."""


class DeckValidationError(TagForceSaveError):
    """Raised when a deck payload violates Tag Force 2 limits or card rules."""


def load_card_db(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Loads cards_db.json (2,926 records indexed 0..2925)."""
    path = db_path or DEFAULT_DB_PATH
    if not os.path.exists(path):
        raise FileNotFoundError(f"Card database not found at {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list) or len(data) != NUM_CARDS:
        raise ValueError(
            f"Expected {NUM_CARDS} card entries in {path}, got {len(data) if isinstance(data, list) else type(data).__name__}"
        )
    return data


def build_id_maps(cards_db: List[Dict[str, Any]]) -> Tuple[Dict[int, int], Dict[int, int]]:
    """Builds bidirectional (id13 -> game_index, game_index -> id13) maps from cards_db.json."""
    id13_to_game: Dict[int, int] = {0: 0}
    game_to_id13: Dict[int, int] = {}
    for card in cards_db:
        gidx = card.get("game_index")
        iid = card.get("internal_id")
        if gidx is None or iid is None:
            continue
        id13 = int(iid) & ID13_MASK
        game_to_id13[int(gidx)] = id13
        if id13 != 0:
            id13_to_game[id13] = int(gidx)
    return id13_to_game, game_to_id13


def is_fusion_card(card: Dict[str, Any]) -> bool:
    """Returns True if the card belongs in the Fusion/Extra Deck."""
    frame = (card.get("frame_type") or "").lower()
    ctype = (card.get("type") or "").lower()
    return frame == "fusion" or "fusion" in ctype


def detect_region(save_path: Optional[str]) -> Optional[str]:
    """Detects game region label from save file path."""
    if not save_path:
        return None
    upper = save_path.upper()
    if "ULES00925" in upper:
        return "EU (ULES00925)"
    if "ULUS10287" in upper:
        return "US (ULUS10287)"
    return "Custom"


def _resolve_candidate_save(candidate: Optional[str]) -> Optional[str]:
    """Resolves a file path or directory (including a SAVEDATA root) to a DATA0 file."""
    if not candidate:
        return None
    expanded = os.path.abspath(os.path.expanduser(candidate))
    if os.path.isfile(expanded):
        return expanded
    if os.path.isdir(expanded):
        direct = os.path.join(expanded, "DATA0")
        if os.path.isfile(direct):
            return direct
        for pattern in ("ULES00925*", "ULUS10287*"):
            for slot_dir in sorted(glob.glob(os.path.join(expanded, pattern))):
                slot_file = os.path.join(slot_dir, "DATA0")
                if os.path.isfile(slot_file):
                    return slot_file
    return None


def find_save_path(explicit_path: Optional[str] = None, search_root: Optional[str] = None) -> Optional[str]:
    """Cross-platform discovery for decrypted Tag Force 2 DATA0 saves.

    Priority:
      1. explicit_path argument
      2. TAGFORCE_SAVE_PATH environment variable
      3. PPSSPP_SAVEDATA environment variable
      4. Standard Windows / Linux / macOS PPSSPP SAVEDATA folders (EU ULES00925* & US ULUS10287*)
      5. Local ./DATA0 fallback
    """
    for direct in (
        explicit_path,
        os.environ.get("TAGFORCE_SAVE_PATH"),
        os.environ.get("PPSSPP_SAVEDATA"),
    ):
        found = _resolve_candidate_save(direct)
        if found:
            return found

    home = os.path.expanduser("~")
    savedata_roots = [
        os.path.join(home, "Documents", "PPSSPP", "PSP", "SAVEDATA"),
        os.path.join(home, "AppData", "Roaming", "PPSSPP", "PSP", "SAVEDATA"),
        os.path.join(home, ".config", "ppsspp", "PSP", "SAVEDATA"),
        os.path.join(home, "Library", "Application Support", "PPSSPP", "PSP", "SAVEDATA"),
    ]
    for root in savedata_roots:
        found = _resolve_candidate_save(root)
        if found:
            return found

    local_dir = search_root or _SCRIPT_DIR
    local_data0 = os.path.join(local_dir, "DATA0")
    if os.path.isfile(local_data0):
        return local_data0

    return None


def is_encrypted_save(data: bytes) -> bool:
    """Checks whether raw DATA0 bytes begin with a PSP encrypted header."""
    return len(data) >= 4 and bytes(data[:4]) in ENCRYPTED_HEADERS


def validate_save_bytes(data: bytes) -> None:
    """Validates that raw DATA0 bytes are decrypted and large enough for deck + inventory blocks."""
    if not isinstance(data, (bytes, bytearray)) or len(data) < 4:
        raise InvalidSaveError("Save file is empty or unreadable.")
    if is_encrypted_save(data):
        raise EncryptedSaveError(
            "Save file is encrypted. Disable 'Encrypt Save' in PPSSPP Settings -> System "
            "and re-save from an in-game menu first."
        )
    if len(data) < MIN_SAVE_SIZE:
        raise InvalidSaveError(
            f"Save file appears truncated ({len(data)} bytes; expected at least {MIN_SAVE_SIZE} bytes)."
        )


def decode_deck_name(name_bytes: bytes) -> Optional[str]:
    """Decodes a 64-byte character-aligned null-terminated UTF-16LE deck name."""
    if len(name_bytes) < DECK_NAME_BYTES:
        return None
    null_idx = DECK_NAME_BYTES
    for idx in range(0, DECK_NAME_BYTES, 2):
        if name_bytes[idx] == 0 and name_bytes[idx + 1] == 0:
            null_idx = idx
            break
    try:
        text = name_bytes[:null_idx].decode("utf-16-le", errors="strict")
    except UnicodeDecodeError:
        return None
    return text


def encode_deck_name(name: str) -> bytes:
    """Encodes a deck name to 64-byte null-padded UTF-16LE without splitting surrogate pairs."""
    cleaned = name.strip()
    out_chars: List[str] = []
    byte_len = 0
    for ch in cleaned:
        encoded_ch = ch.encode("utf-16-le")
        if byte_len + len(encoded_ch) > DECK_NAME_MAX_CONTENT:
            break
        out_chars.append(ch)
        byte_len += len(encoded_ch)
    encoded = "".join(out_chars).encode("utf-16-le")
    return encoded.ljust(DECK_NAME_BYTES, b"\x00")


def _is_printable_deck_name(name: Optional[str]) -> bool:
    if not name or len(name) > 31:
        return False
    return all(ord(ch) >= 0x20 and ch.isprintable() for ch in name)


def _is_valid_deck_block(
    data: bytes,
    offset: int,
    id13_to_game: Dict[int, int],
    *,
    require_zero_tail: bool = True,
    require_nonempty_deck: bool = False,
) -> bool:
    """Structurally validates a 326-byte Tag Force 2 deck block at `offset`."""
    if offset < 0 or offset + DECK_BLOCK_SIZE > len(data):
        return False

    deck_name = decode_deck_name(data[offset : offset + DECK_NAME_BYTES])
    if not _is_printable_deck_name(deck_name):
        return False

    main_count, side_count, extra_count = struct.unpack_from("<III", data, offset + 0x40)
    if main_count > MAX_MAIN or side_count > MAX_SIDE or extra_count > MAX_EXTRA:
        return False
    if require_nonempty_deck and (main_count + side_count + extra_count) == 0:
        return False

    sections = (
        (offset + 0x4C, main_count, MAX_MAIN),
        (offset + 0xEC, side_count, MAX_SIDE),
        (offset + 0x10A, extra_count, MAX_EXTRA),
    )
    for sec_start, count, capacity in sections:
        for i in range(count):
            (val,) = struct.unpack_from("<H", data, sec_start + i * 2)
            id13 = val & ID13_MASK
            gidx = id13_to_game.get(id13)
            if not gidx:
                return False
        if require_zero_tail:
            for i in range(count, capacity):
                (val,) = struct.unpack_from("<H", data, sec_start + i * 2)
                if val != 0:
                    return False

    return True


def find_deck_offset(data: bytes, id13_to_game: Dict[int, int]) -> int:
    """Locates the active deck block structurally (works even after renaming the deck)."""
    # 1. Primary: structurally validate standard offset 0x5880
    if _is_valid_deck_block(data, DEFAULT_DECK_OFFSET, id13_to_game, require_zero_tail=True):
        return DEFAULT_DECK_OFFSET

    # 2. Secondary: search for default UTF-16LE string "Starting Deck"
    target = "Starting Deck".encode("utf-16-le")
    pos = 0
    while True:
        idx = data.find(target, pos)
        if idx == -1:
            break
        if _is_valid_deck_block(data, idx, id13_to_game, require_zero_tail=True):
            return idx
        pos = idx + 2

    # 3. Tertiary: scan 4-byte aligned candidate offsets before inventory block
    scan_limit = min(len(data) - DECK_BLOCK_SIZE, INVENTORY_OFFSET)
    for off in range(0, scan_limit + 1, 4):
        if off == DEFAULT_DECK_OFFSET:
            continue
        # Fast pre-filter on counts before full check
        m, s, e = struct.unpack_from("<III", data, off + 0x40)
        if 1 <= m <= MAX_MAIN and s <= MAX_SIDE and e <= MAX_EXTRA:
            if _is_valid_deck_block(
                data,
                off,
                id13_to_game,
                require_zero_tail=True,
                require_nonempty_deck=True,
            ):
                return off

    # 4. Relaxed fallback at DEFAULT_DECK_OFFSET (in case game left stale bytes in unused tail)
    if _is_valid_deck_block(data, DEFAULT_DECK_OFFSET, id13_to_game, require_zero_tail=False):
        return DEFAULT_DECK_OFFSET

    raise InvalidSaveError("Could not locate a valid active deck block in DATA0 save file.")


def read_deck_bytes(data: bytes, cards_db: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Parses active deck from raw decrypted DATA0 bytes into game_index lists."""
    validate_save_bytes(data)
    id13_to_game, _ = build_id_maps(cards_db)
    deck_offset = find_deck_offset(data, id13_to_game)

    deck_name = decode_deck_name(data[deck_offset : deck_offset + DECK_NAME_BYTES]) or "Starting Deck"
    main_count, side_count, extra_count = struct.unpack_from("<III", data, deck_offset + 0x40)

    def _read_slots(start: int, count: int) -> List[int]:
        out: List[int] = []
        for i in range(count):
            (val,) = struct.unpack_from("<H", data, start + i * 2)
            id13 = val & ID13_MASK
            gidx = id13_to_game.get(id13)
            if gidx is not None and 0 < gidx < len(cards_db):
                out.append(gidx)
        return out

    return {
        "name": deck_name,
        "main": _read_slots(deck_offset + 0x4C, main_count),
        "side": _read_slots(deck_offset + 0xEC, side_count),
        "extra": _read_slots(deck_offset + 0x10A, extra_count),
        "deck_offset": deck_offset,
    }


def validate_deck_payload(payload: Any, cards_db: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Validates a deck payload against Tag Force 2 limits and card rules."""
    if not isinstance(payload, dict):
        raise DeckValidationError("Deck payload must be a JSON object.")

    raw_name = payload.get("name", "")
    if not isinstance(raw_name, str) or not raw_name.strip():
        raise DeckValidationError("Deck name must be a non-empty string.")
    deck_name = raw_name.strip()

    main_list = payload.get("main", [])
    side_list = payload.get("side", [])
    extra_list = payload.get("extra", [])

    for section_name, section in (("main", main_list), ("side", side_list), ("extra", extra_list)):
        if not isinstance(section, list):
            raise DeckValidationError(f"'{section_name}' must be a list of card game_index integers.")

    if len(main_list) > MAX_MAIN:
        raise DeckValidationError(f"Main Deck cannot exceed {MAX_MAIN} cards (got {len(main_list)}).")
    if len(side_list) > MAX_SIDE:
        raise DeckValidationError(f"Side Deck cannot exceed {MAX_SIDE} cards (got {len(side_list)}).")
    if len(extra_list) > MAX_EXTRA:
        raise DeckValidationError(f"Extra/Fusion Deck cannot exceed {MAX_EXTRA} cards (got {len(extra_list)}).")

    name_counts: Counter = Counter()

    def _validate_section(items: List[Any], section_name: str, allow_fusion_only: bool = False) -> List[int]:
        validated: List[int] = []
        for idx_pos, item in enumerate(items):
            if isinstance(item, bool) or not isinstance(item, int):
                raise DeckValidationError(
                    f"Invalid card index in {section_name}[{idx_pos}]: expected int, got {type(item).__name__}."
                )
            if item < 1 or item >= len(cards_db):
                raise DeckValidationError(
                    f"Card game_index {item} in {section_name}[{idx_pos}] is out of valid range (1..{len(cards_db) - 2})."
                )
            card = cards_db[item]
            card_name = card.get("name")
            if not card_name:
                raise DeckValidationError(f"Card game_index {item} is an empty sentinel slot.")

            fusion = is_fusion_card(card)
            if allow_fusion_only and not fusion:
                raise DeckValidationError(
                    f"Only Fusion Monsters can be placed in the Extra Deck ('{card_name}' is '{card.get('type')}')."
                )
            if not allow_fusion_only and fusion:
                raise DeckValidationError(
                    f"Fusion Monster '{card_name}' must be placed in the Extra Deck, not {section_name.title()} Deck."
                )

            name_counts[card_name] += 1
            if name_counts[card_name] > 3:
                raise DeckValidationError(
                    f"Card '{card_name}' exceeds the maximum of 3 copies across Main, Side, and Extra Decks."
                )
            validated.append(item)
        return validated

    clean_main = _validate_section(main_list, "main", allow_fusion_only=False)
    clean_side = _validate_section(side_list, "side", allow_fusion_only=False)
    clean_extra = _validate_section(extra_list, "extra", allow_fusion_only=True)

    return {
        "name": deck_name,
        "main": clean_main,
        "side": clean_side,
        "extra": clean_extra,
    }


def patch_save_bytes(
    data: bytes,
    deck_payload: Dict[str, Any],
    cards_db: List[Dict[str, Any]],
    *,
    auto_unlock: bool = True,
) -> bytes:
    """Patches deck block and inventory ownership diff purely in memory and returns new DATA0 bytes."""
    validate_save_bytes(data)
    clean_deck = validate_deck_payload(deck_payload, cards_db)
    _, game_to_id13 = build_id_maps(cards_db)

    old_deck = read_deck_bytes(data, cards_db)
    deck_offset = old_deck["deck_offset"]

    buf = bytearray(data)

    # 1. Diff inventory records at INVENTORY_OFFSET (4 bytes/card: [main, trunk, side, extra])
    old_gidxs = set(old_deck["main"]) | set(old_deck["side"]) | set(old_deck["extra"])
    new_main_counts = Counter(clean_deck["main"])
    new_side_counts = Counter(clean_deck["side"])
    new_extra_counts = Counter(clean_deck["extra"])
    affected_gidxs = old_gidxs | set(new_main_counts) | set(new_side_counts) | set(new_extra_counts)

    for gidx in affected_gidxs:
        if gidx < 1 or gidx >= NUM_CARDS:
            continue
        off = INVENTORY_OFFSET + gidx * 4
        existing_m, existing_trunk, existing_s, existing_e = buf[off : off + 4]
        existing_total = existing_m + existing_trunk + existing_s + existing_e

        m = new_main_counts.get(gidx, 0)
        s = new_side_counts.get(gidx, 0)
        e = new_extra_counts.get(gidx, 0)
        new_slotted = m + s + e

        if auto_unlock:
            trunk = max(existing_trunk, max(0, 3 - new_slotted))
        else:
            trunk = max(0, existing_total - new_slotted)

        buf[off] = min(255, m)
        buf[off + 1] = min(255, trunk)
        buf[off + 2] = min(255, s)
        buf[off + 3] = min(255, e)

    # 2. Encode deck block (326 bytes)
    name_bytes = encode_deck_name(clean_deck["name"])
    counts_bytes = struct.pack(
        "<III",
        len(clean_deck["main"]),
        len(clean_deck["side"]),
        len(clean_deck["extra"]),
    )

    def _pack_slots(gidxs: List[int], capacity: int) -> bytes:
        block = bytearray(capacity * 2)
        for i, gidx in enumerate(gidxs):
            id13 = game_to_id13.get(gidx, 0) & ID13_MASK
            struct.pack_into("<H", block, i * 2, id13)
        return bytes(block)

    deck_block = (
        name_bytes
        + counts_bytes
        + _pack_slots(clean_deck["main"], MAX_MAIN)
        + _pack_slots(clean_deck["side"], MAX_SIDE)
        + _pack_slots(clean_deck["extra"], MAX_EXTRA)
    )
    assert len(deck_block) == DECK_BLOCK_SIZE
    buf[deck_offset : deck_offset + DECK_BLOCK_SIZE] = deck_block

    return bytes(buf)


def _atomic_write_bytes(target_path: str, payload: bytes) -> None:
    """Atomically writes bytes to `target_path` via temp file + os.replace()."""
    parent = os.path.dirname(os.path.abspath(target_path))
    os.makedirs(parent, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp_", dir=parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target_path)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


def list_backups(save_path: Optional[str]) -> List[str]:
    """Lists valid backup basenames for `save_path` (newest timestamped first, then .original.bak)."""
    if not save_path:
        return []
    abs_save = os.path.abspath(save_path)
    parent = os.path.dirname(abs_save)
    base = os.path.basename(abs_save)
    if not os.path.isdir(parent):
        return []

    original_name = f"{base}.original.bak"
    timestamped: List[str] = []
    has_original = False

    for entry in os.listdir(parent):
        if not entry.startswith(base + "."):
            continue
        if entry == original_name and os.path.isfile(os.path.join(parent, entry)):
            has_original = True
            continue
        suffix = entry[len(base) :]
        if _TIMESTAMP_BAK_RE.match(suffix) and os.path.isfile(os.path.join(parent, entry)):
            timestamped.append(entry)

    timestamped.sort(reverse=True)
    if has_original:
        timestamped.append(original_name)
    return timestamped


def create_backup(save_path: str, max_rotating: int = 10) -> str:
    """Creates immutable .original.bak on first save + rotating timestamped backup."""
    abs_save = os.path.abspath(save_path)
    parent = os.path.dirname(abs_save)
    base = os.path.basename(abs_save)

    original_path = os.path.join(parent, f"{base}.original.bak")
    if not os.path.exists(original_path):
        shutil.copy2(abs_save, original_path)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"{base}.{stamp}.bak"
    backup_path = os.path.join(parent, backup_name)
    seq = 1
    while os.path.exists(backup_path):
        backup_name = f"{base}.{stamp}_{seq:02d}.bak"
        backup_path = os.path.join(parent, backup_name)
        seq += 1

    shutil.copy2(abs_save, backup_path)

    # Prune oldest timestamped backups beyond max_rotating (never prune .original.bak)
    timestamped = [b for b in list_backups(abs_save) if b != f"{base}.original.bak"]
    for stale in timestamped[max_rotating:]:
        try:
            os.remove(os.path.join(parent, stale))
        except OSError:
            pass

    return backup_name


def save_deck_to_path(
    save_path: str,
    deck_payload: Dict[str, Any],
    cards_db: List[Dict[str, Any]],
    *,
    auto_unlock: bool = True,
    max_rotating_backups: int = 10,
) -> Dict[str, Any]:
    """Validates, patches in memory, creates backups, and atomically writes DATA0."""
    if not os.path.isfile(save_path):
        raise FileNotFoundError(f"Save file not found at {save_path}")

    with open(save_path, "rb") as f:
        raw_bytes = f.read()

    # Validate & patch entirely in memory before touching disk or creating backups
    patched_bytes = patch_save_bytes(raw_bytes, deck_payload, cards_db, auto_unlock=auto_unlock)
    backup_name = create_backup(save_path, max_rotating=max_rotating_backups)
    _atomic_write_bytes(save_path, patched_bytes)

    updated_deck = read_deck_bytes(patched_bytes, cards_db)
    return {
        "deck": updated_deck,
        "backup": backup_name,
        "backups": list_backups(save_path),
    }


def restore_backup(
    save_path: str,
    backup_name: str,
    cards_db: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Atomically restores a validated backup belonging to `save_path`."""
    if not save_path or not os.path.isdir(os.path.dirname(os.path.abspath(save_path))):
        raise FileNotFoundError("No active save file path to restore.")
    if not isinstance(backup_name, str) or not backup_name or os.path.basename(backup_name) != backup_name:
        raise ValueError("Invalid backup filename.")

    available = list_backups(save_path)
    if backup_name not in available:
        raise ValueError(f"Backup '{backup_name}' not found for active save file.")

    parent = os.path.dirname(os.path.abspath(save_path))
    backup_path = os.path.join(parent, backup_name)
    with open(backup_path, "rb") as f:
        backup_bytes = f.read()

    validate_save_bytes(backup_bytes)
    _atomic_write_bytes(save_path, backup_bytes)

    result: Dict[str, Any] = {
        "restored": backup_name,
        "backups": list_backups(save_path),
    }
    if cards_db is not None:
        result["deck"] = read_deck_bytes(backup_bytes, cards_db)
    return result


def load_sample_deck(sample_path: Optional[str] = None) -> Dict[str, Any]:
    """Loads sample_deck.json for Demo Mode."""
    path = sample_path or DEFAULT_SAMPLE_DECK_PATH
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {
        "name": data.get("name", "Demo Deck"),
        "main": list(data.get("main", [])),
        "side": list(data.get("side", [])),
        "extra": list(data.get("extra", [])),
    }
