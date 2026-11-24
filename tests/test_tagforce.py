"""Comprehensive stdlib unit & integration tests for Duelist Hub (Tag Force 2)."""

import json
import os
import shutil
import struct
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from card_cache import CardCacheManager
import extract_deck
from run_showcase import DuelistHubState, create_server
from tagforce_save import (
    DECK_BLOCK_SIZE,
    DEFAULT_DB_PATH,
    DEFAULT_DECK_OFFSET,
    DEFAULT_SAMPLE_DECK_PATH,
    ID13_MASK,
    INVENTORY_OFFSET,
    MAX_EXTRA,
    MAX_MAIN,
    MAX_SIDE,
    MIN_SAVE_SIZE,
    NUM_CARDS,
    DeckValidationError,
    EncryptedSaveError,
    InvalidSaveError,
    build_id_maps,
    detect_region,
    encode_deck_name,
    find_deck_offset,
    find_save_path,
    list_backups,
    load_card_db,
    load_sample_deck,
    patch_save_bytes,
    read_deck_bytes,
    restore_backup,
    save_deck_to_path,
    validate_deck_payload,
)


def build_synthetic_save(
    cards_db,
    *,
    deck_name="Starting Deck",
    main=None,
    side=None,
    extra=None,
    deck_offset=DEFAULT_DECK_OFFSET,
    inventory_overrides=None,
    total_size=0x18000,
):
    """Creates a realistic synthetic decrypted Tag Force 2 DATA0 buffer."""
    assert total_size >= MIN_SAVE_SIZE
    _, game_to_id13 = build_id_maps(cards_db)
    buf = bytearray(total_size)

    main = list(main or [])
    side = list(side or [])
    extra = list(extra or [])

    name_bytes = encode_deck_name(deck_name)
    counts_bytes = struct.pack("<III", len(main), len(side), len(extra))

    def _pack(ids, cap):
        out = bytearray(cap * 2)
        for i, gidx in enumerate(ids):
            struct.pack_into("<H", out, i * 2, game_to_id13[gidx] & ID13_MASK)
        return bytes(out)

    block = (
        name_bytes
        + counts_bytes
        + _pack(main, MAX_MAIN)
        + _pack(side, MAX_SIDE)
        + _pack(extra, MAX_EXTRA)
    )
    assert len(block) == DECK_BLOCK_SIZE
    buf[deck_offset : deck_offset + DECK_BLOCK_SIZE] = block

    # Populate inventory for slotted cards
    for gidx in set(main) | set(side) | set(extra):
        off = INVENTORY_OFFSET + gidx * 4
        m = main.count(gidx)
        s = side.count(gidx)
        e = extra.count(gidx)
        buf[off] = m
        buf[off + 1] = max(0, 3 - m - s - e)
        buf[off + 2] = s
        buf[off + 3] = e

    if inventory_overrides:
        for gidx, quad in inventory_overrides.items():
            off = INVENTORY_OFFSET + gidx * 4
            buf[off : off + 4] = bytes(quad)

    return bytes(buf)


class TestDatabaseAndSampleDeck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cards_db = load_card_db(DEFAULT_DB_PATH)
        cls.sample_deck = load_sample_deck(DEFAULT_SAMPLE_DECK_PATH)

    def test_cards_db_sanitized_and_complete(self):
        self.assertEqual(len(self.cards_db), NUM_CARDS)
        id13_to_game, game_to_id13 = build_id_maps(self.cards_db)
        self.assertEqual(len(game_to_id13), NUM_CARDS)
        # 2924 real cards + 0 sentinel = 2925 unique id13 mappings
        self.assertEqual(len(id13_to_game), 2925)

        for idx, card in enumerate(self.cards_db):
            self.assertEqual(card["game_index"], idx)
            self.assertNotIn("desc", card)
            self.assertNotIn("internal_id_hex", card)
            self.assertIn("internal_id", card)
            self.assertIn("passcode", card)
            self.assertIn("name", card)

    def test_sample_deck_valid(self):
        validated = validate_deck_payload(self.sample_deck, self.cards_db)
        self.assertEqual(validated["name"], "Cyber-Dragon Demo Deck")
        self.assertEqual(len(validated["main"]), 40)
        self.assertGreater(len(validated["extra"]), 0)


class TestSaveEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cards_db = load_card_db(DEFAULT_DB_PATH)
        cls.sample_deck = load_sample_deck(DEFAULT_SAMPLE_DECK_PATH)
        cls.by_name = {c["name"]: c["game_index"] for c in cls.cards_db if c.get("name")}
        cls.cyber_dragon = cls.by_name["Cyber Dragon"]
        cls.sangan = cls.by_name["Sangan"]
        cls.heavy_storm = cls.by_name["Heavy Storm"]
        cls.power_bond = cls.by_name["Power Bond"]
        cls.cyber_end = cls.by_name["Cyber End Dragon"]

    def test_roundtrip_and_renamed_deck_detection(self):
        raw = build_synthetic_save(
            self.cards_db,
            deck_name="Starting Deck",
            main=self.sample_deck["main"],
            side=self.sample_deck["side"],
            extra=self.sample_deck["extra"],
        )
        extracted = read_deck_bytes(raw, self.cards_db)
        self.assertEqual(extracted["deck_offset"], DEFAULT_DECK_OFFSET)
        self.assertEqual(extracted["name"], "Starting Deck")
        self.assertEqual(extracted["main"], self.sample_deck["main"])
        self.assertEqual(extracted["side"], self.sample_deck["side"])
        self.assertEqual(extracted["extra"], self.sample_deck["extra"])

        # Rename deck (eliminating "Starting Deck" string) and re-save
        renamed_payload = dict(self.sample_deck, name="Zane's Custom Cyber Deck ⚡")
        patched = patch_save_bytes(raw, renamed_payload, self.cards_db)
        self.assertEqual(patched.find("Starting Deck".encode("utf-16-le")), -1)

        re_read = read_deck_bytes(patched, self.cards_db)
        self.assertEqual(re_read["deck_offset"], DEFAULT_DECK_OFFSET)
        self.assertEqual(re_read["name"], "Zane's Custom Cyber Deck ⚡")
        self.assertEqual(re_read["main"], self.sample_deck["main"])

        # Second patch on already-renamed deck still locates offset cleanly
        second_payload = dict(self.sample_deck, name="Tournament Build v2")
        patched2 = patch_save_bytes(patched, second_payload, self.cards_db)
        re_read2 = read_deck_bytes(patched2, self.cards_db)
        self.assertEqual(re_read2["name"], "Tournament Build v2")
        self.assertEqual(re_read2["deck_offset"], DEFAULT_DECK_OFFSET)

    def test_non_default_offset_discovery(self):
        alt_offset = 0x6200
        raw = build_synthetic_save(
            self.cards_db,
            deck_name="Relocated Deck",
            main=self.sample_deck["main"],
            extra=self.sample_deck["extra"],
            deck_offset=alt_offset,
        )
        id13_to_game, _ = build_id_maps(self.cards_db)
        found = find_deck_offset(raw, id13_to_game)
        self.assertEqual(found, alt_offset)
        parsed = read_deck_bytes(raw, self.cards_db)
        self.assertEqual(parsed["name"], "Relocated Deck")
        self.assertEqual(parsed["main"], self.sample_deck["main"])

    def test_encrypted_and_truncated_saves_rejected(self):
        for header in (b"~PSP" + b"\x00" * 100, b"\x51\x66\x4e\x4f" + b"\x00" * 100):
            with self.assertRaises(EncryptedSaveError):
                read_deck_bytes(header, self.cards_db)

        with self.assertRaises(InvalidSaveError):
            read_deck_bytes(b"\x00" * 4096, self.cards_db)

    def test_inventory_diffing_and_trunk_preservation(self):
        # Start with Sangan (1 in main, 2 in trunk) and Cyber Dragon (2 in main, 9 in trunk!)
        raw = build_synthetic_save(
            self.cards_db,
            deck_name="Inventory Test",
            main=[self.sangan, self.cyber_dragon, self.cyber_dragon],
            extra=[self.cyber_end],
            inventory_overrides={
                self.sangan: (1, 2, 0, 0),
                self.cyber_dragon: (2, 9, 0, 0),
                self.heavy_storm: (0, 0, 0, 0),
            },
        )

        # Remove Sangan, keep 3x Cyber Dragon, add 1x Heavy Storm (previously unowned)
        new_payload = {
            "name": "Inventory Test",
            "main": [self.cyber_dragon, self.cyber_dragon, self.cyber_dragon, self.heavy_storm],
            "side": [],
            "extra": [self.cyber_end],
        }
        patched = patch_save_bytes(raw, new_payload, self.cards_db, auto_unlock=True)

        # Removed Sangan: main/side/extra cleared to 0, trunk kept >= 3
        s_off = INVENTORY_OFFSET + self.sangan * 4
        self.assertEqual(tuple(patched[s_off : s_off + 4]), (0, 3, 0, 0))

        # Cyber Dragon: 3 in main, 9 in trunk MUST NOT be downgraded!
        c_off = INVENTORY_OFFSET + self.cyber_dragon * 4
        self.assertEqual(tuple(patched[c_off : c_off + 4]), (3, 9, 0, 0))

        # Newly added Heavy Storm: 1 in main, 2 auto-unlocked in trunk (total 3)
        h_off = INVENTORY_OFFSET + self.heavy_storm * 4
        self.assertEqual(tuple(patched[h_off : h_off + 4]), (1, 2, 0, 0))

        # Test auto_unlock=False conserves total ownership strictly
        patched_no_unlock = patch_save_bytes(
            raw,
            {
                "name": "Strict Ownership",
                "main": [self.cyber_dragon],  # reduced from 2 to 1 (total was 11 -> trunk becomes 10)
                "side": [],
                "extra": [],
            },
            self.cards_db,
            auto_unlock=False,
        )
        self.assertEqual(tuple(patched_no_unlock[c_off : c_off + 4]), (1, 10, 0, 0))
        self.assertEqual(tuple(patched_no_unlock[s_off : s_off + 4]), (0, 3, 0, 0))

    def test_payload_validation_rules(self):
        # Empty name
        with self.assertRaises(DeckValidationError):
            validate_deck_payload({"name": "   ", "main": [], "side": [], "extra": []}, self.cards_db)
        # >3 copies across main+side
        with self.assertRaises(DeckValidationError):
            validate_deck_payload(
                {
                    "name": "Too Many",
                    "main": [self.cyber_dragon] * 3,
                    "side": [self.cyber_dragon],
                    "extra": [],
                },
                self.cards_db,
            )
        # Non-fusion in extra
        with self.assertRaises(DeckValidationError):
            validate_deck_payload(
                {"name": "Bad Extra", "main": [], "side": [], "extra": [self.sangan]},
                self.cards_db,
            )
        # Fusion in main
        with self.assertRaises(DeckValidationError):
            validate_deck_payload(
                {"name": "Bad Main", "main": [self.cyber_end], "side": [], "extra": []},
                self.cards_db,
            )
        # Sentinel slot 0 or boolean index
        with self.assertRaises(DeckValidationError):
            validate_deck_payload({"name": "Zero", "main": [0], "side": [], "extra": []}, self.cards_db)
        with self.assertRaises(DeckValidationError):
            validate_deck_payload({"name": "Bool", "main": [True], "side": [], "extra": []}, self.cards_db)
        # Exceeds max counts
        with self.assertRaises(DeckValidationError):
            validate_deck_payload(
                {"name": "Huge", "main": [1] * (MAX_MAIN + 1), "side": [], "extra": []},
                self.cards_db,
            )

    def test_backups_rotation_restore_and_traversal_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_path = os.path.join(tmp, "ULES009250001", "DATA0")
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            original_bytes = build_synthetic_save(
                self.cards_db,
                deck_name="Original Save",
                main=[self.cyber_dragon, self.sangan],
                extra=[self.cyber_end],
            )
            with open(save_path, "wb") as f:
                f.write(original_bytes)

            self.assertEqual(detect_region(save_path), "EU (ULES00925)")
            self.assertEqual(find_save_path(explicit_path=tmp), save_path)

            # Perform 5 saves with max_rotating=3
            for i in range(5):
                save_deck_to_path(
                    save_path,
                    {
                        "name": f"Edit {i}",
                        "main": [self.power_bond],
                        "side": [],
                        "extra": [],
                    },
                    self.cards_db,
                    max_rotating_backups=3,
                )

            baks = list_backups(save_path)
            self.assertIn("DATA0.original.bak", baks)
            # 3 rotating + 1 immutable original = 4
            self.assertEqual(len(baks), 4)

            # Path traversal & bogus backup names rejected
            for bad in ("../DATA0", "sub/DATA0.original.bak", "nonexistent.bak", ""):
                with self.assertRaises(ValueError):
                    restore_backup(save_path, bad, self.cards_db)

            # Restore immutable original backup
            res = restore_backup(save_path, "DATA0.original.bak", self.cards_db)
            self.assertEqual(res["deck"]["name"], "Original Save")
            self.assertEqual(res["deck"]["main"], [self.cyber_dragon, self.sangan])

    def test_extract_deck_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_path = os.path.join(tmp, "DATA0")
            out_json = os.path.join(tmp, "deck.json")
            out_md = os.path.join(tmp, "deck.md")
            with open(save_path, "wb") as f:
                f.write(
                    build_synthetic_save(
                        self.cards_db,
                        deck_name="CLI Deck",
                        main=[self.cyber_dragon, self.cyber_dragon, self.sangan],
                        extra=[self.cyber_end],
                    )
                )
            rc = extract_deck.main(["--save", save_path, "--out-json", out_json, "--out-md", out_md])
            self.assertEqual(rc, 0)
            with open(out_json, "r", encoding="utf-8") as f:
                exported = json.load(f)
            self.assertEqual(exported["name"], "CLI Deck")
            self.assertEqual(len(exported["main"]), 3)
            self.assertTrue(os.path.isfile(out_md))


class TestHTTPServerIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="duelist_hub_test_")
        self.cache_dir = os.path.join(self.tmp, "cache")
        self.art_dir = os.path.join(self.tmp, "local_art")
        os.makedirs(self.art_dir, exist_ok=True)

        self.cards_db = load_card_db(DEFAULT_DB_PATH)
        self.sample_deck = load_sample_deck(DEFAULT_SAMPLE_DECK_PATH)

        # Start server in Demo Mode on ephemeral port 0
        self.state = DuelistHubState(
            cache_dir=self.cache_dir,
            art_dir="",  # disabled initially
            force_demo=True,
        )
        self.httpd, self.port, _ = create_server(
            host="127.0.0.1",
            port=0,
            state=self.state,
            auto_fallback_port=False,
            quiet=True,
        )
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.port}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _req(self, path, method="GET", body=None, headers=None):
        req = urllib.request.Request(
            self.base_url + path,
            data=body,
            headers=headers or {},
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as err:
            return err.code, dict(err.headers), err.read()

    def test_demo_status_deck_save_and_security_headers(self):
        code, headers, raw = self._req("/api/status")
        self.assertEqual(code, 200)
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        status = json.loads(raw)
        self.assertEqual(status["mode"], "demo")
        self.assertFalse(status["art_cache_enabled"])
        self.assertFalse(status["art_dir_configured"])
        self.assertEqual(status["text_cache_count"], 0)

        code, _, raw = self._req("/api/deck")
        self.assertEqual(code, 200)
        deck = json.loads(raw)
        self.assertEqual(deck["mode"], "demo")
        self.assertEqual(deck["name"], "Cyber-Dragon Demo Deck")
        self.assertEqual(len(deck["main"]), 40)

        # Save edited deck in Demo Mode
        edited = dict(self.sample_deck, name="Demo Updated")
        code, _, raw = self._req(
            "/api/save_deck",
            method="POST",
            body=json.dumps(edited).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(code, 200)
        resp = json.loads(raw)
        self.assertEqual(resp["status"], "success")
        self.assertEqual(resp["deck"]["name"], "Demo Updated")

        # Invalid payload rejected with 400
        code, _, _ = self._req(
            "/api/save_deck",
            method="POST",
            body=json.dumps({"name": "", "main": []}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(code, 400)

    def test_upload_patch_download_and_restore_save(self):
        # Initially in Demo Mode -> download_save returns 404
        code, _, _ = self._req("/api/download_save")
        self.assertEqual(code, 404)

        # Uploading encrypted save returns 400 with encrypted=true
        code, _, raw = self._req(
            "/api/upload_save",
            method="POST",
            body=b"~PSP" + b"\x00" * 512,
            headers={"Content-Type": "application/octet-stream"},
        )
        self.assertEqual(code, 400)
        self.assertTrue(json.loads(raw).get("encrypted"))

        # Upload valid decrypted synthetic DATA0
        synth = build_synthetic_save(
            self.cards_db,
            deck_name="Uploaded Deck",
            main=self.sample_deck["main"][:10],
            extra=self.sample_deck["extra"][:2],
        )
        code, _, raw = self._req(
            "/api/upload_save",
            method="POST",
            body=synth,
            headers={"Content-Type": "application/octet-stream"},
        )
        self.assertEqual(code, 200)
        uploaded = json.loads(raw)
        self.assertEqual(uploaded["deck"]["name"], "Uploaded Deck")
        self.assertEqual(uploaded["status_info"]["mode"], "save")

        # Save modification onto uploaded DATA0
        modified = {
            "name": "Patched Uploaded Deck",
            "main": self.sample_deck["main"][:12],
            "side": [],
            "extra": self.sample_deck["extra"][:2],
            "auto_unlock": True,
        }
        code, _, raw = self._req(
            "/api/save_deck",
            method="POST",
            body=json.dumps(modified).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(code, 200)
        saved_res = json.loads(raw)
        self.assertIn("uploaded_DATA0.original.bak", saved_res["backups"])

        # Download patched DATA0 and verify binary deck contents
        code, _, dl_bytes = self._req("/api/download_save")
        self.assertEqual(code, 200)
        parsed = read_deck_bytes(dl_bytes, self.cards_db)
        self.assertEqual(parsed["name"], "Patched Uploaded Deck")
        self.assertEqual(len(parsed["main"]), 12)

        # Restore original backup
        code, _, raw = self._req(
            "/api/restore_backup",
            method="POST",
            body=json.dumps({"backup": "uploaded_DATA0.original.bak"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(raw)["deck"]["name"], "Uploaded Deck")

    def test_static_allowlist_and_traversal_blocked(self):
        for allowed in ("/cards_db.json", "/sample_deck.json"):
            code, _, _ = self._req(allowed)
            self.assertEqual(code, 200, f"Expected 200 for {allowed}")

        for forbidden in (
            "/.git/config",
            "/run_showcase.py",
            "/tagforce_save.py",
            "/tests/test_tagforce.py",
            "/../run_showcase.py",
        ):
            code, _, _ = self._req(forbidden)
            self.assertIn(code, (403, 404), f"Expected 403/404 for {forbidden}, got {code}")

    def test_card_image_disabled_and_local_art_dir(self):
        # Art cache disabled and no local art dir -> 404
        code, _, _ = self._req("/api/card_image/70095154?size=small")
        self.assertEqual(code, 404)

        # Configure local TAGFORCE_ART_DIR with a synthetic JPEG
        fake_jpg = b"\xff\xd8\xff\xe0FAKEJPEGDATA\xff\xd9"
        with open(os.path.join(self.art_dir, "70095154.jpg"), "wb") as f:
            f.write(fake_jpg)

        mgr = CardCacheManager(cache_dir=self.cache_dir, art_dir=self.art_dir)
        self.assertTrue(mgr.is_art_dir_configured())
        img = mgr.get_card_image("70095154", size="small")
        self.assertIsNotNone(img)
        self.assertEqual(img, (fake_jpg, "image/jpeg"))

        # Swap manager on running state and verify HTTP serving
        self.state.cache = mgr
        code, headers, body = self._req("/api/card_image/70095154?size=small")
        self.assertEqual(code, 200)
        self.assertEqual(headers.get("Content-Type"), "image/jpeg")
        self.assertEqual(body, fake_jpg)

        # Invalid passcode rejected
        code, _, _ = self._req("/api/card_image/00000000?size=small")
        self.assertEqual(code, 404)

        # Settings toggle persists
        code, _, raw = self._req(
            "/api/settings",
            method="POST",
            body=json.dumps({"art_cache_enabled": True}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(raw)["art_cache_enabled"])

        # Descriptions endpoint returns {} initially
        code, _, raw = self._req("/api/card_descriptions")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(raw), {})


if __name__ == "__main__":
    unittest.main()
