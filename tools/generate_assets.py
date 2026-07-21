from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"


def font_for(size: int):
    candidates = [
        Path(r"C:\Windows\Fonts\segoeuib.ttf"),
        Path(r"C:\Windows\Fonts\arialbd.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def make_icon(size: int) -> Image.Image:
    scale = max(4, size // 24)
    canvas_size = size * scale
    image = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = int(canvas_size * 0.09)
    width = max(2, int(canvas_size * 0.13))
    box = (margin, margin, canvas_size - margin, canvas_size - margin)
    draw.ellipse(box, outline="#30363D", width=width)
    draw.arc(box, -90, 210, fill="#19C37D", width=width)
    text = "C"
    font = font_for(int(canvas_size * 0.38))
    text_box = draw.textbbox((0, 0), text, font=font)
    x = (canvas_size - (text_box[2] - text_box[0])) / 2
    y = (canvas_size - (text_box[3] - text_box[1])) / 2 - text_box[1]
    draw.text((x, y), text, font=font, fill="#F8FAFC")
    return image.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    sizes = [16, 20, 24, 32, 48, 64, 128, 256]
    images = [make_icon(size) for size in sizes]
    images[-1].save(ASSETS / "app_icon.png")
    images[0].save(
        ASSETS / "app_icon.ico",
        format="ICO",
        append_images=images[1:],
        sizes=[(size, size) for size in sizes],
    )


if __name__ == "__main__":
    main()
