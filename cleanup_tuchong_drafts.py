#!/usr/bin/env python3
"""
Delete Tuchong draft folders from the contributor draft list.

Safe by default:
  python3 cleanup_tuchong_drafts.py

Actually delete all draft folders:
  python3 cleanup_tuchong_drafts.py --execute --all

Delete only the first 20 draft folders:
  python3 cleanup_tuchong_drafts.py --execute --limit 20
"""

import argparse
import sys
from dataclasses import dataclass
from typing import Optional

from playwright.sync_api import Page, sync_playwright

from upload.browser import get_context
from upload.tuchong import ensure_login

DRAFTS_URL = "https://contributor.tuchong.com/mine?status=draft&source="

@dataclass
class DraftCard:
    kind: str
    asset_id: str
    count_text: str
    upload_time: str


def _read_cards(page: Page) -> list[DraftCard]:
    cards = []
    for item in page.locator("li.contribute__item").all():
        try:
            kind = (item.locator("span.type-tag").text_content(timeout=500) or "").strip()
            asset_id = (item.locator("span.type-id").text_content(timeout=500) or "").strip()
            count_text = (item.locator("span.contribute__item-img-total").text_content(timeout=500) or "").strip()
            time_raw = (item.locator("p.contribute__item-des-time").text_content(timeout=500) or "").strip()
            upload_time = time_raw.replace("上传时间：", "").replace("上传时间:", "").strip()
            cards.append(DraftCard(kind=kind, asset_id=asset_id, count_text=count_text, upload_time=upload_time))
        except Exception:
            continue
    return cards


def _get_context(playwright, use_system_chrome: bool):
    return get_context(
        "tuchong", playwright, prefer_system_chrome=use_system_chrome
    )


def _goto_drafts(page: Page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_timeout(2_000)

    # Some accounts land on the broader submission page; click the draft tab if it exists.
    try:
        page.locator("text=草稿").first.click(timeout=5_000)
        page.wait_for_timeout(1_000)
    except Exception:
        pass


def _confirm_delete(page: Page) -> None:
    """Handle common confirmation modal variants."""
    for selector in [
        "button:has-text('确定')",
        "button:has-text('确认')",
        "button:has-text('确 认')",
        "button:has-text('删除')",
        ".ant-modal button:has-text('确 定')",
    ]:
        try:
            page.locator(selector).last.click(timeout=2_000)
            page.wait_for_timeout(1_000)
            return
        except Exception:
            pass

    # Some delete actions may not show a modal. Give the list a moment to update.
    page.wait_for_timeout(1_000)


def _delete_card(page: Page, card: DraftCard) -> bool:
    if not card.asset_id:
        print("  [warn] card has no stable asset ID, skipping", flush=True)
        return False

    card_loc = page.locator(f"li.contribute__item:has(span.type-id:text-is('{card.asset_id}'))")
    if card_loc.count() != 1:
        print(
            f"  [warn] expected one card for id={card.asset_id}, found {card_loc.count()}; skipping",
            flush=True,
        )
        return False

    card_loc.locator("div.contribute__item-img").hover()
    page.wait_for_timeout(300)
    card_loc.locator("span.contribute__item-img-delete").click()
    _confirm_delete(page)

    for _ in range(8):
        still_present = any(
            c.asset_id == card.asset_id and c.upload_time == card.upload_time
            for c in _read_cards(page)
        )
        if not still_present:
            return True
        page.wait_for_timeout(500)

    return False


def _print_card(prefix: str, card: DraftCard) -> None:
    parts = [prefix]
    if card.asset_id:
        parts.append(f"id={card.asset_id}")
    if card.count_text:
        parts.append(card.count_text)
    if card.upload_time:
        parts.append(card.upload_time)
    print("  " + " | ".join(parts), flush=True)


def preview(page: Page, scan_limit: int) -> int:
    seen: set[tuple[str, str]] = set()
    stable_scrolls = 0

    while len(seen) < scan_limit and stable_scrolls < 3:
        cards = _read_cards(page)
        for card in cards:
            key = (card.asset_id, card.upload_time)
            if key in seen:
                continue
            seen.add(key)
            _print_card(f"[{len(seen)}]", card)
            if len(seen) >= scan_limit:
                break

        old_y = page.evaluate("() => window.scrollY")
        page.evaluate("() => window.scrollBy(0, Math.floor(window.innerHeight * 0.85))")
        page.wait_for_timeout(1_200)
        new_y = page.evaluate("() => window.scrollY")
        stable_scrolls = stable_scrolls + 1 if new_y == old_y else 0

    return len(seen)


def delete_drafts(page: Page, limit: Optional[int]) -> int:
    deleted = 0
    stable_scrolls = 0

    while limit is None or deleted < limit:
        cards = _read_cards(page)
        if not cards:
            old_y = page.evaluate("() => window.scrollY")
            page.evaluate("() => window.scrollBy(0, Math.floor(window.innerHeight * 0.85))")
            page.wait_for_timeout(1_200)
            new_y = page.evaluate("() => window.scrollY")
            stable_scrolls = stable_scrolls + 1 if new_y == old_y else 0
            if stable_scrolls >= 3:
                break
            continue

        stable_scrolls = 0
        card = cards[0]
        _print_card(f"deleting {deleted + 1}", card)
        ok = _delete_card(page, card)
        if ok:
            deleted += 1
        else:
            print("  [warn] delete did not appear to remove the visible draft folder; stopping", flush=True)
            break

    return deleted


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean up Tuchong draft folders")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--all", action="store_true", help="delete all draft folders when used with --execute")
    mode.add_argument("--limit", type=int, help="delete at most N draft folders when used with --execute")
    parser.add_argument("--execute", action="store_true", help="actually delete draft folders; default is preview only")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt in execute mode")
    parser.add_argument("--preview-limit", type=int, default=50, help="number of draft folders to list in preview mode")
    parser.add_argument("--url", default=DRAFTS_URL, help="Tuchong draft list URL")
    parser.add_argument("--system-chrome", action="store_true", help="use Google Chrome instead of bundled Chromium")
    args = parser.parse_args()

    if args.execute and not args.all and args.limit is None:
        sys.exit("Refusing to delete without --all or --limit N.")
    if args.limit is not None and args.limit <= 0:
        sys.exit("--limit must be a positive integer.")

    with sync_playwright() as pw:
        ctx = _get_context(pw, args.system_chrome)
        try:
            ensure_login(ctx)
            page = ctx.new_page()
            _goto_drafts(page, args.url)

            if not args.execute:
                print("Preview only. No draft folders will be deleted.", flush=True)
                count = preview(page, args.preview_limit)
                print(f"\nListed {count} draft folder(s). Add --execute with --all or --limit N to delete.", flush=True)
                return

            target = "ALL visible/scrollable" if args.all else str(args.limit)
            if not args.yes:
                answer = input(f"Delete {target} Tuchong draft folder(s)? Type DELETE to continue: ")
                if answer.strip() != "DELETE":
                    print("Aborted.")
                    return

            deleted = delete_drafts(page, None if args.all else args.limit)
            print(f"\nDeleted {deleted} Tuchong draft folder(s).", flush=True)
        finally:
            ctx.close()


if __name__ == "__main__":
    main()
