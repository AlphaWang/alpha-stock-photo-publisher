# alpha-photo-desc

Bilingual stock photo metadata generator and uploader for Shutterstock and 500px.com.cn.

Given a photo (or a directory of photos), it uses the Claude vision API to generate English and Chinese titles, descriptions, keywords, and categories — then automates the upload via a real browser.

## Prerequisites

**Python packages**

```bash
pip install anthropic pillow playwright
python -m playwright install chromium
```

**Claude API access**

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

On the eBay internal network, the token is fetched automatically via `npx @ebay/claude-code-token@latest`.

## Usage

### With Claude Code (recommended)

Open this project in [Claude Code](https://claude.ai/code) and run:

```
/publish-photos /path/to/dir
/publish-photos /path/to/dir --platform shutterstock
/publish-photos /path/to/dir --dry-run
```

Claude handles the full pipeline automatically:
1. Generate metadata (skips images that already have a JSON)
2. Upload to the target platform(s)
3. Report results and guide you through any login prompts

### Without Claude Code

Run the two scripts manually:

```bash
# Step 1 — generate metadata
python3 photo_desc.py /path/to/dir

# Step 2 — upload
python3 upload_photos.py /path/to/dir --platform shutterstock
```

## First run (browser login)

On the first run for each platform, a browser window opens. Log in with your account (including 2FA), then press Enter in the terminal. The session is saved to `.session/` and reused automatically — no repeated logins needed.

## Output format

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

If you run metadata generation on the same image twice, the newest JSON is used automatically.

## Platform limits (enforced automatically)

| Field | Shutterstock | 500px.com.cn |
|---|---|---|
| Description | ≤ 2048 chars | ≤ 50 chars |
| Keywords | exactly 50 | exactly 35 |
| Categories | 1 required + 1 optional | — |

## Supported image formats

`.jpg` `.jpeg` `.png` `.gif` `.webp`

## Project structure

```
photo_desc.py          # metadata generator (Claude vision API)
upload_photos.py       # upload CLI
upload/
  browser.py           # shared: persistent browser context, login helper
  shutterstock.py      # Shutterstock upload automation
  px500.py             # 500px.com.cn upload automation
debug_selectors.py     # interactive DOM inspector for debugging selectors
.claude/skills/
  publish-photos/
    SKILL.md           # /publish-photos Claude Code skill
.session/              # browser sessions (git-ignored)
```
