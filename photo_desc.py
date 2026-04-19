#!/usr/bin/env python3
"""
photo_desc.py — Stock photo metadata generator
Generates bilingual (EN/ZH) titles, descriptions, and keywords for
Shutterstock, 500px, and similar platforms. Output is pretty-printed JSON.

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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import anthropic
import httpx
from PIL import Image

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

# Per-platform hard limits enforced both in the prompt and in enforce_limits().
SHUTTERSTOCK_DESC_MAX = 2048
SHUTTERSTOCK_KW_MAX = 50
PX500_DESC_MAX = 50       # characters
PX500_KW_MAX = 35

SHUTTERSTOCK_CATEGORIES = [
    "Abstract", "Animals/Wildlife", "Arts", "Backgrounds/Textures",
    "Beauty/Fashion", "Buildings/Landmarks", "Business/Finance", "Celebrities",
    "Education", "Food and drink", "Healthcare/Medical", "Holidays",
    "Industrial", "Interiors", "Miscellaneous", "Nature", "Objects",
    "Parks/Outdoor", "People", "Religion", "Science", "Signs/Symbols",
    "Sports/Recreation", "Technology", "Transportation", "Vintage",
]

SYSTEM_PROMPT = f"""You are a professional stock photo editor specializing in optimizing image metadata for platforms like Shutterstock and 500px.
Your goal is to generate titles, descriptions, and keywords that attract buyers through search and drive purchases.

Platform limits (strictly enforced):
- description_en (Shutterstock): max {SHUTTERSTOCK_DESC_MAX} characters
- description_zh (500px.com.cn): max {PX500_DESC_MAX} characters, keep concise
- keywords_en (Shutterstock): exactly {SHUTTERSTOCK_KW_MAX}, all lowercase
- keywords_zh (500px.com.cn): exactly {PX500_KW_MAX}

Arrange keywords from most to least important, covering subject/color/mood/scene/style/use-case dimensions.

Shutterstock categories (category1 required, category2 optional) must be chosen exactly from this list:
{", ".join(SHUTTERSTOCK_CATEGORIES)}

Output must be strict JSON with no markdown code fences:
{{
  "title_en": "English title",
  "title_zh": "Chinese title",
  "description_en": "Shutterstock description (max {SHUTTERSTOCK_DESC_MAX} chars)",
  "description_zh": "500px Chinese description (max {PX500_DESC_MAX} chars)",
  "keywords_en": ["keyword1", ..., "keyword{SHUTTERSTOCK_KW_MAX}"],
  "keywords_zh": ["Chinese keyword 1", ..., "Chinese keyword {PX500_KW_MAX}"],
  "category1": "Primary Shutterstock category (required)",
  "category2": "Secondary Shutterstock category (optional, omit if not applicable)",
  "location_zh": "Shooting location in Chinese, city-level preferred (e.g. 旧金山, 洛杉矶, 纽约). Infer from context or visual cues; omit field if truly unknown.",
  "core_keywords_zh": ["most objective keyword 1", "...", "up to 5 total — pick from keywords_zh, most objective subject terms first"]
}}"""


_GATEWAY_URL = os.environ.get("CLAUDE_GATEWAY_URL", "")
_TOKEN_CMD = os.environ.get("CLAUDE_TOKEN_CMD", "npx @ebay/claude-code-token@latest get_token")


class _BearerAuth(httpx.Auth):
    def __init__(self, token: str):
        self._token = token

    def auth_flow(self, request):
        request.headers["Authorization"] = f"Bearer {self._token}"
        yield request


def _get_token() -> str:
    try:
        result = subprocess.run(
            shlex.split(_TOKEN_CMD), capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        sys.exit(f"Token command failed: {e.stderr.strip() or e.stdout.strip()}")


def make_client() -> anthropic.Anthropic:
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
        http_client=httpx.Client(auth=_BearerAuth(token)),
    )


def get_model() -> str:
    return os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")


def load_image(path: Path) -> tuple[str, str]:
    """Resize to 1024px on the long edge and encode as JPEG for the API."""
    img = Image.open(path).convert("RGB")
    img.thumbnail((1024, 1024), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70, optimize=True)
    return base64.standard_b64encode(buf.getvalue()).decode(), "image/jpeg"


def analyze_image(image_path: Path, client: anthropic.Anthropic, context: str = "") -> dict:
    data, media_type = load_image(image_path)

    context_note = f"\n\nShooting context (use this to improve description accuracy and keyword commercial value): {context}" if context else ""

    response = client.messages.create(
        model=get_model(),
        max_tokens=2048,
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
                            f"keywords_en: exactly {SHUTTERSTOCK_KW_MAX}, all lowercase. "
                            f"keywords_zh: exactly {PX500_KW_MAX} Chinese keywords. "
                            f"description_zh: max {PX500_DESC_MAX} characters."
                            + context_note
                        ),
                    },
                ],
            }
        ],
    )

    raw = next(b.text for b in response.content if b.type == "text")
    # Strip markdown code fences if the model wraps the JSON
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


def enforce_limits(result: dict) -> dict:
    """Hard-truncate fields to platform limits as a safety net after the API call."""
    result["description_en"] = result.get("description_en", "")[:SHUTTERSTOCK_DESC_MAX]
    result["description_zh"] = result.get("description_zh", "")[:PX500_DESC_MAX]
    result["keywords_en"] = result.get("keywords_en", [])[:SHUTTERSTOCK_KW_MAX]
    result["keywords_zh"] = result.get("keywords_zh", [])[:PX500_KW_MAX]
    return result


def write_json(result: dict, image_path: Path, output_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = output_dir / f"{image_path.stem}_{timestamp}.json"

    payload = {
        "source": image_path.name,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        **result,
    }
    out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_file


def process_one(image_path: Path, output_dir: Path, client: anthropic.Anthropic, context: str = "") -> tuple[Path, bool, str]:
    try:
        result = enforce_limits(analyze_image(image_path, client, context))
        out_file = write_json(result, image_path, output_dir)
        return image_path, True, str(out_file)
    except Exception as e:
        return image_path, False, str(e)


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


def main():
    parser = argparse.ArgumentParser(description="Generate bilingual stock photo metadata")
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
        return

    done = 0
    failed = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(process_one, img, output_for(img), client, args.context): img for img in images}
        for future in as_completed(futures):
            img, ok, info = future.result()
            done += 1
            if ok:
                print(f"[{done}/{total}] ✓ {img.name} → {Path(info).name}")
            else:
                failed.append(img.name)
                print(f"[{done}/{total}] ✗ {img.name} failed: {info}")

    print(f"\nDone: {total - len(failed)}/{total} succeeded")
    if failed:
        print("Failed: " + ", ".join(failed))


if __name__ == "__main__":
    main()
