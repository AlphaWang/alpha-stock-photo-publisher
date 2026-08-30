#!/usr/bin/env python3
"""Find and repair incomplete Tuchong drafts by exact original filename.

The command is read-only unless ``--execute`` is supplied.  It never uploads
or submits images; execute mode fills category, description, and keywords in
already existing drafts, saves them, and verifies the saved values through the
draft-detail API.
"""

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from playwright.sync_api import BrowserContext, Page, sync_playwright

from upload.browser import get_context
from upload.tuchong import (
    _check_pledge,
    _fill_metadata,
    _select_card_for_edit,
    ensure_login,
)
from upload_photos import SUPPORTED_EXTS, find_pairs, load_metadata

DRAFTS_URL = "https://contributor.tuchong.com/mine?status=draft&source="
DETAIL_URL = "https://contributor.tuchong.com/api/creative/group/detail/{group_id}"


@dataclass(frozen=True)
class LocalPair:
    image: Path
    metadata_path: Path
    metadata: dict


@dataclass(frozen=True)
class DraftAsset:
    group_id: str
    source: int
    filename: str
    description: str
    keywords: str
    category: str

    @property
    def missing_fields(self) -> tuple[str, ...]:
        missing = []
        if not self.description.strip():
            missing.append("description")
        if len(_split_keywords(self.keywords)) < 5:
            missing.append("keywords")
        if not self.category.strip():
            missing.append("category")
        return tuple(missing)


def _split_keywords(value: str) -> list[str]:
    return [part for part in re.split(r"[,，\s]+", value or "") if part]


def _local_pairs(target: Path) -> dict[str, LocalPair]:
    if target.is_file():
        directories = [target.parent]
        requested_name = target.name
    else:
        directories = sorted(
            {
                path.parent
                for path in target.rglob("*")
                if path.is_file() and path.suffix.lower() in SUPPORTED_EXTS
            }
        )
        requested_name = None

    by_filename: dict[str, LocalPair] = {}
    ambiguous: set[str] = set()
    for directory in directories:
        for image, metadata_path in find_pairs(directory):
            if requested_name is not None and image.name != requested_name:
                continue
            pair = LocalPair(image, metadata_path, load_metadata(metadata_path))
            if image.name in by_filename and by_filename[image.name].image != image:
                ambiguous.add(image.name)
            else:
                by_filename[image.name] = pair

    if ambiguous:
        names = ", ".join(sorted(ambiguous))
        raise RuntimeError(
            "Tuchong exposes only original filenames; duplicate in-scope names "
            f"cannot be matched safely: {names}"
        )
    return by_filename


def _with_query(url: str, **updates: object) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    for key, value in updates.items():
        query[key] = [str(value)]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def _open_draft_index(page: Page) -> tuple[str, dict]:
    captured = []

    def capture(response) -> None:
        if "/api/group/mycontribute" not in response.url:
            return
        try:
            captured.append((response.url, response.json()))
        except Exception:
            pass

    page.on("response", capture)
    page.goto(DRAFTS_URL, wait_until="networkidle", timeout=30_000)
    page.wait_for_timeout(500)
    if not captured:
        raise RuntimeError("Tuchong draft-list API response was not observed")
    return captured[-1]


