"""Generate a known two-spread video; never uses user documents."""
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

root = Path(__file__).resolve().parents[1]
out = root / 'build' / 'verification'
out.mkdir(parents=True, exist_ok=True)
font = ImageFont.truetype(str(root / 'assets' / 'Mukta-Regular.ttf'), 30)
writer = cv2.VideoWriter(str(out / 'book-fixture.mp4'), cv2.VideoWriter_fourcc(*'mp4v'), 8, (1200, 900))
assert writer.isOpened()
for spread in (1, 2):
    image = Image.new('RGB', (1200, 900), (55, 65, 70))
    draw = ImageDraw.Draw(image)
    draw.rectangle((60, 50, 1139, 849), fill=(248, 244, 230))
    draw.rectangle((590, 50, 610, 849), fill=(75, 70, 65))
    for side, x in [('LEFT', 95), ('RIGHT', 645)]:
        draw.text((x, 95), f'{side} PAGE {spread}', font=font, fill='black')
        for line in range(12):
            text = (f'This is the first book spread. {line}' if spread == 1
                    else f'New chapter with different words {line}')
            draw.text((x, 155+line*48), text, font=font, fill='black')
    frame = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
    for _ in range(24):
        writer.write(frame)
    # Brief page turn (no stable readable page).
    for _ in range(2):
        writer.write(np.full((900,1200,3),75,dtype=np.uint8))
writer.release()
print(out / 'book-fixture.mp4')
