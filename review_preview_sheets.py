"""Build compact contact sheets from privacy-reduced photo previews."""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--per-sheet", type=int, default=2)
    parser.add_argument("--overview-grid", action="store_true")
    args = parser.parse_args()

    items = json.loads(args.manifest.read_text())["items"]
    args.output.mkdir(parents=True, exist_ok=True)
    if args.overview_grid:
        columns = 4
        cell_width, cell_height = 640, 470
        for start in range(0, len(items), args.per_sheet):
            group = items[start : start + args.per_sheet]
            rows = (len(group) + columns - 1) // columns
            sheet = Image.new("RGB", (columns * cell_width, rows * cell_height), "white")
            draw = ImageDraw.Draw(sheet)
            for offset, item in enumerate(group):
                x = offset % columns * cell_width
                y = offset // columns * cell_height
                draw.text((x + 10, y + 8), Path(item["source"]).name, fill="black")
                with Image.open(item["preview"]) as preview:
                    preview.thumbnail((cell_width - 16, cell_height - 36))
                    sheet.paste(preview, (x + (cell_width - preview.width) // 2, y + 32))
            out = args.output / f"overview_{start + 1:04d}_{start + len(group):04d}.jpg"
            sheet.save(out, "JPEG", quality=88)
            print(out)
        return
    panel_width, panel_height = 1024, 1420
    for start in range(0, len(items), args.per_sheet):
        group = items[start : start + args.per_sheet]
        sheet = Image.new("RGB", (panel_width * len(group), panel_height), "white")
        draw = ImageDraw.Draw(sheet)
        for offset, item in enumerate(group):
            x = offset * panel_width
            draw.text((x + 12, 10), Path(item["source"]).name, fill="black")
            paths = [item["preview"], *item["detail_previews"]]
            for index, path in enumerate(paths):
                with Image.open(path) as image:
                    if index == 0:
                        image.thumbnail((panel_width, 680))
                        sheet.paste(image, (x + (panel_width - image.width) // 2, 32))
                    else:
                        image.thumbnail((panel_width // 2, 350))
                        column = (index - 1) % 2
                        row = (index - 1) // 2
                        left = x + column * (panel_width // 2)
                        top = 730 + row * 350
                        sheet.paste(image, (left + ((panel_width // 2) - image.width) // 2, top))
        out = args.output / f"sheet_{start + 1:04d}_{start + len(group):04d}.jpg"
        sheet.save(out, "JPEG", quality=88)
        print(out)


if __name__ == "__main__":
    main()
