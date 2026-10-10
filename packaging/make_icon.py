"""Draws the Open DyePrint icon: yellow, magenta and cyan dye layers overlapping on a
print, the way a dye-sublimation printer builds a photo. Writes .png and .ico."""

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "src" / "opendyeprint" / "assets"
S = 1024  # drawn large, downsampled for clean edges

PAPER = (250, 247, 240, 255)
EDGE = (205, 200, 190, 255)
SHADOW = (0, 0, 0, 70)
DYES = [((404, 400), (255, 215, 0)), ((620, 400), (230, 0, 126)), ((512, 590), (0, 174, 239))]


def draw() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((136, 136, 904, 904), 120, fill=SHADOW)
    d.rounded_rectangle((120, 120, 888, 888), 120, fill=PAPER)
    # Multiplying the discs mixes them like stacked dye layers (subtractive colour).
    layer = Image.new("RGB", (S, S), (255, 255, 255))
    r = 220
    for (cx, cy), col in DYES:
        disc = Image.new("RGB", (S, S), (255, 255, 255))
        ImageDraw.Draw(disc).ellipse((cx - r, cy - r, cx + r, cy + r), fill=col)
        layer = ImageChops.multiply(layer, disc)
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((120, 120, 888, 888), 120, fill=255)
    img.paste(layer, (0, 0), mask)
    d.rounded_rectangle((120, 120, 888, 888), 120, outline=EDGE, width=6)
    return img


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    big = draw().resize((256, 256), Image.Resampling.LANCZOS)
    big.save(OUT / "opendyeprint.png")
    big.save(OUT / "opendyeprint.ico",
             sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", OUT)
