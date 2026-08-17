#!/usr/bin/env python3
"""
photo_desc.py - Optional Anthropic API stock metadata generator.
Generates bilingual (EN/ZH) titles, descriptions, and keywords for
Shutterstock, 500px, and similar platforms. Agent-native workflows use
metadata_writer.py instead and do not require an AI API key.

Usage:
  Single image: python3 photo_desc.py <image> [--output <dir>]
  Batch:        python3 photo_desc.py <directory> [--output <dir>]
"""

import argparse
import base64
import io
import json
import os
import re
import shlex
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from metadata_core import (
    PX500_DESC_MAX,
    PX500_KW_MAX,
    SHUTTERSTOCK_KW_MAX,
    SUPPORTED_EXTS,
    SYSTEM_PROMPT,
    enforce_limits,
    find_batch_quality_issues,
    validate_metadata,
    validate_metadata_quality,
    write_metadata,
)

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()

_GATEWAY_URL = os.environ.get("CLAUDE_GATEWAY_URL", "")
_TOKEN_CMD = os.environ.get("CLAUDE_TOKEN_CMD", "npx @ebay/claude-code-token@latest get_token")


def _get_token() -> str:
    try:
        result = subprocess.run(
            shlex.split(_TOKEN_CMD), capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        sys.exit(f"Token command failed: {e.stderr.strip() or e.stdout.strip()}")


def make_client():
    try:
        import anthropic
        import httpx
    except ImportError:
        sys.exit(
            "Anthropic fallback dependencies are missing. Install them with: "
            "pip install -r requirements-anthropic.txt"
        )

    class BearerAuth(httpx.Auth):
        def __init__(self, token: str):
            self._token = token

        def auth_flow(self, request):
            request.headers["Authorization"] = f"Bearer {self._token}"
            yield request

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        return anthropic.Anthropic(api_key=api_key)
    if not _GATEWAY_URL:
        sys.exit(
            "Set ANTHROPIC_API_KEY or CLAUDE_GATEWAY_URL + CLAUDE_TOKEN_CMD. "
            "See .env.example for details."
        )
    token = _get_token()
    return anthropic.Anthropic(
        api_key="placeholder",
        base_url=_GATEWAY_URL,
        http_client=httpx.Client(auth=BearerAuth(token)),
    )


def get_model() -> str:
    return os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")


def get_verifier_model() -> str:
    """Allow a separately configured verifier while retaining a safe fallback."""
    return os.environ.get("ANTHROPIC_VERIFIER_MODEL", get_model())


def load_image(
    path: Path, *, max_edge: int = 1024, quality: int = 70
) -> tuple[str, str]:
    """Resize and encode an EXIF-corrected JPEG for the API."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        sys.exit(
            "Anthropic fallback image support is missing. Install it with: "
            "pip install pillow"
        )

    with Image.open(path) as opened:
        opened.seek(0)
        img = ImageOps.exif_transpose(opened)
        if img.mode in ("RGBA", "LA") or (
            img.mode == "P" and "transparency" in img.info
        ):
            rgba = img.convert("RGBA")
            background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            img = Image.alpha_composite(background, rgba).convert("RGB")
        else:
            img = img.convert("RGB")
        resampling = getattr(Image, "Resampling", Image).LANCZOS
        img.thumbnail((max_edge, max_edge), resampling)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
    return base64.standard_b64encode(buf.getvalue()).decode(), "image/jpeg"


def load_image_crops(
    path: Path, *, max_edge: int = 1024, quality: int = 80
) -> list[tuple[str, str]]:
    """Encode four overlapping quadrants for small text/logo/release review."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        sys.exit(
            "Anthropic fallback image support is missing. Install it with: "
            "pip install pillow"
        )

    encoded = []
    with Image.open(path) as opened:
        opened.seek(0)
        image = ImageOps.exif_transpose(opened).convert("RGB")
        width, height = image.size
        if max(width, height) <= max_edge:
            return []
        overlap_x = max(1, width // 12)
        overlap_y = max(1, height // 12)
        mid_x, mid_y = width // 2, height // 2
        boxes = (
            (0, 0, min(width, mid_x + overlap_x), min(height, mid_y + overlap_y)),
            (max(0, mid_x - overlap_x), 0, width, min(height, mid_y + overlap_y)),
            (0, max(0, mid_y - overlap_y), min(width, mid_x + overlap_x), height),
            (max(0, mid_x - overlap_x), max(0, mid_y - overlap_y), width, height),
        )
        resampling = getattr(Image, "Resampling", Image).LANCZOS
        for box in boxes:
            crop = image.crop(box)
            crop.thumbnail((max_edge, max_edge), resampling)
            buffer = io.BytesIO()
            crop.save(buffer, format="JPEG", quality=quality, optimize=True)
            encoded.append(
                (base64.standard_b64encode(buffer.getvalue()).decode(), "image/jpeg")
            )
    return encoded


def _json_from_response(response) -> dict:
    raw = next(block.text for block in response.content if block.type == "text")
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw)
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("model response must be a JSON object")
    return result


def analyze_image(
    image_path: Path,
    client,
    context: str = "",
    revision_feedback: str = "",
) -> dict:
    data, media_type = load_image(image_path)

    context_note = (
        "\n\nShooting context (supporting location information only; never treat "
        f"it as proof that a subject is visible): {context}"
        if context
        else ""
    )
    revision_note = (
        "\n\nA visual verifier rejected the previous draft. Correct every issue "
        f"listed here: {revision_feedback}"
        if revision_feedback
        else ""
    )

    last_error = None
    for attempt in range(3):
        try:
            response = client.messages.create(
                model=get_model(),
                max_tokens=3072,
                system=SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": data,
                                },
                            },
                            {
                                "type": "text",
                                "text": (
                                    "Analyze this image and generate stock photo metadata optimized for commercial sales. "
                                    "Return strict JSON only — no extra text, no markdown code fences. "
                                    f"keywords_en: up to {SHUTTERSTOCK_KW_MAX}, all lowercase, ordered by relevance, no filler. "
                                    f"keywords_zh: up to {PX500_KW_MAX} Chinese keywords. "
                                    f"description_zh: max {PX500_DESC_MAX} characters."
                                    + context_note
                                    + revision_note
                                ),
                            },
                        ],
                    }
                ],
            )

            return _json_from_response(response)
        except Exception as error:
            last_error = error
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"metadata API failed after 3 attempts: {last_error}")


