# alpha-stock-photo-publisher

Bilingual stock photo metadata generator and publisher for Shutterstock, 500px.com.cn, Tuchong, and Adobe Stock.

Given a photo (or a directory of photos), the project can use Codex or Claude's native image understanding to generate English and Chinese titles, descriptions, keywords, and categories, then automate uploads through a real browser. A standalone Anthropic API generator remains available as an optional fallback.

## Supported platforms

| Platform | URL | Status |
|---|---|---|
| Shutterstock | https://www.shutterstock.com | ✅ Supported |
| 500px.com.cn / 视觉中国 (VCG) | https://500px.com.cn · https://www.vcg.com | ✅ Supported |
| 图虫创意 (Tuchong) | https://tuchong.com | ✅ Supported |
| Getty Images / iStock | https://contributor.gettyimages.com | ⚠️ Implementing |
| Adobe Stock | https://stock.adobe.com | ✅ Supported |
| Alamy | https://www.alamy.com | — |
| Dreamstime | https://www.dreamstime.com | — |
| 全景图片 (Quanjing) | https://www.quanjing.com | — |

## Prerequisites

Python 3.9 or newer is supported.

**Agent-native metadata generation**

Open the repository in Codex or Claude Code. No AI SDK or separate API key is required when the host can inspect local images. Install the local preview and upload dependencies:

```bash
pip install -r requirements.txt
```

The skill sends temporary previews to the host model instead of original files by default. Previews are EXIF-corrected JPEGs with metadata removed and a maximum edge of 1024 pixels. They are deleted after metadata generation; source photos are never modified.

**Browser upload**

Run `python -m playwright install chromium` to provide the fallback browser. The uploader prefers Google Chrome when installed and otherwise uses Playwright Chromium.

**Optional standalone Anthropic fallback**

Install these only when running `photo_desc.py` directly:

```bash
pip install -r requirements-anthropic.txt
export ANTHROPIC_API_KEY=sk-ant-...
```

## Usage

### With Codex

Open this project in Codex and invoke the repository skill or ask naturally:

```text
$publish-photos /path/to/dir --metadata-only
Generate stock photo descriptions for /path/to/dir
$publish-photos /path/to/dir --platform shutterstock
```

### With Claude Code

