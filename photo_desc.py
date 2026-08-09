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


def load_image(path: Path) -> tuple[str, str]:
    """Resize to 1024px on the long edge and encode as JPEG for the API."""
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
        img.thumbnail((1024, 1024), resampling)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=70, optimize=True)
    return base64.standard_b64encode(buf.getvalue()).decode(), "image/jpeg"


def analyze_image(image_path: Path, client, context: str = "") -> dict:
    data, media_type = load_image(image_path)

    context_note = f"\n\nShooting context (use this to improve description accuracy and keyword commercial value): {context}" if context else ""

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
                                ),
                            },
                        ],
                    }
                ],
            )

            raw = next(block.text for block in response.content if block.type == "text")
            raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
            raw = re.sub(r"\s*```$", "", raw)
            return json.loads(raw)
        except Exception as error:
            last_error = error
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"metadata API failed after 3 attempts: {last_error}")


def process_one(image_path: Path, output_dir: Path, client, context: str = "") -> tuple[Path, bool, str]:
    try:
        result = enforce_limits(analyze_image(image_path, client, context))
        out_file = write_metadata(result, image_path, output_dir)
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
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
