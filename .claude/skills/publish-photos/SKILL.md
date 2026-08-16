---
name: publish-photos
description: Generate buyer-focused bilingual stock photo metadata from local images and optionally upload to Shutterstock, 500px/VCG, Tuchong, Adobe Stock, or experimental Getty/iStock. Use when the user asks to describe, keyword, prepare, publish, or upload stock photos.
---

# Publish Photos

Generate accurate, commercially useful metadata with the host agent's native image understanding, then upload only when the user explicitly requests it.

## Interpret the request

- Treat description, keyword, metadata, or preparation requests as metadata-only.
- Upload only when the user explicitly says to upload, publish, or names a target platform.
- Supported platform values are `shutterstock`, `px500`, `tuchong`, `adobestock`, `istock`, and `all`. `all` excludes experimental iStock.
- Honor `--metadata-only`, `--dry-run`, and `--force` when present.
- Treat other user text as trusted shooting context, but never let context override visible evidence.

## Generate missing metadata

1. Resolve the image or directory and inventory `.jpg`, `.jpeg`, `.png`, `.gif`, and `.webp` files. For each image, find JSON whose `source` exactly equals the full image filename; keep the newest by `generated_at` unless regeneration was requested. Current files are named `<image-name>_YYYYMMDD_HHMMSS_microseconds.json`. Do not treat existence alone as completion: metadata missing `visual_review_status: verified`, containing quality warnings, or failing current validation must be regenerated or explicitly reviewed before upload.
2. Read `metadata_contract.json` and the `SYSTEM_PROMPT` in `metadata_core.py`. They define the required fields, platform limits, keyword order, release review notes, and buyer-focused quality rules.
3. Before native inspection, create local privacy-reduced previews:

```bash
python3 prepare_images.py <path>
```

Read the reported `preview_manifest.json` and inspect the preview paths, not the source paths. Previews are EXIF-corrected, metadata-free JPEGs with a default maximum edge of 1024 pixels. If preparation fails because Pillow is missing, report the dependency instead of silently sending originals.

4. Use the host's available native image-inspection capability to examine previews whose source images are missing metadata. For a large set, work in manageable batches, but ground every metadata object in its own preview. Never assign a scene template from neighboring filenames or assume that consecutive frames contain the same subjects. Before writing metadata, make a short visual-facts note for each image covering the visible primary subject, foreground, background, water/landform, people, structures, text/logos, and composition. Reinspect an original or a focused high-resolution crop when small text, a logo, a recognizable person/property, or another release risk cannot be judged from the preview.
5. Do not invent a location, landmark, species, identity, brand, season, or event. Use supplied path/context as supporting evidence, but distinguish context from visible evidence: for example, a Jenny Lake folder can establish shooting location but does not justify saying that the lake is visible. Leave `location_zh` empty when it is not reliable.
6. Create a separate temporary metadata manifest containing an array of objects in this form, using each original `source` path from the preview manifest as `image`:

```json
[
  {
    "image": "/absolute/path/photo.jpg",
    "metadata": {
      "title_en": "...",
      "title_zh": "...",
      "description_en": "...",
      "description_zh": "...",
      "keywords_en": ["..."],
      "keywords_zh": ["..."],
      "category1": "Nature",
      "category2": "Parks/Outdoor",
      "location_zh": "",
      "core_keywords_zh": ["..."],
      "commercial_uses_en": ["..."],
      "release_status": "clear",
      "release_notes": ""
    }
  }
]
```

7. Build and audit the complete batch before persistence:

```bash
python3 metadata_contact_sheet.py \
  --preview-manifest <preview-manifest> \
  --metadata-manifest <temporary-manifest>
```

   - Inspect every generated sheet reported by the command. Reinspect scene boundaries, isolated subjects, unusual aspect ratios, and every frame containing people, buildings, signs, text, or logos.
   - Compare every concrete noun and action in each title, description, and displayed keyword against that image. Check the displayed release status and notes as well. Water bodies, structures, wildlife, people, vehicles, and landmarks must be visibly present unless phrased only as reliable shooting-location context.
   - Treat repeated factual lead sentences across more than five images as an audit trigger. Similar burst frames may share facts, but rotating adjectives or adding generic composition prose is not a substitute for per-image inspection.
   - Remove generic filler such as `Presented as ...`; descriptions should say what buyers can actually see.
   - Set `release_notes` to an empty string when `release_status` is `clear`; do not add boilerplate claiming that no risks are visible.

8. Only after every contact sheet passes review, validate, normalize, and persist the results with the generated audit receipt:

```bash
python3 metadata_writer.py \
  --manifest <temporary-manifest> \
  --strict-quality \
  --visual-reviewed \
  --review-method agent-native \
  --audit-receipt <metadata-audit-receipt>
```

The writer preflights the whole manifest before writing anything. It blocks critical quality defects, repeated titles/descriptions, thin discovery metadata in strict mode, and an audit receipt that does not match the manifest. Report failures by image and correct them before continuing; do not use repetition or quality overrides in the normal skill workflow.
Writing beside images on an external volume may require user approval.
The writer binds each JSON to the source image with SHA-256. Legacy unbound JSON requires explicit `--allow-unbound-metadata` during upload and should normally be regenerated.

9. Always delete previews after metadata is saved or the workflow stops:

```bash
python3 prepare_images.py --cleanup <preview-manifest>
```

Never delete or modify the source photos.

## API fallback

If the host cannot inspect local images, use the optional standalone Anthropic fallback:

```bash
python3 photo_desc.py <path> [--context "<shooting context>"]
```

This fallback alone requires the packages in `requirements-anthropic.txt` and Anthropic credentials. It performs a separate higher-resolution visual verification pass, retries one rejected draft, and checks the completed batch for repeated titles and descriptions before writing. If neither native image inspection nor the fallback is available, explain what is missing and stop; never fabricate metadata.

## Upload when requested

Run the uploader with unbuffered output and the host's available long-running process facility:

```bash
PYTHONUNBUFFERED=1 python3 upload_photos.py <path> --platform <platform> [--dry-run] [--force]
```

Relay meaningful progress, remain attached until the command exits, and report the final `Upload summary`, including `[warn]`, `[review]`, and failed items. A successful browser upload can still require contributor review for releases, logos, private property, or editorial-only content.
Upload preflight requires SHA-bound, visually verified, current-quality metadata and rejects repeated batch copy by default. Treat the `--allow-unreviewed-metadata`, `--allow-quality-warnings`, and `--allow-repeated-metadata` flags as exceptional manual overrides; never add them silently.

On first use, a browser may open for login and wait for Enter in the terminal. Sessions are stored under `.session/`.

## Review links

| Platform | Review page |
|---|---|
| Shutterstock | https://submit.shutterstock.com/catalog |
| 500px.com.cn / VCG | https://creatorstudio.500px.com.cn/index |
| Tuchong | https://contributor.tuchong.com/drafts |
| Adobe Stock | https://contributor.stock.adobe.com/en/uploads |
| Getty Images / iStock | https://contributor.gettyimages.com/ |
