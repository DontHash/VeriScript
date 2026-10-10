#!/usr/bin/env python3
"""finetune_digit_crnn.py — N5 retry (docs/PLAN.md Appendix AS).

Data-only digit fine-tune, warm-started from the shipped letterpress CRNN
checkpoint. Unlike `deva_crnn.train` (charset rebuilt from the data, equality
enforced), this trainer reuses the checkpoint charset directly: the 317
owner-audited crops cannot cover all 134 base chars by construction, so the
equality contract cannot hold. A recorded deviation (Appendix AS).

Usage:
    python scripts/finetune_digit_crnn.py \
        --staging data/doc_eval/target_domain_digit_staging_v1 \
        --staging data/doc_eval/target_domain_digit_staging_v2 \
        --staging data/doc_eval/target_domain_digit_staging_v3 \
        --init weights/deva_crnn_h48w512.pt --out out/digit_ft/run1 \
        --epochs 24 --aug-per 3
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Dict, List, Tuple

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from deva_crnn.augment import augment_line  # noqa: E402
from deva_crnn.charset import decode, encode  # noqa: E402
from deva_crnn.data import normalize_line  # noqa: E402
from deva_crnn.model import CRNN  # noqa: E402
from veriscript.core import data as doc_data  # noqa: E402


def load_staging(dirs: List[str], charset: List[str]):
    """(images, texts) from staging dirs, labels filtered to `charset`."""
    images, texts, dropped = [], [], 0
    for d in dirs:
        labels = os.path.join(d, "labels.tsv")
        if not os.path.isfile(labels):
            raise SystemExit(f"missing {labels}")
        for line in open(labels, encoding="utf-8"):
            line = line.rstrip("\n")
            if not line:
                continue
            name, text = line.split("\t", 1)
            text = "".join(c for c in text if c in charset)
            img = doc_data.imread_safe(os.path.join(d, "lines", name))
            if img is None or not text:
                dropped += 1
                continue
            images.append(img)
            texts.append(text)
    return images, texts, dropped


class _DS(Dataset):
    def __init__(self, images: List[np.ndarray], texts: List[str],
                 charset: List[str], h: int, w: int):
        self.images = images
        self.texts = texts
        self.charset = charset
        self.h, self.w = h, w

    def __len__(self) -> int:
        return len(self.texts)

    def __getitem__(self, i):
        img = normalize_line(self.images[i], h=self.h, w=self.w)
        x = torch.from_numpy(img.astype(np.float32) / 255.0)
        x = (x - 0.5) / 0.5
        y = torch.tensor(encode(self.texts[i], self.charset),
                         dtype=torch.long)
        return x.unsqueeze(0), y, len(y)


def _collate(batch):
    imgs = torch.stack([b[0] for b in batch])
    targets = torch.cat([b[1] for b in batch])
    lens = torch.tensor([b[2] for b in batch], dtype=torch.long)
    return imgs, targets, lens


def evaluate(model, loader, charset, device) -> Dict:
    model.eval()
    exact = total = 0
    with torch.no_grad():
        for imgs, _t, _l in loader:
            logits = model(imgs.to(device))
            preds = logits.argmax(-1).permute(1, 0)
            for b, p in enumerate(preds):
                hyp = decode(p.tolist(), charset)
                gt = loader.dataset.texts[total]
                exact += int(hyp == gt)
                total += 1
    return {"lines": total, "exact_match": (exact / total) if total else 0.0}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--staging", action="append", required=True)
    ap.add_argument("--init", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=int, default=24)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--aug-per", type=int, default=3,
                    help="xheavy-augmented copies per training crop")
    ap.add_argument("--val-frac", type=float, default=0.1)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    ck = torch.load(args.init, map_location="cpu", weights_only=False)
    charset = list(ck["charset"])
    in_h, in_w = int(ck.get("in_h") or 48), int(ck.get("in_w") or 512)
    images, texts, dropped = load_staging(args.staging, charset)
    print(f"loaded {len(texts)} crops ({dropped} dropped by charset filter)",
          flush=True)

    rng = np.random.default_rng(args.seed)
    order = rng.permutation(len(texts))
    n_val = max(1, int(len(texts) * args.val_frac))
    val_idx = set(order[:n_val].tolist())

    tr_imgs: List[np.ndarray] = []
    tr_txt: List[str] = []
    for i, (img, txt) in enumerate(zip(images, texts)):
        if i in val_idx:
            continue
        tr_imgs.append(img)
        tr_txt.append(txt)
        for _ in range(max(0, args.aug_per)):
            tr_imgs.append(augment_line(img, rng, level="xheavy"))
            tr_txt.append(txt)
    va_imgs = [images[i] for i in sorted(val_idx)]
    va_txt = [texts[i] for i in sorted(val_idx)]
    print(f"train {len(tr_txt)} (aug x{args.aug_per + 1}) | val {len(va_txt)}",
          flush=True)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = CRNN(n_classes=len(charset), hidden=256, in_h=in_h).to(device)
    model.load_state_dict(ck["model"])
    print(f"initialized from {args.init} (epoch {ck.get('epoch')})", flush=True)

    dl_tr = DataLoader(_DS(tr_imgs, tr_txt, charset, in_h, in_w),
                       batch_size=args.batch, shuffle=True, collate_fn=_collate,
                       num_workers=0, drop_last=len(tr_txt) >= args.batch)
    dl_va = DataLoader(_DS(va_imgs, va_txt, charset, in_h, in_w),
                       batch_size=args.batch, shuffle=False,
                       collate_fn=_collate, num_workers=0)

    opt = torch.optim.AdamW(model.parameters(), lr=args.lr)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt,
                                                       T_max=max(1, args.epochs))
    ctc = nn.CTCLoss(blank=0, zero_infinity=True)

    os.makedirs(args.out, exist_ok=True)
    history = []
    t0 = time.time()
    best = None
    for epoch in range(args.epochs):
        model.train()
        losses = []
        for imgs, targets, lens in dl_tr:
            logits = model(imgs.to(device))
            input_lens = torch.full((imgs.shape[0],), logits.shape[0],
                                    dtype=torch.long)
            loss = ctc(logits, targets, input_lens, lens)
            if not torch.isfinite(loss):
                opt.zero_grad(set_to_none=True)
                continue
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            opt.step()
            losses.append(float(loss.item()))
        val = evaluate(model, dl_va, charset, device)
        rec = {"epoch": epoch + 1,
               "loss": float(np.mean(losses)) if losses else None,
               **val, "seconds": round(time.time() - t0, 1)}
        history.append(rec)
        print(f"epoch {epoch + 1}/{args.epochs} loss "
              f"{rec['loss']:.3f} val_exact {val['exact_match']:.3f} "
              f"({rec['seconds']}s)", flush=True)
        payload = {"model": model.state_dict(), "charset": charset,
                   "in_h": in_h, "in_w": in_w, "epoch": epoch + 1}
        torch.save(payload, os.path.join(args.out, "ckpt.pt"))
        if best is None or val["exact_match"] > best:
            best = val["exact_match"]
            torch.save(payload, os.path.join(args.out, "ckpt_best.pt"))
        sched.step()
        with open(os.path.join(args.out, "metrics.json"), "w") as f:
            json.dump({"history": history, "charset_size": len(charset),
                       "train": len(tr_txt), "val": len(va_txt),
                       "device": str(device)}, f, indent=2)
    print(f"done in {time.time() - t0:.0f}s; best val_exact {best:.3f}",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