Open this project in [Claude Code](https://claude.ai/code) and run:

```text
/publish-photos /path/to/dir
/publish-photos /path/to/dir --metadata-only
/publish-photos /path/to/dir --platform shutterstock
/publish-photos /path/to/dir --platform px500
/publish-photos /path/to/dir --platform tuchong
/publish-photos /path/to/dir --platform adobestock
/publish-photos /path/to/dir --dry-run
```

Both agent skills follow the same workflow:

1. Create temporary 1024px previews and generate per-image visual facts and metadata
2. Build filename-and-metadata contact sheets and inspect every proposed description
3. Run strict batch validation, then write SHA-bound metadata marked as visually verified
4. Remove the previews and audit sheets
5. Upload only when explicitly requested, with another quality and review-status preflight

Existing JSON is reused only when it is SHA-bound, visually verified, and passes
the current quality checks. Merely having a JSON file no longer counts as a
completed metadata workflow.

The copies under `.agents/skills/` and `.claude/skills/` are intentionally identical. Their instructions avoid host-specific tool names, so each agent uses its own image and process tools.

### Standalone Anthropic API fallback

Use this when the current agent cannot inspect local images, or when running outside an agent host:

```bash
python3 photo_desc.py /path/to/dir
python3 photo_desc.py /path/to/dir --context "SLC road trip"
```

This path requires the optional Anthropic dependencies and credentials above. It
uses a 1024px generation preview followed by an independent 1536px visual
verification pass. A rejected draft is regenerated once, and the completed batch
is checked for repeated titles and descriptions before any repeated records are
written. Metadata is not written when the second verification still fails. This
path is not used by the normal Codex or Claude native workflow.

### Prepare previews manually

```bash
python3 prepare_images.py /path/to/dir
python3 prepare_images.py --cleanup /tmp/stock-photo-previews-abc123/preview_manifest.json
```

The command prints the exact manifest path. Pass that path back to `--cleanup`; cleanup refuses directories that were not created and marked by this tool.

### Audit and write native-agent metadata manually

After creating a temporary metadata manifest, build contact sheets that bind each
preview to its proposed title, description, keywords, and release assessment:

```bash
python3 metadata_contact_sheet.py \
  --preview-manifest /tmp/stock-photo-previews-abc123/preview_manifest.json \
  --metadata-manifest /tmp/proposed-metadata.json
```

Inspect every reported sheet, including its displayed English keywords and
release status/notes, then use its receipt to write verified metadata:

```bash
python3 metadata_writer.py \
  --manifest /tmp/proposed-metadata.json \
  --strict-quality \
  --visual-reviewed \
  --review-method agent-native \
  --audit-receipt /tmp/stock-photo-previews-abc123/metadata_audit_receipt.json
```

The writer validates the entire manifest before writing any file. Repeated titles
or descriptions, repeated factual leads, generic filler, release-status
contradictions, thin strict-mode keyword sets, and changed or mismatched audit
artifacts block the batch.

### Upload manually

```bash
python3 upload_photos.py /path/to/dir --platform shutterstock
python3 upload_photos.py /path/to/dir --platform shutterstock --force
```

`--platform all` runs the stable platforms. Getty/iStock remains experimental and
must be selected explicitly with `--platform istock`.

Completed uploads are tracked by image content hash in
`.stock_upload_history.json` beside the photos. Subsequent runs skip completed
images for that platform unless `--force` is supplied.
History distinguishes `uploaded`, `draft_saved`, and `submitted`. An `uploaded`
result is recorded to prevent duplicate transfer but returns a nonzero exit status
until metadata is confirmed saved. Legacy JSON
without a source hash is blocked by default; use `--allow-unbound-metadata` only
for trusted older metadata that cannot be regenerated.
Unreviewed metadata, quality warnings, and repeated batch copy are also blocked by
default. `--allow-unreviewed-metadata`, `--allow-quality-warnings`, and
`--allow-repeated-metadata` are explicit manual overrides and should not be used
by the normal skill workflow.

## First run (browser login)

On the first run for each platform, a browser window opens. Log in with your account (including 2FA), then press Enter in the terminal. The session is saved to `.session/` and reused automatically — no repeated logins needed.

## Output format

Each image produces a timestamped JSON file alongside it, e.g. `DSC00012.jpg_20260418_132943_123456.json`:

```json
{
  "source": "DSC00012.jpg",
  "source_sha256": "...",
  "source_size": 12345678,
  "generated_at": "2026-04-18 13:29:43",
  "visual_review_status": "verified",
  "visual_review_method": "agent-native",
  "visual_reviewed_at": "2026-04-18 13:31:02",
  "quality_warnings": [],
  "title_en": "...",
  "title_zh": "...",
  "description_en": "...",
  "description_zh": "...",
  "keywords_en": ["...", "..."],
  "keywords_zh": ["...", "..."],
  "category1": "Nature",
  "category2": "Parks/Outdoor",
  "location_zh": "",
  "core_keywords_zh": ["..."],
  "commercial_uses_en": ["travel marketing"],
  "release_status": "clear",
  "release_notes": ""
}
```

If you run metadata generation on the same image twice, the newest JSON is used
automatically. Upload verifies the exact filename, SHA-256, metadata contract,
quality warnings, batch uniqueness, and visual-review status before opening a
browser.

## Platform limits (enforced automatically)

| Field | Shutterstock | 500px.com.cn | Adobe Stock | Getty / iStock |
|---|---|---|---|---|
| Title / Description | ≤ 2048 chars | ≤ 50 chars | title ≤ 70 chars | title ≤ 200 chars |
| Keywords | up to 50, ordered by relevance | up to 35 | up to 49 (first 10 strongest) | ≤ 50 |
| Categories | 1 required + 1 optional | — | 1 required (mapped taxonomy) | 1 required |

## Tuchong draft cleanup

Use `cleanup_tuchong_drafts.py` to bulk-delete draft folders left behind from failed or unwanted uploads.

**Preview (no deletions, lists up to 50 by default)**

```bash
python3 cleanup_tuchong_drafts.py
python3 cleanup_tuchong_drafts.py --preview-limit 100
```

**Actually delete**

```bash
# Delete all draft folders
python3 cleanup_tuchong_drafts.py --execute --all

# Delete only the first 20 draft folders
python3 cleanup_tuchong_drafts.py --execute --limit 20

# Skip the confirmation prompt (for scripting)
python3 cleanup_tuchong_drafts.py --execute --all --yes
```

The script reuses the `.session/tuchong` browser session. On the first run it will open a browser window for login, the same as the upload flow.

## Supported image formats

`.jpg` `.jpeg` `.png` `.gif` `.webp`

## Project structure

```
metadata_contract.json # shared agent output contract
metadata_core.py       # shared prompt, limits, validation, and persistence
metadata_writer.py     # standard-library writer for native agent output
metadata_contact_sheet.py # auditable preview and metadata contact sheets
prepare_images.py      # temporary 1024px, metadata-free preview generator
photo_desc.py          # optional standalone Anthropic API fallback
requirements.txt       # preview and browser upload dependencies
requirements-anthropic.txt  # standalone Anthropic fallback dependencies
upload_photos.py       # upload CLI
upload/
  browser.py           # shared: persistent browser context, login helper
  confirmation.py      # post-action success confirmation helper
  status.py            # explicit upload lifecycle states
  shutterstock.py      # Shutterstock upload automation
  px500.py             # 500px.com.cn upload automation
  tuchong.py           # Tuchong upload automation
  adobestock.py        # Adobe Stock upload automation
  istock.py            # experimental Getty/iStock preparation (no auto-submit)
cleanup_tuchong_drafts.py  # bulk-delete Tuchong draft folders
debug_selectors.py         # interactive DOM inspector for debugging selectors
.agents/skills/
  publish-photos/
    SKILL.md           # Codex / Agent Skills entry
.claude/skills/
  publish-photos/
    SKILL.md           # Claude Code skill (same portable workflow)
.session/              # browser sessions (git-ignored)
```
