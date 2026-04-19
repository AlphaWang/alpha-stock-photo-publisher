# publish-photos

End-to-end stock photo pipeline: generate bilingual metadata with Claude vision, then upload to Shutterstock, 500px.com.cn, and/or 图虫创意.

## Usage

```
/publish-photos <path> [--platform shutterstock|px500|tuchong|all] [--dry-run]
```

- `<path>` — image file or directory of images
- `--platform` — target platform (default: `all`); `tuchong` = 图虫创意
- `--dry-run` — preview what would run without executing

## What this skill does

### Step 1 — Generate metadata (if needed)

Check whether each image in `<path>` already has a matching `*_????????_??????.json` file alongside it.

- **Missing JSON → run photo_desc.py first:**
  ```bash
  python3 photo_desc.py <path> [--context "<context>"]
  ```
  If the user provided any descriptive text beyond the path and flags (e.g. location, scene, shooting conditions), pass it as `--context`.
- **All JSONs present → skip to Step 2**

### Step 2 — Upload

```bash
python3 upload_photos.py <path> --platform <platform> [--dry-run]
```

### Step 3 — Report

After the script finishes, report:
- How many images succeeded / failed
- Any error messages for failed images
- Remind the user to check the browser if a login prompt appears

## Login (first run)

On the first run for each platform, a browser window opens. Tell the user:

> "A browser window has opened. Please log in to [platform] and press Enter in the terminal when done."

The session is saved to `.session/` and reused automatically on future runs.

## Examples

```
/publish-photos ~/Photo/2026-04-15/4
/publish-photos ~/Photo/2026-04-15/4 --platform shutterstock
/publish-photos ~/Photo/2026-04-15/4 --dry-run
/publish-photos ~/Photo/2026-04-15/4/DSC00012.jpg --platform shutterstock
```

With context:
```
/publish-photos ~/Photo/2026-04-15/4 --platform shutterstock
Shot at San Simeon along California Highway 1, featuring elephant seals, a lighthouse, and sunset coastal scenery
```
