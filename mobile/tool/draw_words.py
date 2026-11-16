"""Draw the phone's word boxes (integration_test/words_smoke_test.dart output)
on the page images for a visual check (docs/TECH_UPGRADE_PLAN.md D5).

python mobile/tool/draw_words.py words.json image_dir out_dir
"""
import json
import os
import sys

import cv2

data = json.load(open(sys.argv[1], encoding="utf-8"))
os.makedirs(sys.argv[3], exist_ok=True)
for key, value in data.items():
    name, engine = key.split("|")
    img = cv2.imread(os.path.join(sys.argv[2], name))
    for line in value["page"]:
        x, y, w, h = line["bbox"]
        cv2.rectangle(img, (int(x), int(y)), (int(x + w), int(y + h)), (255, 0, 0), 1)
        for word in line.get("words") or []:
            x, y, w, h = word["bbox"]
            cv2.rectangle(img, (int(x), int(y)), (int(x + w), int(y + h)), (0, 0, 255), 2)
    cv2.imwrite(os.path.join(sys.argv[3], f"{os.path.splitext(name)[0]}_{engine}.jpg"), img)