def verify_metadata(
    image_path: Path, metadata: dict, client, context: str = ""
) -> tuple[bool, list[str]]:
    """Run a context-isolated visual-grounding pass with detailed crops."""
    data, media_type = load_image(image_path, max_edge=1536, quality=78)
    image_blocks = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": data,
            },
        }
    ]
    for crop_data, crop_media_type in load_image_crops(image_path):
        image_blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": crop_media_type,
                    "data": crop_data,
                },
            }
        )
    last_error = None
    for attempt in range(3):
        try:
            response = client.messages.create(
                model=get_verifier_model(),
                max_tokens=1024,
                system=(
                    "You are a stock-photo metadata verifier. The first image is a full "
                    "preview and any following images are overlapping crops of the same "
                    "source. Compare the proposed bilingual metadata against these images "
                    "only. Check every concrete "
                    "subject, action, water body, landform, structure, person, text/logo, "
                    "landmark, weather claim, English and Chinese keyword, platform category, "
                    "and release/IP risk. Location fields whose location_source is context, "
                    "EXIF, or manual need not be visually provable, but they must not make a "
                    "nonvisible subject appear visible in a title or description. Fail "
                    "material omissions of the primary commercial subject, bilingual "
                    "contradictions, or any invented visual claim. Return strict JSON only as "
                    "{\"verdict\":\"pass\",\"issues\":[]} or "
                    "{\"verdict\":\"fail\",\"issues\":[\"specific correction\"]}."
                ),
                messages=[
                    {
                        "role": "user",
                        "content": image_blocks + [
                            {
                                "type": "text",
                                "text": (
                                    "Verify this proposed metadata:\n"
                                    + json.dumps(metadata, ensure_ascii=False)
                                ),
                            },
                        ],
                    }
                ],
            )
            result = _json_from_response(response)
            break
        except Exception as error:
            last_error = error
            if attempt < 2:
                time.sleep(2 ** attempt)
    else:
        raise RuntimeError(
            f"visual metadata verifier failed after 3 attempts: {last_error}"
        )
    verdict = str(result.get("verdict", "")).strip().lower()
    issues = result.get("issues", [])
    if not isinstance(issues, list):
        raise ValueError("visual verifier issues must be an array")
    issues = [str(issue).strip() for issue in issues if str(issue).strip()]
    if verdict not in {"pass", "fail"}:
        raise ValueError("visual verifier verdict must be pass or fail")
    if verdict == "fail" and not issues:
        issues = ["visual verifier rejected the metadata without details"]
    return verdict == "pass", issues


