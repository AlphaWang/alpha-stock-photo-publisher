---
name: publish-photos
description: Generate buyer-focused bilingual stock photo metadata from local images and optionally upload to Shutterstock, 500px/VCG, Tuchong, Adobe Stock, or experimental Getty/iStock. Use when the user asks to describe, keyword, prepare, publish, or upload stock photos.
---

# Publish Photos

Generate accurate, commercially useful metadata with the host agent's native image understanding, then upload only when the user explicitly requests it.

## Keep AI inference on the active host

- Use the active host's native model for every image-understanding, metadata-generation, and visual-verification step. Codex must use Codex-native image inspection; Claude Code must use Claude-native image inspection.
- Never invoke an external or cross-provider AI SDK, gateway, CLI, or model from the agent-native workflow. Batch size, speed, convenience, available credentials, installed dependencies, or configured environment variables never justify switching providers.
- Treat `ANTHROPIC_API_KEY`, `CLAUDE_GATEWAY_URL`, and similar settings only as evidence that an optional standalone path is available, never as user consent or a routing signal.
- In the agent-native workflow, run only deterministic local preparation, review-pack, validation, and writing scripts. Do not run `photo_desc.py`; it is an explicitly authorized standalone Anthropic path, not a batch accelerator for the native workflow.

## Interpret the request

- Treat description, keyword, metadata, or preparation requests as metadata-only.
- Upload only when the user explicitly says to upload, publish, or names a target platform.
- Supported platform values are `shutterstock`, `px500`, `tuchong`, `adobestock`, `istock`, and `all`. `all` excludes experimental iStock.
- Honor `--metadata-only`, `--dry-run`, and `--force` when present.
- Treat other user text as trusted shooting context, but never let context override visible evidence.

## Generate missing metadata

1. Resolve the image or directory and inventory `.jpg`, `.jpeg`, `.png`, `.gif`, and `.webp` files. For each image, find JSON whose `source` exactly equals the full image filename; keep the newest by `generated_at` unless regeneration was requested. Current files are named `<image-name>_YYYYMMDD_HHMMSS_microseconds.json`. Do not treat existence alone as completion: metadata missing `visual_review_status: verified` or failing current factual, spam, ordering, location-evidence, release, or platform validation must be regenerated or explicitly reviewed before upload. Keyword-count advisories alone do not require padding or regeneration.
2. Read `metadata_contract.json` and the `SYSTEM_PROMPT` in `metadata_core.py`. They define the required fields, platform limits, keyword order, release review notes, and buyer-focused quality rules.
3. Before native inspection, create local privacy-reduced previews:

```bash
python3 prepare_images.py <path> --max-edge 1536 --detail-crops
```

Read the reported `preview_manifest.json` and inspect the overview plus all four overlapping `detail_previews`, not the source paths. Previews are EXIF-corrected, metadata-free JPEGs. Detail crops are mandatory for detecting small aircraft, wildlife tags/collars, distant people, text, and logos. If preparation fails because Pillow is missing, report the dependency instead of silently sending originals.

4. Use the host's available native image-inspection capability to examine previews whose source images are missing metadata. First inspect each image without using its folder name, neighboring frames, or shooting context and complete every field in `visual_facts_contract.json`. Use `yes`, `no`, or `unknown`; never turn uncertainty into `no`. Then apply supplied context only to location fields. For a large set, work in manageable batches, but ground every facts object and metadata object in that image's own overview and detail crops. Never assign a scene template from neighboring filenames or assume that consecutive frames contain the same subjects.
   - Put every primary commercial subject in `primary_subjects_en/zh`; use `required_terms_en/zh` for small but material details such as an aircraft or tracking collar, and `forbidden_claims_en/zh` for plausible misidentifications such as cabin versus barn.
   - When `text_visible` is yes, inspect detail crops and use native OCR if available. Record commercially material visible wording in required terms or put unreadable text in `uncertain_details`; never guess. Distinguish ordinary text from an actual logo/trademark.
   - Give each distinct scene a concise `scene_signature`. Assign near-identical frames a shared `burst_group_id`, rank selected frames from strongest to weakest with `burst_rank`, and keep at most three. Leave `burst_group_id` empty and use rank 0 outside a burst.
   - Persist only frames with `technical_quality: pass` and `selection_status: selected`. Assess `commercial_potential` and list concrete `commercial_strengths_en`; do not select a weak frame merely to preserve a sequence.
5. Do not invent a location, landmark, species, identity, brand, season, or event. Use supplied path/context as supporting evidence, but distinguish context from visible evidence: for example, a Jenny Lake folder can establish shooting location but does not justify saying that the lake is visible. Leave `location_en` and `location_zh` empty, with unknown source/confidence, when location is not reliable.
6. Create a separate temporary metadata manifest containing an array of objects in this form, using each original `source` path from the preview manifest as `image`:

```json
[
  {
    "image": "/absolute/path/photo.jpg",
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
      "commercial_strengths_en": ["clear rustic travel concept", "usable sky copy space"],
      "selection_status": "selected",
      "uncertain_details": ["property ownership cannot be determined visually"]
    },
    "metadata": {
      "title_en": "...",
      "title_zh": "...",
      "description_en": "...",
      "description_zh": "...",
      "keywords_en": ["..."],
      "keywords_zh": ["..."],
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
      "commercial_uses_en": ["..."],
      "model_release_status": "not_required",
      "property_release_status": "unknown",
      "logo_trademark_status": "none",
      "copyrighted_content_status": "none",
      "commercial_eligibility": "review",
      "release_status": "unknown",
      "release_notes": "Property release status requires manual review."
    }
  }
]
```

