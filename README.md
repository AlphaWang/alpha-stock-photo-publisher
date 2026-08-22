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

1. Create 1536px overviews plus four overlapping detail crops
2. Record machine-readable visual facts before generating buyer metadata
3. Build immutable one-image review sheets and record independent per-image decisions
4. Issue a v3 audit receipt, then write SHA-bound, fact-bound metadata
5. Curate near-identical bursts and upload only when explicitly requested
6. Repair platform returns with evidence-bound Editorial metadata when supported

Existing JSON is reused only when it is SHA-bound, visually verified, and passes
the current quality checks. Merely having a JSON file no longer counts as a
completed metadata workflow.

The copies under `.agents/skills/` and `.claude/skills/` are intentionally identical. Their instructions avoid host-specific tool names, so each agent uses its own image and process tools.

### Standalone Anthropic API fallback

Use this when the current agent cannot inspect local images, or when running outside an agent host:

```bash
python3 photo_desc.py /path/to/dir --allow-anthropic-api
python3 photo_desc.py /path/to/dir --allow-anthropic-api --context "SLC road trip"
```

This path requires the optional Anthropic dependencies and credentials above. It
also requires the explicit `--allow-anthropic-api` acknowledgement; configured
credentials or a Claude gateway do not authorize an agent-native workflow to use
this path. Batch size, speed, or convenience are not provider-routing signals. It
uses a 1024px generation preview followed by a context-isolated 1536px visual
verification pass with overlapping crops for small text, logos, and people. Set
`ANTHROPIC_VERIFIER_MODEL` to use a separately configured verifier model. A rejected draft is regenerated once, and the completed batch
is checked against a full visual-facts object and for repeated titles and
descriptions before records are written. Metadata is not written when the second
verification still fails. This
path is not used by the normal Codex or Claude native workflow.

### Prepare previews manually

```bash
python3 prepare_images.py /path/to/dir --max-edge 1536 --detail-crops
python3 prepare_images.py --cleanup /tmp/stock-photo-previews-abc123/preview_manifest.json
```

The command prints the exact manifest path. Pass that path back to `--cleanup`; cleanup refuses directories that were not created and marked by this tool.

### Audit and write native-agent metadata manually

After creating a temporary manifest containing `visual_facts` that satisfies
`visual_facts_contract.json`, build a review pack that binds each overview, detail
crop, facts object, metadata object, and review sheet by SHA-256:

```bash
python3 metadata_contact_sheet.py \
  --preview-manifest /tmp/stock-photo-previews-abc123/preview_manifest.json \
  --metadata-manifest /tmp/proposed-metadata.json
```

The command produces `metadata_review_pack.json` and a pending
`metadata_review_decisions.json`; it does not claim that review happened. Inspect
every sheet in a fresh pass, then mark each image's facts, metadata, release/IP,
and overall verdict as `pass`, record the overview/detail evidence, and finalize:

```bash
python3 metadata_review_finalize.py \
  --review-pack /tmp/stock-photo-previews-abc123/metadata_review_pack.json \
  --decisions /tmp/stock-photo-previews-abc123/metadata_review_decisions.json
```

The finalizer refuses missing, failed, incomplete, or changed review artifacts.
Use the resulting v3 receipt to write verified metadata:

```bash
python3 metadata_writer.py \
  --manifest /tmp/proposed-metadata.json \
  --strict-quality \
  --visual-reviewed \
  --review-method agent-native \
  --audit-receipt /tmp/stock-photo-previews-abc123/metadata_audit_receipt.json
```

The writer validates the entire manifest before writing any file. Incomplete facts,
facts/metadata contradictions, weak technical selections, more than three selected
frames per burst, generic filler, irrelevant first keywords, word-stem spam,
unsupported locations, release contradictions, invalid categories, and changed or
incomplete audit artifacts block the batch. Exact copy is permitted only for a
small, explicitly ranked same-scene burst, avoiding artificial adjective rotation.
Counts below 15 English or 8 Chinese keywords are advisory only; never pad metadata
with weak terms to silence an advisory.

### Run a labeled metadata benchmark

Use `metadata_benchmark.py` to compare a generated manifest against human labels:

```bash
python3 metadata_benchmark.py \
  --expected /path/to/golden-labels.json \
  --actual /path/to/proposed-metadata.json
```

