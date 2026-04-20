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

### Step 2 — Upload (with live progress)

Run the upload in the **background** using `run_in_background=True` on the Bash tool:

```bash
PYTHONUNBUFFERED=1 python3 upload_photos.py <path> --platform <platform> [--dry-run]
```

Then **poll for progress** using `TaskOutput(task_id=<id>, block=False, timeout=5000)`:

- Keep track of how many characters of output you've already seen (`seen` index).
- After each poll, slice `output[seen:]` to extract only new text, then advance `seen`.
- Immediately print any new lines to the user as plain text.
- Poll every ~15 seconds. Stop once the output contains `Done:` or the task finishes.
- Do a final blocking `TaskOutput(block=True)` to capture any trailing output.

### Step 3 — Report

After the task completes, report:
- How many images succeeded / failed (from the `Done: N/M succeeded` line)
- Any `[warn]` or `[fail]` error messages for failed images
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
