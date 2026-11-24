# 📖 Technical Architecture & Save Format Explainer: Yu-Gi-Oh! GX Tag Force 2 Deck Editor

A technical guide to the architecture, PSP `DATA0` memory layouts, card ID mapping, safe inventory patching, opt-in local caching, and frontend design used in **Duelist Hub** for *Yu-Gi-Oh! GX: Tag Force 2* (PSP / PPSSPP).

> **Clean-Room Note:** This repository contains **zero** proprietary game binaries, archives, or copyrighted artwork. Runtime ID resolution reads exclusively from the factual metadata in `cards_db.json`; the binary table formats described in Section 3 are clean-room structural reference notes documenting how Tag Force 2 stores card records.

---

## Table of Contents
1. [System Overview & High-Level Architecture](#1-system-overview--high-level-architecture)
2. [PSP Save File Architecture (`DATA0`)](#2-psp-save-file-architecture-data0)
   - [Encryption vs. Decryption Detection](#encryption-vs-decryption-detection)
   - [Active Deck Memory Block (`0x5880`)](#active-deck-memory-block-0x5880)
   - [Structural Offset Detection (Renamed-Deck Safe)](#structural-offset-detection-renamed-deck-safe)
   - [Inventory Ownership Block (`0x13F11`)](#inventory-ownership-block-0x13f11)
3. [Card ID Architecture & Structural Reference Notes](#3-card-id-architecture--structural-reference-notes)
   - [Dual-ID System: `game_index` vs. 13-Bit `id13`](#dual-id-system-game_index-vs-13-bit-id13)
   - [Runtime Mapping via `cards_db.json`](#runtime-mapping-via-cards_dbjson)
   - [Reference: Tag Force 2 Card Table Layouts](#reference-tag-force-2-card-table-layouts)
4. [Backend Engine & HTTP API (`tagforce_save.py`, `card_cache.py`, `run_showcase.py`)](#4-backend-engine--http-api)
   - [Cross-Platform EU/US Save Discovery](#cross-platform-euus-save-discovery)
   - [Safe Inventory Diffing & Atomic Backups](#safe-inventory-diffing--atomic-backups)
   - [Security & Static File Allowlist](#security--static-file-allowlist)
   - [Opt-In Local Artwork & Text Cache (`card_cache.py`)](#opt-in-local-artwork--text-cache-card_cachepy)
5. [Frontend Architecture (`index.html`, `index.css`, `app.js`)](#5-frontend-architecture)
   - [Procedural SVG/CSS Card Frame Pipeline](#procedural-svgcss-card-frame-pipeline)
   - [State Management, Undo/Redo & Demo Mode Fallback](#state-management-undoredo--demo-mode-fallback)
6. [End-to-End Save & Sync Data Flow](#6-end-to-end-save--sync-data-flow)

---

## 1. System Overview & High-Level Architecture

Duelist Hub runs with **zero external `pip` or `npm` dependencies** across three layers:

```text
+-----------------------------------------------------------------------------------+
|                                  USER LAYER                                       |
|  Browser UI (Vanilla ES6, Procedural SVG/CSS Card Frames, Demo Mode + Analytics)  |
+----------------------------------------+------------------------------------------+
                                         | Same-Origin HTTP / JSON REST API
+----------------------------------------v------------------------------------------+
|                              BACKEND SERVER LAYER                                 |
|  run_showcase.py  : ThreadingHTTPServer, strict static allowlist, REST endpoints  |
|  tagforce_save.py : Pure stdlib DATA0 parser, validator, diff-patcher & backups   |
|  card_cache.py    : Opt-in rate-limited local disk cache & TAGFORCE_ART_DIR       |
|  extract_deck.py  : Thin CLI wrapper to export DATA0 decks to JSON / Markdown     |
+----------------------------------------+------------------------------------------+
                                         | Atomic File I/O & Local Disk Cache
+----------------------------------------v------------------------------------------+
|                                DATA & STORAGE LAYER                               |
|  - cards_db.json   : 2,926 factual card entries (IDs, passcodes, stats, types)    |
|  - sample_deck.json: Bundled Demo Mode deck (Cyber-Dragon Demo Deck)              |
|  - DATA0           : User's decrypted PPSSPP save (local or browser-uploaded)     |
|  - cache/          : .gitignored optional local art/text cache & uploaded saves   |
+-----------------------------------------------------------------------------------+
```

---

## 2. PSP Save File Architecture (`DATA0`)

### Encryption vs. Decryption Detection

Standard PSP saves are encrypted with Sony's Kirk hardware engine and begin with `~PSP` or `QfNO` (`0x51 0x66 0x4E 0x4F`). When **Encrypt Save** is disabled in PPSSPP, the emulator writes raw unencrypted game save structures directly to `DATA0`.

`tagforce_save.py` inspects the leading header bytes before parsing:
- Rejects encrypted saves with `EncryptedSaveError` (surfacing a warning banner in the UI while keeping Demo Mode usable).
- Rejects truncated or malformed files with `InvalidSaveError`.

---

### Active Deck Memory Block (`0x5880`)

The active deck record occupies **326 bytes** (`0x146`):

```text
+-------------------+--------------------------------------------------------------------+
| Relative Offset   | Field Description                                                  |
+-------------------+--------------------------------------------------------------------+
| 0x000 - 0x03F     | Deck Name (64 bytes, UTF-16LE, null-terminated; max 60 bytes text) |
| 0x040 - 0x043     | Main Deck Card Count  (uint32 LE, max: 80)                         |
| 0x044 - 0x047     | Side Deck Card Count  (uint32 LE, max: 15)                         |
| 0x048 - 0x04B     | Extra Deck Card Count (uint32 LE, max: 30)                         |
| 0x04C - 0x0EB     | Main Deck Card Slots  (80 × uint16 LE = 160 bytes)                 |
| 0x0EC - 0x109     | Side Deck Card Slots  (15 × uint16 LE =  30 bytes)                 |
| 0x10A - 0x145     | Extra Deck Card Slots (30 × uint16 LE =  60 bytes)                 |
+-------------------+--------------------------------------------------------------------+
```

Each 16-bit card slot stores the lower **13 bits** of the card's internal engine ID (`internal_id & 0x1FFF`). Unused trailing slots are zero-padded (`0x0000`).

---

### Structural Offset Detection (Renamed-Deck Safe)

Early versions searched strictly for the UTF-16LE string `"Starting Deck"`, which failed once a player renamed their deck. `tagforce_save.py` resolves the deck offset reliably via `find_deck_offset(data, id_map)`:

1. Validates `DEFAULT_DECK_OFFSET` (`0x5880`) structurally:
   - `main <= 80`, `side <= 15`, `extra <= 30`
   - Decodable UTF-16LE name header
   - Active slots map to valid known card IDs in `id_map`, and unused trailing slots are `0x0000`.
2. If `0x5880` does not match (e.g., different save variant), falls back to searching for `"Starting Deck"` in UTF-16LE and scanning 4-byte aligned candidate headers with the same structural validator.

When writing back a deck name, `tagforce_save.py` truncates by Unicode character boundaries until `len(encoded_utf16le) <= 60`, then pads with `\x00` to 64 bytes—preventing broken UTF-16 surrogate pairs.

---

### Inventory Ownership Block (`0x13F11`)

Tag Force 2 tracks card ownership separately from deck slots. If a card is slotted into a deck without matching inventory counts, the game strips it on load.

- **Base Offset:** `0x13F11`
- **Entries:** `2,926` cards × `4` bytes = `11,704` bytes (ending at `0x16CE9`)

```text
Card Inventory Record Offset = 0x13F11 + (game_index * 4)

+--------+------------------+--------------------------------------------------------+
| Byte   | Field Name       | Description                                            |
+--------+------------------+--------------------------------------------------------+
| Byte 0 | Main Deck Qty    | Copies currently slotted in Main Deck                  |
| Byte 1 | Trunk Qty        | Undeployed copies stored in Trunk                      |
| Byte 2 | Side Deck Qty    | Copies currently slotted in Side Deck                  |
| Byte 3 | Extra Deck Qty   | Copies currently slotted in Extra / Fusion Deck        |
+--------+------------------+--------------------------------------------------------+
```

---

## 3. Card ID Architecture & Structural Reference Notes

### Dual-ID System: `game_index` vs. 13-Bit `id13`

Tag Force 2 uses two card identifiers:

1. **`game_index` (`0 .. 2925`):** Sequential zero-based index used by the inventory table (`0x13F11 + game_index * 4`), text tables, and `cards_db.json` (indices `0` and `2925` are empty sentinel slots; `1 .. 2924` are the 2,924 playable/anime cards).
2. **`internal_id` (16-bit) & `id13` (13-bit mask):** Save deck slots store the 13-bit engine ID `id13 = internal_id & 0x1FFF` (`ID13_MASK = 0x1FFF`).

---

### Runtime Mapping via `cards_db.json`

Duelist Hub has **zero runtime dependency on any Konami binary file**. `tagforce_save.py` builds bidirectional lookup tables (`id13 -> game_index` and `game_index -> id13`) directly from `cards_db.json`:

- Every entry in `cards_db.json` contains purely factual interoperability fields: `game_index`, `internal_id`, `passcode`, `name`, `type`, `frame_type`, `atk`, `def`, `level`, `race`, `attribute`, and `is_anime`.
- Sentinel empty slots (`0` and `2925`, both with `id13 == 0`) are skipped during normal card lookup and search.

---

### Reference: Tag Force 2 Card Table Layouts

For developers researching Tag Force 2 save/data interoperability (clean-room structural notes only—no game files are bundled):

- **Property Table (`CARD_Prop.bin`, 2,926 × 8-byte records):**
  - Bytes `0..1`: `uint16_le` `internal_id` (low 13 bits = `id13`; upper 3 bits carry the lowest 3 bits of the packed ATK field).
  - Bytes `2..3`: packed 9-bit ATK & 9-bit DEF fields:
    $$\text{full\_24} = (\text{internal\_id} \gg 13) \mid (b_2 \ll 3) \mid (b_3 \ll 11)$$
    $$\text{ATK} = (\text{full\_24} \ \& \ \text{0x1FF}) \times 10, \quad \text{DEF} = ((\text{full\_24} \gg 9) \ \& \ \text{0x1FF}) \times 10$$
    *(Cards with `?` ATK/DEF are represented as `-1` in `cards_db.json` and rendered as `?` in the UI.)*
  - Byte `4`: upper nibble = Attribute/Category (`0x1` LIGHT through `0x7` DIVINE, `0x8` Spell, `0x9` Trap); lower nibble = Spell/Trap icon subtype.
  - Byte `5`: low nibble = Monster Level (`1..12`); high nibble = Frame subtype (Normal, Effect, Ritual, Fusion, Token).
  - Byte `6`: Monster Race / Type ID.
- **Passcode Table (`CARD_Pass.bin`):** `uint32_le` array indexed by `game_index` storing 8-digit card passcodes (`00000000` for anime-exclusive/token entries).
- **Genre / Sort / String Tables:** `CARD_Genre.bin` (48-bit deck-filter bitmasks), `CARD_Sort_E.bin` (`uint16_le` alphabetical indices), `CARD_Indx_E.bin` (`(name_offset, desc_offset)` pairs), `CARD_Name_E.bin` (UTF-16LE names), and a Huffman + dictionary token compression pipeline (`CARD_Huff_E.bin` + `DICT_E.bin` + `CARD_Desc_E.bin`) for in-game descriptions.

---

## 4. Backend Engine & HTTP API

### Cross-Platform EU/US Save Discovery

`tagforce_save.find_save_path(explicit_path=None)` checks locations in priority order:

1. Explicit CLI `--save` argument
2. `TAGFORCE_SAVE_PATH` environment variable
3. `PPSSPP_SAVEDATA` directory (scanning EU `ULES00925*` and US `ULUS10287*` slots)
4. OS-standard PPSSPP paths:
   - Windows: `%USERPROFILE%\Documents\PPSSPP\PSP\SAVEDATA` & `%APPDATA%\PPSSPP\PSP\SAVEDATA`
   - Linux: `~/.config/ppsspp/PSP/SAVEDATA`
   - macOS: `~/Library/Application Support/PPSSPP/PSP/SAVEDATA`
5. Local `./DATA0` fallback

If no valid decrypted save is found (or `--demo` is passed), `run_showcase.py` boots cleanly in **Demo Mode** backed by `sample_deck.json`.

---

### Safe Inventory Diffing & Atomic Backups

`patch_save_bytes(data, deck_payload, cards_db, auto_unlock=True)` operates purely in memory:

1. Validates the incoming payload via `validate_deck_payload()` (valid `game_index` range `1..2924`, deck limits `80/15/30`, max 3 copies per card name across Main + Side + Extra, Fusion monsters only in Extra Deck).
2. Reads the existing deck from `data` to compute previous counts per `game_index`.
3. Iterates over the **union of old and new `game_index`es** so removed cards have their `main`/`side`/`extra` counts properly reset instead of leaving stale equipped counts behind:
   - **`auto_unlock=True`:** `trunk = max(existing_trunk, max(0, 3 - m - s - e))` — ensures at least 3 total copies without ever downgrading players who legitimately own > 3 trunk copies.
   - **`auto_unlock=False`:** `trunk = max(0, existing_total - (m + s + e))` — strictly preserves total card ownership.
4. Patches the 326-byte deck block and returns the updated `bytes`.

When writing to disk, `save_deck_to_path()`:
- Preserves an immutable `DATA0.original.bak` on first write (never overwritten).
- Creates a timestamped backup `DATA0.YYYYMMDD_HHMMSS.bak` and retains the 10 most recent timestamped snapshots.
- Writes to a temporary file in the same directory and atomically swaps it via `os.replace()`.
- `restore_backup()` strictly validates the backup basename against `list_backups()` (preventing path traversal) before performing an atomic restore.

---

### Security & Static File Allowlist

`run_showcase.py` uses `ThreadingHTTPServer`, binds to `127.0.0.1` by default, and enforces:
- **Strict static allowlist:** Only `/`, `/index.html`, `/index.css`, `/app.js`, `/cards_db.json`, `/sample_deck.json`, and `/favicon.ico` are served. Requests for `.git`, `*.py`, `DATA0`, `*.bak`, `tests/`, or parent traversal are rejected (`403`/`404`).
- **No wildcard CORS** (`Access-Control-Allow-Origin: *` removed), `Cache-Control: no-store` on all `/api/*` endpoints, and request body size caps (1 MB JSON / 2 MB save upload).

| Endpoint | Method | Purpose |
| :--- | :--- | :--- |
| `/api/status` | `GET` | Server mode (`save`/`demo`), save path, region, encryption status, backups, cache settings |
| `/api/deck` | `GET` | Active deck payload (`{mode, name, main, side, extra}`) |
| `/api/save_deck` | `POST` | Validate and save deck (patches `DATA0` in save mode or updates demo session) |
| `/api/upload_save` | `POST` | Upload & validate raw `DATA0` bytes into `cache/uploaded_DATA0` |
| `/api/download_save` | `GET` | Download current patched `DATA0` |
| `/api/restore_backup` | `POST` | Atomically restore a validated backup snapshot |
| `/api/settings` | `GET`/`POST` | Read or toggle `art_cache_enabled` |
| `/api/card_image/<passcode>` | `GET` | Serve cached or `TAGFORCE_ART_DIR` image (`?size=small\|full`) |
| `/api/card_descriptions` | `GET` | Serve locally synced `cache/card_descriptions.json` (or `{}`) |
| `/api/sync_descriptions` | `POST` | Opt-in local fetch of TCG card descriptions from YGOPRODeck API |

---

### Opt-In Local Artwork & Text Cache (`card_cache.py`)

YGOPRODeck's API terms strictly forbid hotlinking `images.ygoprodeck.com` and enforce a 20 req/s rate limit. `card_cache.py` enforces full compliance:

1. **Resolution Order for `GET /api/card_image/<passcode>?size=small|full`:**
   - Validates digits-only non-zero passcode.
   - Checks user-supplied `TAGFORCE_ART_DIR` first (`<passcode>.jpg/.png` or unpadded integer filename).
   - Checks `.gitignore`d local disk cache (`cache/cards_small/` or `cache/cards/`).
   - Only if the user explicitly enabled `art_cache_enabled` (and passcode is not recorded in `cache/missing_art.json`), acquires a per-passcode single-flight lock + **token-bucket rate limiter (≤ 10 req/s)**, fetches once from YGOPRODeck, atomically stores it on disk, and serves it locally forever after.
2. **Opt-In Card Text Sync (`sync_descriptions`):**
   - Triggered only on explicit user action (Settings button or `python card_cache.py --sync-text`).
   - Filters results strictly to passcodes present in `cards_db.json` and writes `cache/card_descriptions.json` atomically.

---

## 5. Frontend Architecture

### Procedural SVG/CSS Card Frame Pipeline

```text
Card Render Request
       │
       ├── [ Art Cache Disabled & No TAGFORCE_ART_DIR ] (Default)
       │         └── Render Procedural SVG/CSS Card Frame (zero external requests)
       │             • Color-coded by frame_type (Normal / Effect / Fusion / Ritual / Spell / Trap / Anime)
       │             • Displays Name, Attribute badge, Level stars, Race/Subtype, ATK/DEF (-1 -> ?)
       │
       └── [ User Opted-In Local Art Cache OR TAGFORCE_ART_DIR Configured ]
                 └── Request same-origin /api/card_image/{passcode}?size=small|full (loading="lazy")
                           ├── [ HTTP 200 ] -> Display cached local image
                           └── [ HTTP 404 / Error ] -> Record in failedArtCache Set
                                                       & fall back cleanly to Procedural Frame
```

### State Management, Undo/Redo & Demo Mode Fallback

- **Hybrid Static + Backend Boot:** On `DOMContentLoaded`, `app.js` loads `cards_db.json` and probes `GET /api/status` + `GET /api/deck`. If no Python backend is running (e.g., opened on GitHub Pages), it seamlessly falls back to `sample_deck.json` with `localStorage` persistence.
- **History Stack:** Captures deck mutations and deck-name edits up to 100 states with proper Undo/Redo button disabled states and an unsaved-changes indicator.
- **Deck Analytics & Tools:** Computes real-time breakdown across Normal/Effect/Fusion/Ritual/Spell/Trap, Level and Attribute distributions, an interactive **5-Card Opening Hand Simulator** (`+1 Draw`, `New Hand`), and `.ydk` / `.json` / plain-text import & export.

---

## 6. End-to-End Save & Sync Data Flow

```text
[ Browser UI ] User edits deck & clicks Save (or presses Ctrl+S)
       │
       ▼ POST /api/save_deck { name, main: [gidx...], side: [gidx...], extra: [gidx...], auto_unlock }
[ run_showcase.py ]
       │
       ▼
[ tagforce_save.py ]
       ├── 1. validate_deck_payload()  (valid game_index, 80/15/30 caps, <=3 per name, Fusion-only Extra)
       ├── 2. find_deck_offset()       (structural validation at 0x5880 or aligned fallback scan)
       ├── 3. patch_save_bytes()       (diff old vs. new deck -> update 0x13F11 inventory + 0x5880 block)
       └── 4. save_deck_to_path()      (immutable .original.bak + rotating timestamped .bak + atomic os.replace)
       │
       ▼ HTTP 200 JSON { status, message, backups }
[ Browser UI ] Shows non-blocking success toast & updates backup list
       │
       ▼
[ PPSSPP ] Load game -> Active deck & trunk inventory load cleanly with zero corruption
```
