"""Generate the Prompt Optimizer desktop icon: a clean skull on a dark
rounded square, matching the app's monochrome theme. Outputs:
    assets/skull.ico   (multi-size Windows icon)
    assets/skull.png   (256px preview)

Run:  .venv\\Scripts\\python.exe scripts\\make_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
ASSETS.mkdir(exist_ok=True)

S = 512  # supersample canvas
BG = (15, 15, 15, 255)       # near-black panel
BONE = (237, 237, 237, 255)  # off-white skull
HOLE = (15, 15, 15, 255)     # eye/nose/teeth cutouts (match bg)


def rounded_rect(draw, box, radius, fill):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def build() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Dark rounded-square background tile.
    rounded_rect(d, (16, 16, S - 16, S - 16), radius=96, fill=BG)

    cx = S // 2

    # --- Skull silhouette (bone) ---
    # Cranium dome (wide ellipse).
    d.ellipse((118, 96, 394, 372), fill=BONE)
    # Cheek/temple fill to square the sides a little.
    rounded_rect(d, (150, 230, 362, 350), radius=60, fill=BONE)
    # Jaw block, narrower, sitting under the cranium.
    rounded_rect(d, (198, 322, 314, 432), radius=44, fill=BONE)

    # --- Eye sockets (two large angled holes) ---
    d.ellipse((158, 196, 244, 286), fill=HOLE)
    d.ellipse((268, 196, 354, 286), fill=HOLE)

    # --- Nasal cavity (downward triangle) ---
    d.polygon([(cx, 286), (cx - 26, 332), (cx + 26, 332)], fill=HOLE)

    # --- Teeth: carve gaps into the jaw with thin vertical bars ---
    top, bot = 330, 432
    for x in (cx - 40, cx - 14, cx + 14, cx + 40):
        d.line((x, top, x, bot), fill=HOLE, width=10)
    # Separate the jaw from the upper teeth row.
    d.line((204, 356, 308, 356), fill=HOLE, width=8)

    return img


def main() -> None:
    art = build()
    png_path = ASSETS / "skull.png"
    ico_path = ASSETS / "skull.ico"

    art.resize((256, 256), Image.LANCZOS).save(png_path)

    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    art.save(ico_path, format="ICO", sizes=sizes)

    print(f"wrote {png_path} ({png_path.stat().st_size} bytes)")
    print(f"wrote {ico_path} ({ico_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
