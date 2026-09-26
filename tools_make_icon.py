"""Génère assets/icon.png : un vélo lancé à pleine vitesse (traînées de vitesse)."""
from PIL import Image, ImageDraw

S = 1024                      # dessin en 1024 px puis réduction en 512 (anticrénelage)
ORANGE = (240, 128, 24, 255)
WHITE = (255, 255, 255, 255)

img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# Fond : carré arrondi sombre avec léger dégradé vertical
bg = Image.new("RGBA", (S, S))
for y in range(S):
    t = y / S
    bg.putpixel((0, y), (int(22 + 18 * t), int(24 + 10 * t), int(38 + 16 * t), 255))
bg = bg.crop((0, 0, 1, S)).resize((S, S))
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle((0, 0, S - 1, S - 1), radius=210, fill=255)
img.paste(bg, (0, 0), mask)

# Vélo penché vers l'avant (dessiné sur un calque puis incliné)
bike = Image.new("RGBA", (S, S), (0, 0, 0, 0))
b = ImageDraw.Draw(bike)
W = 40
rear, front, r = (370, 620), (750, 620), 165
for cx, cy in (rear, front):
    b.ellipse((cx - r, cy - r, cx + r, cy + r), outline=WHITE, width=W)
    b.ellipse((cx - 22, cy - 22, cx + 22, cy + 22), fill=WHITE)
bb, seat, head_top, head_bot = (545, 640), (495, 420), (715, 400), (735, 470)
for p, q in ((rear, bb), (bb, seat), (seat, rear), (seat, head_top), (bb, head_bot),
             (head_top, head_bot), (head_bot, front)):
    b.line((p, q), fill=ORANGE, width=W + 6, joint="curve")
b.line((head_top, (head_top[0] - 10, head_top[1] - 55)), fill=ORANGE, width=W)             # potence
b.line(((head_top[0] - 50, head_top[1] - 62), (head_top[0] + 40, head_top[1] - 62)), fill=WHITE, width=W - 6)  # guidon
b.line((seat, (seat[0] - 15, seat[1] - 35)), fill=ORANGE, width=W - 6)                    # tige de selle
b.line(((seat[0] - 75, seat[1] - 40), (seat[0] + 35, seat[1] - 40)), fill=WHITE, width=W - 4)  # selle
for p in (rear, front, bb, seat, head_top, head_bot):
    b.ellipse((p[0] - W // 2 - 3, p[1] - W // 2 - 3, p[0] + W // 2 + 3, p[1] + W // 2 + 3), fill=ORANGE)
b.ellipse((bb[0] - 45, bb[1] - 45, bb[0] + 45, bb[1] + 45), outline=WHITE, width=16)       # plateau
bike = bike.rotate(-7, resample=Image.BICUBIC, center=(560, 560))   # penché en avant
img.alpha_composite(bike, (40, 0))

# Traînées de vitesse derrière le vélo
for y, x0, x1, w in ((430, 90, 300, 30), (530, 50, 230, 34), (640, 110, 210, 26), (740, 70, 190, 22)):
    d.rounded_rectangle((x0, y - w // 2, x1, y + w // 2), radius=w // 2, fill=(255, 255, 255, 190))

img.resize((512, 512), Image.LANCZOS).save("assets/icon.png")
print("assets/icon.png")
