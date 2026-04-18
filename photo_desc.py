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
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import anthropic
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

SYSTEM_PROMPT = f"""你是一位专业的图库图片编辑，擅长为 Shutterstock、500px 等平台优化图片元数据。
你的目标是生成能吸引买家搜索并促成购买的标题、描述和关键词。

各平台限制（必须严格遵守）：
- description_en（Shutterstock）：不超过 {SHUTTERSTOCK_DESC_MAX} 个字符
- description_zh（500px.com.cn）：不超过 {PX500_DESC_MAX} 个字符，务必简洁
- keywords_en（Shutterstock）：恰好 {SHUTTERSTOCK_KW_MAX} 个，全部小写
- keywords_zh（500px.com.cn）：恰好 {PX500_KW_MAX} 个

关键词从最重要到最次要排列，覆盖主体/颜色/情绪/场景/风格/用途等维度。

Shutterstock 分类（category1 必填，category2 可选）必须从以下列表中精确选择：
{", ".join(SHUTTERSTOCK_CATEGORIES)}

输出格式必须是严格的 JSON，不包含任何 markdown 代码块标记：
{{
  "title_en": "English title",
  "title_zh": "中文标题",
  "description_en": "Shutterstock description (max {SHUTTERSTOCK_DESC_MAX} chars)",
  "description_zh": "500px中文描述（最多{PX500_DESC_MAX}字）",
  "keywords_en": ["keyword1", ..., "keyword{SHUTTERSTOCK_KW_MAX}"],
  "keywords_zh": ["关键词1", ..., "关键词{PX500_KW_MAX}"],
  "category1": "Primary Shutterstock category (required)",
  "category2": "Secondary Shutterstock category (optional, omit if not applicable)"
}}"""


def get_api_key() -> str:
    """Return the API token, fetching it via the eBay helper if not set in the environment."""
    if key := os.environ.get("ANTHROPIC_API_KEY"):
        return key
    try:
        result = subprocess.run(
            ["npx", "@ebay/claude-code-token@latest", "get_token"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        token = result.stdout.strip()
        if token:
            return token
    except Exception as e:
        sys.exit(f"Failed to obtain API token: {e}")
    sys.exit("Failed to obtain API token. Set ANTHROPIC_API_KEY or ensure the eBay token helper is available.")


def make_client() -> anthropic.Anthropic:
    token = get_api_key()
    base_url = os.environ.get(
        "ANTHROPIC_BASE_URL",
        "https://platformgateway2.vip.ebay.com/hubgptgatewaysvc/v1/anthropic",
    )

    import httpx

    # The eBay gateway requires Bearer auth; override the SDK's default x-api-key injection.
    class BearerAuth(httpx.Auth):
        def auth_flow(self, request):
            request.headers["Authorization"] = f"Bearer {token}"
            request.headers.pop("x-api-key", None)
            yield request

    return anthropic.Anthropic(
        api_key="placeholder",
        base_url=base_url,
        http_client=httpx.Client(auth=BearerAuth()),
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


def analyze_image(image_path: Path, client: anthropic.Anthropic) -> dict:
    data, media_type = load_image(image_path)

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
                            "请分析这张图片并生成适合图库销售的元数据。"
                            "严格返回 JSON 格式，不要任何额外文字或代码块标记。"
                            f"keywords_en 恰好 {SHUTTERSTOCK_KW_MAX} 个，"
                            f"keywords_zh 恰好 {PX500_KW_MAX} 个，"
                            f"description_zh 不超过 {PX500_DESC_MAX} 个字符。"
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


def process_one(image_path: Path, output_dir: Path, client: anthropic.Anthropic) -> tuple[Path, bool, str]:
    try:
        result = enforce_limits(analyze_image(image_path, client))
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

    if total == 1:
        img, ok, info = process_one(images[0], output_for(images[0]), client)
        if ok:
            print(f"✓ {img.name} → {info}")
        else:
            print(f"✗ {img.name} failed: {info}")
        return

    done = 0
    failed = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(process_one, img, output_for(img), client): img for img in images}
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