Each expected item uses the same `image` value and an `expected` object containing
any of `required_terms_en`, `forbidden_terms_en`, `required_terms_zh`,
`forbidden_terms_zh`, `first10_terms_en`, `category1`, and the structured
release/IP fields. `expected.visual_facts` additionally runs deterministic visual
grounding checks. The command reports per-image failures and an aggregate pass
rate, so prompt or model changes can be measured on real labeled photos.

### Upload manually

```bash
python3 upload_photos.py /path/to/dir --platform shutterstock
python3 upload_photos.py /path/to/dir --platform shutterstock --force
python3 upload_photos.py /path/to/dir --platform shutterstock --repair-corrections
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
Unreviewed metadata, factual/ordering/spam defects, commercial release risks, and
repeated batch copy are blocked by default. Keyword-count advisories do not block
upload. `--allow-unreviewed-metadata` and `--allow-repeated-metadata` are explicit
manual overrides and should not be used by the normal skill workflow.

### Repair Shutterstock corrections

`--repair-corrections` handles existing Shutterstock items marked `Correction
needed` without uploading the image again. It matches the exact filename on the
returned-items page and only automates the platform's `Eligible for Editorial
Use` correction. Other review reasons remain manual review items.

Editorial repair metadata must be SHA-bound and visually verified, with
`commercial_eligibility: "editorial_only"`, complete caption fields, and explicit
date/location provenance:

```json
{
  "editorial_date": "2026-06-27",
  "editorial_date_source": "exif",
  "editorial_location_en": "Grand Teton National Park, Wyoming, USA",
  "location_source": "context",
  "location_confidence": "high",
  "editorial_caption_en": "Grand Teton National Park, Wyoming, USA - 27 June 2026: Kayakers cross a mountain lake below the Teton Range."
}
```

The repair workflow replaces stale keywords rather than appending to them,
switches Shutterstock Usage to Editorial, uses the correction-specific Submit
action, and records a submitted status only after the exact card shows
`Resubmitted`. It refuses missing cards,
unsupported correction reasons, uncertain dates or locations, incomplete
Editorial fields, and unresolved visual-review failures.

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
  "visual_facts_sha256": "...",
  "visual_facts": {
    "schema_version": 1,
    "primary_subjects_en": ["mountain cabin"],
    "primary_subjects_zh": ["山间木屋"],
    "required_terms_en": [],
    "required_terms_zh": [],
    "forbidden_claims_en": ["barn", "lake", "trail"],
    "forbidden_claims_zh": ["谷仓", "湖泊", "步道"],
    "water_visible": "no",
    "trail_visible": "no",
    "people_visible": "no",
    "recognizable_people_visible": "no",
    "structures_visible": "yes",
    "vehicles_visible": "no",
    "animals_visible": "no",
    "reflection_visible": "no",
    "text_visible": "no",
    "logo_or_trademark_visible": "no",
    "copyrighted_content_visible": "no",
    "private_property_visible": "unknown",
    "copy_space_visible": "yes",
    "scene_signature": "single-cabin-meadow-mountain-background",
    "burst_group_id": "",
    "burst_rank": 0,
    "technical_quality": "pass",
    "commercial_potential": "medium",
    "commercial_strengths_en": ["clear rustic travel concept"],
    "selection_status": "selected",
    "uncertain_details": ["property ownership cannot be determined visually"]
  },
  "title_en": "...",
  "title_zh": "...",
  "description_en": "...",
  "description_zh": "...",
  "keywords_en": ["...", "..."],
  "keywords_zh": ["...", "..."],
  "category1": "Nature",
  "category2": "Parks/Outdoor",
  "platform_categories": {
    "shutterstock": ["Nature", "Parks/Outdoor"],
    "adobestock": "Landscapes",
    "tuchong": ["自然风光"],
    "istock": "Nature"
  },
  "location_en": "",
  "location_zh": "",
  "location_source": "unknown",
  "location_confidence": "unknown",
  "core_keywords_zh": ["..."],
  "commercial_uses_en": ["travel marketing"],
  "editorial_caption_en": "",
  "editorial_date": "",
  "editorial_date_source": "unknown",
  "editorial_location_en": "",
  "model_release_status": "not_required",
  "property_release_status": "unknown",
  "logo_trademark_status": "none",
  "copyrighted_content_status": "none",
  "commercial_eligibility": "review",
  "release_status": "unknown",
  "release_notes": "Property release status requires manual review."
}
```

If you run metadata generation on the same image twice, the newest JSON is used
automatically. Upload verifies the exact filename, SHA-256, metadata contract,
visual-facts digest and contradictions, critical quality rules, commercial
eligibility, batch uniqueness, and visual-review status before opening a browser.

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
