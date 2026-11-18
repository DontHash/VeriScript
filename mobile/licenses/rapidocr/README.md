# OCR component notices

The native experimental backend in `RapidOcr.kt` was written for VeriScript to reproduce the public RapidOCR 3.9.2 inference stages. Its DB rectangle expansion is an approximation of the upstream polygon offset; it does not claim bitwise parity.

- RapidOCR: https://github.com/RapidAI/RapidOCR/tree/v3.9.2 (Apache-2.0).
- PaddleOCR models: https://github.com/PaddlePaddle/PaddleOCR (Apache-2.0); pinned artifact URLs and hashes are in `mobile/rapidocr-models.json`.
- ONNX Runtime: https://github.com/microsoft/onnxruntime/tree/v1.24.3 (MIT).

The corresponding upstream license texts are preserved alongside this file and copied into Android assets by `prepare_rapidocr.py`. They must accompany redistribution.
