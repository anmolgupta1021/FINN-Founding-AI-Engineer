"""Generate FINN PWA icons (no text → no font dependency): an ink tile with three 'brief' rules,
the top one heavier — the product idea in one glyph: ranked lines, most important first."""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "apps" / "web" / "public"
INK, PAPER, SIGNAL = (22, 21, 15), (246, 244, 239), (138, 43, 29)


def icon(size: int, maskable: bool = False) -> Image.Image:
    img = Image.new("RGB", (size, size), INK)
    d = ImageDraw.Draw(img)
    pad = size * (0.28 if maskable else 0.2)
    w = size - 2 * pad
    y = pad + w * 0.12
    # top rule: heavy, signal-coloured dot to its left
    h1 = w * 0.13
    d.ellipse([pad, y, pad + h1, y + h1], fill=SIGNAL)
    d.rectangle([pad + h1 * 1.6, y, pad + w, y + h1], fill=PAPER)
    # two lighter rules
    for i, frac in enumerate((0.78, 0.55)):
        yy = y + h1 + w * (0.2 + i * 0.22)
        d.rectangle([pad, yy, pad + w * frac, yy + w * 0.06], fill=PAPER)
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    icon(192).save(OUT / "icon-192.png")
    icon(512).save(OUT / "icon-512.png")
    icon(512, maskable=True).save(OUT / "icon-512-maskable.png")
    icon(180).save(OUT / "apple-touch-icon.png")
    print("icons written to", OUT)


if __name__ == "__main__":
    main()