def generate_one(
    image_path: Path, client, context: str = ""
) -> tuple[Path, bool, object]:
    try:
        result = enforce_limits(analyze_image(image_path, client, context))
        for review_attempt in range(2):
            static_issues = (
                validate_metadata(result)
                + validate_metadata_quality(result)
            )
            if static_issues:
                passed, issues = False, static_issues
            else:
                passed, issues = verify_metadata(image_path, result, client, context)
            if passed:
                break
            if review_attempt == 1:
                raise RuntimeError(
                    "visual metadata verification failed: " + "; ".join(issues)
                )
            result = enforce_limits(
                analyze_image(
                    image_path,
                    client,
                    context,
                    revision_feedback="; ".join(issues),
                )
            )
        return image_path, True, result
    except Exception as error:
        return image_path, False, str(error)


def process_one(
    image_path: Path, output_dir: Path, client, context: str = ""
) -> tuple[Path, bool, str]:
    image_path, ok, result = generate_one(image_path, client, context)
    if not ok:
        return image_path, False, str(result)
    try:
        out_file = write_metadata(
            result,
            image_path,
            output_dir,
            visual_review_status="verified",
            visual_review_method="anthropic-second-pass",
        )
        return image_path, True, str(out_file)
    except Exception as error:
        return image_path, False, str(error)


def collect_images(target: Path) -> list[Path]:
    if target.is_file():
        if target.suffix.lower() not in SUPPORTED_EXTS:
            sys.exit(f"Unsupported format: {target.suffix}. Supported: {', '.join(SUPPORTED_EXTS)}")
        return [target]
    if target.is_dir():
        images = sorted(
            p for p in target.iterdir()
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
        )
        if not images:
            sys.exit(f"No supported images found in: {target}")
        return images
    sys.exit(f"Path does not exist: {target}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate bilingual stock photo metadata with the Anthropic API"
    )
    parser.add_argument("target", help="Image file or directory of images")
    parser.add_argument("--output", "-o", default=None, help="Output directory (default: same directory as the image)")
    parser.add_argument("--workers", "-w", type=int, default=3, help="Parallel workers for batch mode (default: 3)")
    parser.add_argument("--context", "-c", default="", help="Additional context about the photos (e.g. location, scene, shooting conditions)")
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    fixed_output = Path(args.output).expanduser().resolve() if args.output else None
    if fixed_output:
        fixed_output.mkdir(parents=True, exist_ok=True)

    images = collect_images(target)
    total = len(images)
    out_label = str(fixed_output) if fixed_output else "alongside each image"
    print(f"Found {total} image(s). Output: {out_label}")

    client = make_client()

    def output_for(img: Path) -> Path:
        return fixed_output or img.parent

    if args.context:
        print(f"Context: {args.context}")

    if total == 1:
        img, ok, info = process_one(images[0], output_for(images[0]), client, args.context)
        if ok:
            print(f"✓ {img.name} → {info}")
        else:
            print(f"✗ {img.name} failed: {info}")
        return 0 if ok else 1

    done = 0
    failed = []
    generated = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(generate_one, img, client, args.context): img
            for img in images
        }
        for future in as_completed(futures):
            img, ok, result = future.result()
            done += 1
            if ok:
                generated.append((img, result))
                print(f"[{done}/{total}] verified {img.name}")
            else:
                failed.append(img.name)
                print(f"[{done}/{total}] failed {img.name}: {result}")

    repeated = find_batch_quality_issues(
        [(str(image), metadata) for image, metadata in generated]
    )
    for image, metadata in generated:
        if str(image) in repeated:
            failed.append(image.name)
            print(
                f"[batch] failed {image.name}: "
                + "; ".join(repeated[str(image)])
            )
            continue
        try:
            out_file = write_metadata(
                metadata,
                image,
                output_for(image),
                visual_review_status="verified",
                visual_review_method="anthropic-second-pass",
            )
            print(f"wrote {image.name} -> {out_file.name}")
        except Exception as error:
            failed.append(image.name)
            print(f"failed {image.name} during write: {error}")

    print(f"\nDone: {total - len(failed)}/{total} succeeded")
    if failed:
        print("Failed: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
