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

1. Resolve the image or directory and inventory `.jpg`, `.jpeg`, `.png`, `.gif`, and `.webp` files. For each image, find JSON whose `source` exactly equals the full image filename; keep the newest by `generated_at` unless regeneration was requested. Current files are named `<image-name>_YYYYMMDD_HHMMSS_microseconds.json`.
2. Read `metadata_contract.json` and the `SYSTEM_PROMPT` in `metadata_core.py`. They define the required fields, platform limits, keyword order, release review notes, and buyer-focused quality rules.
3. Before native inspection, create local privacy-reduced previews:

```bash
python3 prepare_images.py <path>
```

Read the reported `preview_manifest.json` and inspect the preview paths, not the source paths. Previews are EXIF-corrected, metadata-free JPEGs with a default maximum edge of 1024 pixels. If preparation fails because Pillow is missing, report the dependency instead of silently sending originals.

4. Use the host's available native image-inspection capability to examine previews whose source images are missing metadata. For a large set, work in manageable batches, but create a distinct metadata object for every source image. Reinspect an original or a focused high-resolution crop only when small text, a logo, a recognizable person/property, or another release risk cannot be judged from the preview.
5. Do not invent a location, landmark, species, identity, brand, season, or event. Use supplied path/context as supporting evidence. Leave `location_zh` empty when it is not reliable.
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

7. Validate, normalize, and persist the results with:

```bash
python3 metadata_writer.py --manifest <temporary-manifest>
```

Writing beside images on an external volume may require user approval. Report validation failures by image and correct them before continuing.
The writer binds each JSON to the source image with SHA-256. Legacy unbound JSON requires explicit `--allow-unbound-metadata` during upload and should normally be regenerated.

8. Always delete previews after metadata is saved or the workflow stops:

```bash
python3 prepare_images.py --cleanup <preview-manifest>
```

Never delete or modify the source photos.

## API fallback

If the host cannot inspect local images, use the optional standalone Anthropic fallback:

```bash
python3 photo_desc.py <path> [--context "<shooting context>"]
```

This fallback alone requires the packages in `requirements-anthropic.txt` and Anthropic credentials. If neither native image inspection nor the fallback is available, explain what is missing and stop; never fabricate metadata.

## Upload when requested

Run the uploader with unbuffered output and the host's available long-running process facility:

```bash
PYTHONUNBUFFERED=1 python3 upload_photos.py <path> --platform <platform> [--dry-run] [--force]
```

Relay meaningful progress, remain attached until the command exits, and report the final `Upload summary`, including `[warn]`, `[review]`, and failed items. A successful browser upload can still require contributor review for releases, logos, private property, or editorial-only content.

On first use, a browser may open for login and wait for Enter in the terminal. Sessions are stored under `.session/`.

## Review links

| Platform | Review page |
|---|---|
| Shutterstock | https://submit.shutterstock.com/catalog |
| 500px.com.cn / VCG | https://creatorstudio.500px.com.cn/index |
| Tuchong | https://contributor.tuchong.com/drafts |
| Adobe Stock | https://contributor.stock.adobe.com/en/uploads |
| Getty Images / iStock | https://contributor.gettyimages.com/ |
