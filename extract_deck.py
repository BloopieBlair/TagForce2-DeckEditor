"""CLI utility to extract the active player deck from a decrypted Tag Force 2 DATA0 save.

Thin wrapper around `tagforce_save.py` with zero `CARD_Prop.bin` dependency and
no import-time `sys.argv` side effects.
"""

import argparse
from collections import Counter
import json
import os
import sys
from typing import Optional

from tagforce_save import (
    DEFAULT_DB_PATH,
    EncryptedSaveError,
    InvalidSaveError,
    find_save_path,
    load_card_db,
    read_deck_bytes,
)

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def extract_and_format(
    save_path: Optional[str] = None,
    out_json: Optional[str] = None,
    out_md: Optional[str] = None,
    db_path: Optional[str] = None,
) -> bool:
    """Extracts the active deck from DATA0 and writes JSON + Markdown summaries."""
    resolved_save = find_save_path(explicit_path=save_path)
    if not resolved_save or not os.path.isfile(resolved_save):
        print("Save file not found. Pass --save PATH or set TAGFORCE_SAVE_PATH.")
        return False

    try:
        cards_db = load_card_db(db_path or DEFAULT_DB_PATH)
        with open(resolved_save, "rb") as f:
            raw_bytes = f.read()
        deck = read_deck_bytes(raw_bytes, cards_db)
    except EncryptedSaveError as err:
        print(f"Error: {err}")
        return False
    except (InvalidSaveError, FileNotFoundError, ValueError) as err:
        print(f"Error: {err}")
        return False

    deck_offset = deck["deck_offset"]
    main_cards = [cards_db[gidx] for gidx in deck["main"]]
    side_cards = [cards_db[gidx] for gidx in deck["side"]]
    extra_cards = [cards_db[gidx] for gidx in deck["extra"]]

    target_json = out_json or os.path.join(_SCRIPT_DIR, "player_deck.json")
    target_md = out_md or os.path.join(_SCRIPT_DIR, "decklist.md")

    deck_json_data = {
        "offset": deck_offset,
        "name": deck["name"],
        "main": main_cards,
        "extra": extra_cards,
        "side": side_cards,
    }
    with open(target_json, "w", encoding="utf-8") as f:
        json.dump(deck_json_data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    with open(target_md, "w", encoding="utf-8") as f:
        f.write(f"# Yu-Gi-Oh! GX Tag Force 2 - {deck['name']}\n\n")
        f.write(f"**Save File Offset:** `0x{deck_offset:X}`\n")
        f.write(f"**Main Deck:** {len(main_cards)} cards  \n")
        f.write(f"**Extra Deck:** {len(extra_cards)} cards  \n")
        f.write(f"**Side Deck:** {len(side_cards)} cards  \n\n")

        def _write_section(title: str, cards: list) -> None:
            f.write(f"## {title}\n")
            counts = Counter((c["name"], c.get("passcode", "00000000")) for c in cards)
            for (name, passcode), qty in sorted(counts.items(), key=lambda x: x[0][0]):
                tag = f" ({passcode})" if passcode and passcode != "00000000" else " (Anime)"
                f.write(f"- {qty}x {name}{tag}\n")
            f.write("\n")

        _write_section("Main Deck", main_cards)
        if extra_cards:
            _write_section("Extra Deck", extra_cards)
        if side_cards:
            _write_section("Side Deck", side_cards)

    print(f"Found deck '{deck['name']}' at offset 0x{deck_offset:X} "
          f"(Main={len(main_cards)}, Side={len(side_cards)}, Extra={len(extra_cards)})")
    print(f"Deck JSON written to: {target_json}")
    print(f"Deck list written to: {target_md}")
    return True


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract active deck from a decrypted Yu-Gi-Oh! GX: Tag Force 2 DATA0 save."
    )
    parser.add_argument("--save", default=None, help="Path to decrypted DATA0 save file.")
    parser.add_argument("--out-json", default=None, help="Output JSON path (default: ./player_deck.json).")
    parser.add_argument("--out-md", default=None, help="Output Markdown path (default: ./decklist.md).")
    parser.add_argument("--db", default=None, help="Path to cards_db.json.")
    args = parser.parse_args(argv)

    ok = extract_and_format(
        save_path=args.save,
        out_json=args.out_json,
        out_md=args.out_md,
        db_path=args.db,
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