def _list_groups(context: BrowserContext, first_url: str, first_payload: dict) -> list[dict]:
    first_data = first_payload.get("data") or {}
    total = int(first_data.get("total") or 0)
    page_size = 100
    groups: list[dict] = []
    pages = max(1, (total + page_size - 1) // page_size)
    for page_number in range(1, pages + 1):
        response = context.request.get(
            _with_query(first_url, count=page_size, page=page_number),
            timeout=30_000,
        )
        payload = response.json()
        if not response.ok or payload.get("code") != 0:
            raise RuntimeError(f"draft list page {page_number} failed: {payload}")
        groups.extend((payload.get("data") or {}).get("groups") or [])
    print(f"  Indexed {len(groups)}/{total} Tuchong draft groups", flush=True)
    return groups


def _detail(
    context: BrowserContext,
    group_id: str,
    source: int,
    xsrf_token: str,
) -> dict:
    response = context.request.get(
        DETAIL_URL.format(group_id=group_id),
        params={"xsrfToken": xsrf_token, "source": source},
        timeout=30_000,
    )
    payload = response.json()
    groups = (payload.get("data") or {}).get("groups") or []
    if not response.ok or payload.get("code") != 0 or len(groups) != 1:
        raise RuntimeError(f"draft detail {group_id} failed: {payload}")
    return groups[0]


def _inventory_assets(
    context: BrowserContext,
    groups: list[dict],
    xsrf_token: str,
    wanted: set[str],
) -> dict[str, DraftAsset]:
    found: dict[str, DraftAsset] = {}
    duplicates: set[str] = set()
    for index, summary in enumerate(groups, start=1):
        group_id = str(summary.get("group_id") or "")
        source = int(summary.get("source") or 0)
        detail = _detail(context, group_id, source, xsrf_token)
        for image in detail.get("images") or []:
            filename = str(image.get("filename") or "")
            if filename not in wanted:
                continue
            asset = DraftAsset(
                group_id=group_id,
                source=source,
                filename=filename,
                description=str(detail.get("description") or ""),
                keywords=str(detail.get("keywords") or ""),
                category=str(detail.get("category") or ""),
            )
            if filename in found and found[filename].group_id != group_id:
                duplicates.add(filename)
            else:
                found[filename] = asset
        if index % 25 == 0 or index == len(groups):
            print(
                f"  Inspected {index}/{len(groups)} draft groups; "
                f"matched {len(found)} in-scope files",
                flush=True,
            )
    if duplicates:
        names = ", ".join(sorted(duplicates))
        raise RuntimeError(f"duplicate Tuchong drafts require manual resolution: {names}")
    return found


def _client_fields(page: Page) -> tuple[str, str, list[str]]:
    form = page.locator("form.contribute__sider-form")
    description = form.locator("textarea.ant-input").first.input_value().strip()
    category = form.locator(
        "input.ant-input[placeholder='请选择']"
    ).first.input_value().strip()
    keywords = [
        value.strip()
        for value in form.locator(
            ".ant-select-selection--multiple .ant-select-selection__choice"
        ).all_inner_texts()
        if value.strip()
    ]
    return description, category, keywords


def _expected_fields(metadata: dict) -> tuple[str, list[str], list[str]]:
    from upload.tuchong import _categories_for_metadata

    return (
        str(metadata.get("description_zh") or "")[:50],
        [str(value) for value in (metadata.get("keywords_zh") or [])[:30]],
        _categories_for_metadata(metadata),
    )


def _values_match(
    description: str,
    category: str,
    keywords: list[str],
    expected_description: str,
    expected_categories: list[str],
    expected_keywords: list[str],
) -> bool:
    keyword_set = set(keywords)
    return (
        description == expected_description
        and bool(category)
        and all(value in category for value in expected_categories)
        and len(keyword_set) >= 5
        and all(value in keyword_set for value in expected_keywords)
    )


def _repair_one(
    page: Page,
    context: BrowserContext,
    asset: DraftAsset,
    pair: LocalPair,
    xsrf_token: str,
) -> None:
    page.goto(
        f"https://contributor.tuchong.com/contribute/{asset.group_id}"
        f"?category={asset.source}",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    page.wait_for_selector(".contribute__image__item", timeout=30_000)
    _select_card_for_edit(page, pair.image)
    _fill_metadata(page, pair.metadata)

    expected_description, expected_keywords, expected_categories = _expected_fields(
        pair.metadata
    )
    description, category, keywords = _client_fields(page)
    if not _values_match(
        description,
        category,
        keywords,
        expected_description,
        expected_categories,
        expected_keywords,
    ):
        raise RuntimeError("client-side metadata read-back did not match the sidecar")

    _check_pledge(page)
    with page.expect_response(
        lambda response: (
            "/api/creative/groups" in response.url
            and response.request.method == "PATCH"
        ),
        timeout=30_000,
    ) as response_info:
        page.locator("button:has-text('保存草稿')").first.click(timeout=5_000)
    save_response = response_info.value
    payload = save_response.json()
    data = payload.get("data") or {}
    saved_ids = {str(value) for value in data.get("success_ids") or []}
    if (
        not save_response.ok
        or payload.get("code") != 0
        or asset.group_id not in saved_ids
    ):
        raise RuntimeError(f"draft save was not confirmed: {payload}")

    saved = _detail(context, asset.group_id, asset.source, xsrf_token)
    saved_images = saved.get("images") or []
    filenames = {str(image.get("filename") or "") for image in saved_images}
    saved_description = str(saved.get("description") or "").strip()
    saved_category = str(saved.get("category") or "").strip()
    saved_keywords = _split_keywords(str(saved.get("keywords") or ""))
    if pair.image.name not in filenames or not _values_match(
        saved_description,
        saved_category,
        saved_keywords,
        expected_description,
        expected_categories,
        expected_keywords,
    ):
        raise RuntimeError("server-side metadata read-back did not match the sidecar")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit and repair incomplete Tuchong drafts by exact filename"
    )
    parser.add_argument("path", type=Path, help="image file or directory tree")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="save repairs; default is a read-only audit",
    )
    parser.add_argument(
        "--system-chrome",
        action="store_true",
        help="use installed Google Chrome for the saved Tuchong session",
    )
    args = parser.parse_args()

    target = args.path.expanduser().resolve()
    if not target.exists():
        raise SystemExit(f"path does not exist: {target}")
    local = _local_pairs(target)
    if not local:
        raise SystemExit("no exact image/metadata pairs found")
    print(f"Local metadata inventory: {len(local)} image(s)", flush=True)

    with sync_playwright() as pw:
        context = get_context(
            "tuchong", pw, prefer_system_chrome=args.system_chrome
        )
        try:
            ensure_login(context)
            page = context.new_page()
            first_url, first_payload = _open_draft_index(page)
            query = parse_qs(urlparse(first_url).query)
            xsrf_token = query.get("xsrfToken", [""])[0]
            if not xsrf_token:
                raise RuntimeError("Tuchong XSRF token was not observed")
            groups = _list_groups(context, first_url, first_payload)
            assets = _inventory_assets(context, groups, xsrf_token, set(local))
            incomplete = sorted(
                (asset for asset in assets.values() if asset.missing_fields),
                key=lambda asset: asset.filename,
            )
            print(
                f"Matched drafts: {len(assets)}; incomplete metadata: {len(incomplete)}",
                flush=True,
            )
            for asset in incomplete:
                print(
                    f"  {asset.filename} | group {asset.group_id} | "
                    f"missing {', '.join(asset.missing_fields)}",
                    flush=True,
                )

            if not args.execute:
                print("Preview only; no drafts were changed. Add --execute to repair.")
                return

            repaired = []
            failed = []
            for index, asset in enumerate(incomplete, start=1):
                print(
                    f"[{index}/{len(incomplete)}] repairing {asset.filename} "
                    f"(group {asset.group_id})",
                    flush=True,
                )
                try:
                    _repair_one(page, context, asset, local[asset.filename], xsrf_token)
                    repaired.append(asset.filename)
                    print(f"  verified {asset.filename}", flush=True)
                except Exception as error:
                    failed.append((asset.filename, str(error)))
                    print(f"  [fail] {asset.filename}: {error}", flush=True)

            print(
                f"Repair summary: {len(repaired)} verified, {len(failed)} failed",
                flush=True,
            )
            for filename, error in failed:
                print(f"  [fail] {filename}: {error}", flush=True)
            if failed:
                raise SystemExit(1)
        finally:
            context.close()


if __name__ == "__main__":
    main()