7. Build the immutable review pack before persistence:

```bash
python3 metadata_contact_sheet.py \
  --preview-manifest <preview-manifest> \
  --metadata-manifest <temporary-manifest>
```

   This command creates `metadata_review_pack.json` and a non-passing `metadata_review_decisions.json` template; it does not create an audit receipt.
   - Start a fresh, context-isolated verification pass and inspect every generated sheet, including overview and detail crops. Reinspect scene boundaries, isolated subjects, unusual aspect ratios, and every frame containing people, buildings, signs, text, or logos.
   - Each sheet contains one image, its structured visual facts, and every English/Chinese title, description, keyword, category, location-evidence, commercial-use, and release/IP field. Compare every concrete noun and action against that image. Water bodies, structures, wildlife, people, vehicles, and landmarks must be visibly present unless phrased only as reliable shooting-location context.
   - Treat repeated factual lead sentences across more than five images as an audit trigger. Similar burst frames may share facts, but rotating adjectives or adding generic composition prose is not a substitute for per-image inspection.
   - When near-identical burst frames need the same factual metadata, curate the weaker frames out of the upload set instead of inventing wording differences.
   - Remove generic filler such as `Presented as ...`; descriptions should say what buyers can actually see.
   - Set `release_notes` to an empty string when `release_status` is `clear`; do not add boilerplate claiming that no risks are visible.

8. For each image, edit the decision template only after review: set all four verdicts to `pass`, keep `issues` empty, list `overview`, `visual_facts`, `metadata`, and `detail_crops` under `reviewed_evidence`, set reviewer provenance, and set `independent_review` to true. A failed image must be corrected and the review pack regenerated; never mark a known issue as pass. Then issue the receipt:

```bash
python3 metadata_review_finalize.py \
  --review-pack <metadata-review-pack> \
  --decisions <metadata-review-decisions>
```

Only after the v3 receipt is issued, validate, normalize, and persist the results:

```bash
python3 metadata_writer.py \
  --manifest <temporary-manifest> \
  --strict-quality \
  --visual-reviewed \
  --review-method agent-native \
  --audit-receipt <metadata-audit-receipt>
```

The writer preflights the whole manifest before writing anything. It blocks incomplete visual facts, facts/metadata contradictions, rejected or weak technical selections, more than three selected burst frames, critical factual defects, keyword spam, weak first-keyword ordering, unsupported locations, release contradictions, invalid platform categories, and incomplete or changed review artifacts. Exact metadata reuse is allowed only for at most three explicitly ranked frames in the same burst with the same scene signature; do not rotate adjectives to evade duplicate detection. Counts below the recommended 15 English or 8 Chinese keywords are advisory only; never pad to silence them.
Writing beside images on an external volume may require user approval.
The writer binds each JSON to the source image with SHA-256. Legacy unbound JSON requires explicit `--allow-unbound-metadata` during upload and should normally be regenerated.

9. Always delete previews after metadata is saved or the workflow stops:

```bash
python3 prepare_images.py --cleanup <preview-manifest>
```

Never delete or modify the source photos.

## Explicit Anthropic fallback

Do not enter this path automatically. Use the standalone Anthropic API only when the user explicitly requests it, or when the host cannot inspect local images and the user explicitly authorizes it after being told that it changes the inference provider and may incur separate API usage. Never infer authorization from credentials, gateway configuration, dependencies, batch size, or time pressure.

When explicitly authorized, require the command-level acknowledgement flag:

```bash
python3 photo_desc.py <path> --allow-anthropic-api [--context "<shooting context>"]
```

This path alone requires the packages in `requirements-anthropic.txt` and Anthropic credentials. It performs a context-isolated higher-resolution visual verification pass with overlapping crops, produces and validates the same visual-facts contract, retries one rejected draft, and checks batch curation and repetition before writing. Set `ANTHROPIC_VERIFIER_MODEL` to use a separately configured verifier model. If native image inspection is unavailable and the user does not authorize Anthropic, explain what is missing and stop; never fabricate metadata.

## Upload when requested

Run the uploader with unbuffered output and the host's available long-running process facility:

```bash
PYTHONUNBUFFERED=1 python3 upload_photos.py <path> --platform <platform> [--dry-run] [--force]
```

Relay meaningful progress, remain attached until the command exits, and report the final `Upload summary`, including `[warn]`, `[review]`, and failed items. A successful browser upload can still require contributor review for releases, logos, private property, or editorial-only content.
Upload preflight requires SHA-bound, visually verified, current-quality metadata and rejects repeated batch copy by default. Automatic commercial metadata entry stops for unresolved model/property releases, logos, copyrighted content, or editorial-only assets. Treat `--allow-unreviewed-metadata` and `--allow-repeated-metadata` as exceptional manual overrides; never add them silently.

On first use, a browser may open for login and wait for Enter in the terminal. Sessions are stored under `.session/`.

## Review links

| Platform | Review page |
|---|---|
| Shutterstock | https://submit.shutterstock.com/catalog |
| 500px.com.cn / VCG | https://creatorstudio.500px.com.cn/index |
| Tuchong | https://contributor.tuchong.com/drafts |
| Adobe Stock | https://contributor.stock.adobe.com/en/uploads |
| Getty Images / iStock | https://contributor.gettyimages.com/ |
