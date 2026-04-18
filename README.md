# alpha-photo-desc

Bilingual stock photo metadata generator and uploader for Shutterstock and 500px.com.cn.

Given a photo (or a directory of photos), it uses the Claude vision API to generate English and Chinese titles, descriptions, keywords, and categories — then automates the upload via a real browser.

## Workflow

```
photo_desc.py  →  JSON metadata files
upload_photos.py  →  browser automation (Playwright)
```

## Prerequisites

**Python packages**

```bash
pip install anthropic pillow playwright
python -m playwright install chromium
```

**Claude API access**

Set your API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Or if you are on the eBay internal network, the token is fetched automatically via `npx @ebay/claude-code-token@latest`.

## Step 1 — Generate metadata

```bash
# Single image
python3 photo_desc.py /path/to/photo.jpg

# Whole directory (parallel, 3 workers by default)
python3 photo_desc.py /path/to/dir

# Custom output directory
python3 photo_desc.py /path/to/dir --output /path/to/output
```

Each image produces a timestamped JSON file alongside it, e.g. `DSC00012_20260418_132943.json`:

```json
{
  "source": "DSC00012.jpg",
  "generated_at": "2026-04-18 13:29:43",
  "title_en": "...",
  "title_zh": "...",
  "description_en": "...",
  "description_zh": "...",
  "keywords_en": ["...", "..."],
  "keywords_zh": ["...", "..."],
  "category1": "Nature",
  "category2": "Parks/Outdoor"
}
```

If you run `photo_desc.py` on the same image twice, the newest JSON is used automatically.

## Step 2 — Upload

```bash
# Upload a single image
python3 upload_photos.py /path/to/photo.jpg --platform shutterstock

# Upload a whole directory
python3 upload_photos.py /path/to/dir --platform shutterstock

# Both platforms
python3 upload_photos.py /path/to/dir --platform all

# Preview without uploading
python3 upload_photos.py /path/to/dir --dry-run
```

**First run:** A browser window opens. Log in with your account (including 2FA if required), then press Enter in the terminal. The session is saved to `.session/` and reused on future runs — no repeated logins needed.

## Claude Code skill

If you use [Claude Code](https://claude.ai/code), a `/upload-photos` skill is included:

```
/upload-photos /path/to/dir --platform shutterstock
/upload-photos /path/to/dir --dry-run
```

Claude will run the upload script and report the result.

## Platform limits (enforced automatically)

| Field | Shutterstock | 500px.com.cn |
|---|---|---|
| Description | ≤ 2048 chars | ≤ 50 chars |
| Keywords | exactly 50 | exactly 35 |
| Categories | 1 required + 1 optional | — |

## Project structure

```
photo_desc.py          # metadata generator (Claude vision API)
upload_photos.py       # CLI entry point for uploads
upload/
  browser.py           # shared: persistent browser context, login helper
  shutterstock.py      # Shutterstock upload automation
  px500.py             # 500px.com.cn upload automation (not yet tested)
debug_selectors.py     # interactive DOM inspector for debugging selectors
.claude/skills/
  upload-photos/
    SKILL.md           # /upload-photos Claude Code skill
.session/              # browser sessions (git-ignored)
```

## Session management

Browser sessions are stored in `.session/shutterstock/` and `.session/px500/` (git-ignored). They persist across runs — you only need to log in once per platform.

If a session expires, the browser reopens automatically and prompts you to log in again.

## Supported image formats

`.jpg` `.jpeg` `.png` `.gif` `.webp`
