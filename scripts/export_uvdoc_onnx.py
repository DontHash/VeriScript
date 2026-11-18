"""Export UVDoc to ONNX for the studio and the phone (docs/TECH_UPGRADE_PLAN.md F1).

The desktop server build leaves PyTorch out, and the phone has only ONNX
Runtime, so flattening ships as ONNX there. This converts the checked
checkpoint (docs/EXTERNAL_ASSETS.md; loaded with weights_only=True) once:

* data/external/uvdoc/model/uvdoc.onnx       float32, for the desktop;
* mobile/android/app/src/main/assets/uvdoc/uvdoc_fp16.onnx
                                              weights stored as float16 and
                                              cast to float32 on load (half
                                              the APK size, float32 maths).

Only the grid output (1, 2, 45, 31) is kept; the 3D head is dropped.
Both files are checked against PyTorch on DocUNet photos before writing the
manifest (max grid difference in pixels at 2000 px).

python scripts/export_uvdoc_onnx.py
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DESKTOP = os.path.join(ROOT, "data", "external", "uvdoc", "model", "uvdoc.onnx")
PHONE_DIR = os.path.join(ROOT, "mobile", "android", "app", "src", "main", "assets", "uvdoc")
PHONE = os.path.join(PHONE_DIR, "uvdoc_fp16.onnx")


def _fp16_weights(model):
    """float32 initializers -> float16 + a Cast back to float32."""
    import onnx
    from onnx import helper, numpy_helper

    graph = model.graph
    casts, keep = [], []
    for init in graph.initializer:
        if init.data_type != onnx.TensorProto.FLOAT or np.prod(init.dims) < 1024:
            keep.append(init)
            continue
        half = numpy_helper.from_array(numpy_helper.to_array(init).astype(np.float16),
                                       init.name + "_fp16")
        keep.append(half)
        casts.append(helper.make_node("Cast", [half.name], [init.name], to=onnx.TensorProto.FLOAT,
                                      name=init.name + "_cast"))
    del graph.initializer[:]
    graph.initializer.extend(keep)
    nodes = list(graph.node)
    del graph.node[:]
    graph.node.extend(casts + nodes)
    return model


def main() -> None:
    import cv2
    import onnx
    import onnxruntime as ort
    import torch

    from veriscript.document import dewarp

    net = dewarp._load()  # noqa: SLF001 - the checked loader

    class GridOnly(torch.nn.Module):
        def __init__(self, inner):
            super().__init__()
            self.inner = inner

        def forward(self, x):
            return self.inner(x)[0]

    w, h = dewarp.INPUT_SIZE
    dummy = torch.zeros(1, 3, h, w)
    os.makedirs(os.path.dirname(DESKTOP), exist_ok=True)
    torch.onnx.export(GridOnly(net).eval(), dummy, DESKTOP, input_names=["image"],
                      output_names=["grid"], opset_version=17, dynamo=False)
    model = onnx.load(DESKTOP)
    onnx.checker.check_model(model)
    os.makedirs(PHONE_DIR, exist_ok=True)
    onnx.save(_fp16_weights(model), PHONE)
    onnx.checker.check_model(onnx.load(PHONE))

    worst = {}
    photos = sorted(glob.glob(os.path.join(ROOT, "data", "external", "docunet", "crop", "*.png")))[:12]
    for path in (DESKTOP, PHONE):
        sess = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        diff = 0.0
        for p in photos:
            img = cv2.imread(p)
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
            x = np.ascontiguousarray(
                cv2.resize(rgb, dewarp.INPUT_SIZE, interpolation=cv2.INTER_AREA).transpose(2, 0, 1)[None])
            with torch.no_grad():  # the PyTorch reference, not dewarp's ONNX path
                ref = net(torch.from_numpy(x))[0].numpy()
            out = sess.run(None, {"image": x})[0]
            diff = max(diff, float(np.abs(out - ref).max()) / 2 * 2000)
        worst[os.path.basename(path)] = round(diff, 3)
    manifest = {
        "source": "UVDoc best_model.pkl, github.com/tanguymagne/UVDoc @ 4c9b82b (MIT)",
        "input": {"name": "image", "shape": [1, 3, h, w], "rgb": "0..1 float, INTER_AREA"},
        "output": {"name": "grid", "shape": [1, 2, 45, 31], "range": "[-1, 1], align_corners"},
        "max_grid_difference_px_at_2000": worst,
        "files": {os.path.relpath(p, ROOT).replace(os.sep, "/"):
                  hashlib.sha256(open(p, "rb").read()).hexdigest() for p in (DESKTOP, PHONE)},
        "bytes": {os.path.basename(p): os.path.getsize(p) for p in (DESKTOP, PHONE)},
    }
    with open(os.path.join(PHONE_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
    print(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
