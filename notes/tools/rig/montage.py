"""montage.py OUT.png COLS IMG... : tile screenshots 2x, labelled by file name."""
import sys
from PIL import Image, ImageDraw
out, cols, files = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
ims = [Image.open(f).convert("RGB").resize((480, 320), Image.NEAREST) for f in files]
rows = (len(ims) + cols - 1) // cols
sheet = Image.new("RGB", (cols * 484, rows * 340), "white")
d = ImageDraw.Draw(sheet)
for i, (im, f) in enumerate(zip(ims, files)):
    x, y = (i % cols) * 484, (i // cols) * 340
    sheet.paste(im, (x, y + 18))
    d.text((x + 2, y + 2), f.rsplit("/", 1)[-1], fill="black")
sheet.save(out)
