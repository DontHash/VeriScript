# Devanagari / Nepali OCR landscape (web research, 2026-10-10)

Purpose: the direct-competitor map for the launch copy and the "State of
Devanagari OCR" report. Every entry has its source at the bottom; all pages
were accessed **2026-10-10**. Vendor claims are marked as claims.

## 1. Free online tools - the crowded, conversion-only bottom

| Tool | Price | What it is | Nepali | Verification / queue | Offline |
|---|---|---|---|---|---|
| i2ocr | Free | Online OCR page | yes | none | no |
| olocr | Free | Online OCR page | yes | none | no |
| TextGens | Free, no signup | Online OCR page | yes | none | no |
| NewOCR | Free | Tesseract 5, 122 languages | yes | none | no |
| OnlineOCR.net | Free | Online OCR | yes | none | no |
| OCR.space | Free tier + API | Cloud OCR API, popular free tier | 100+ langs | none | no |
| SimpleOCR | Free | "Tesseract-based" online OCR | yes | none | no |
| Google Drive / Lens | Free | Consumer OCR | yes (Devanagari) | none | no |

**Finding:** a dense field of conversion pages; **none publishes accuracy for
Nepali, none re-reads or flags digits, and all of them ship your document to
someone's server.** Several are Tesseract under the hood - we have measured
what that means on letterpress (0.353 page CER but **5,080 invented tokens**
on 69 pages, `BENCHMARK.md`).

## 2. The government platform: Bhashini (India)

- Bhashini's OCR services list **Nepali** among supported Indic languages
  (IIIT-H / AI4Bharat models); ULCA APIs are free for registered developers
  (India-centric onboarding), and bhashini.ai sells an on-prem enterprise
  tier.
- It is an **API platform**, not a document pipeline: no review queue, no
  alternative readings, no digit honesty, no searchable-PDF/correction loop.

**Finding:** the most credible free alternative where it is available, and a
validation that Indic-language AI matters at the national level. It
complements a trust layer rather than replacing one.

## 3. Open-source engines (what everyone builds on)

| Engine | License | Devanagari evidence | Our measurements (frozen sets) |
|---|---|---|---|
| RapidOCR (PP-OCRv5 deva mobile) | Apache-2.0 | PaddleOCR claims 84.96% devanagari rec on their internal set | hard-10 CER 0.530; letterpress 0.4335 |
| PaddleOCR 3.x full pipeline | Apache-2.0 | PP-OCRv6 (2026-05); PaddleOCR-VL-1.5 claims 94.5% OmniDocBench v1.5 | hard-10 CER 0.662 at 21.8 s/page CPU (worse than its own raw engine) |
| Tesseract 5 (nep) | Apache-2.0 | academic: +preprocessing 94.8/71.2/51.2% "accuracy" on high/med/low images (private set) | **5,080 invented tokens** on 69 letterpress pages - fails the honesty bar |
| Surya OCR 2 (650M) | code Apache-2.0; **weights OpenRAIL-M (free <$5M)** | olmOCR-bench 83.3%; Hindi 82.2% (vendor) | hard-10 CER 0.166 at **172 s/page**; 82 invented tokens |
| EasyOCR / DocTR / TrOCR | mixed | community comparisons: EasyOCR 72.1% char accuracy vs Google Vision 94.2% vs Tesseract 43.7% on one answer-sheet dataset | TrOCR decisively loses on print (1.04 CER, hallucinates) |

**Finding:** glyph recognition is a commodity; the published Nepali numbers
that exist are **private-dataset, non-reproducible, and without confidence
intervals** (the academic work we found: Tesseract+preprocessing percentages,
an ANN paper at 81% test, a Tribhuvan University thesis on *handwritten*
Nepali - a different problem). Nobody publishes page-level Devanagari/Nepali
CER with CIs and alternative readings. That gap is still ours.

## 4. Commercial IDP and cloud APIs - the expensive middle

| Service | Price | Devanagari-first? | Verification | Offline |
|---|---|---|---|---|
| Google Vision / Document AI | $1.50/1k pages text; $10-30 structure | no (generic) | confidence only | no |
| AWS Textract | $1.50/1k text; $10-70 structure | **not supported** (English + 6 Latin languages) | confidence only | no |
| Azure Doc Intelligence | $1.50/1k Read; $10-30 structure | generic; containers on-prem at same price | confidence only | containers only |
| Mistral OCR 4.1 | $4/1k ($2 batch) | generic VLM-class | confidence only | no |
| Mindee / Nanonets / Klippa-Doxis / Docsumo / Rossum | free tiers then EUR/USD subscriptions; Nanonets ~$0.30/page block-based; Docsumo $299/mo for 1k pages; enterprise quotes | invoice/workflow-first, Latin-first | workflow review, not digit-trust | mostly no |
| ABBYY FineReader PDF | $99 / $165 per seat/year (Corporate caps 5,000 automated pages/mo) | no | consumer-grade review only | **yes** |

**Finding:** commercial money is in invoices and workflows, cloud-first, and
nobody in it advertises-devanagari-first error visibility. See
`PRICING_RESEARCH.md` for the full referenced price tables.

## 5. Where VeriScript sits (honest read)

**Wins, evidenced:**

1. **No other tool in this landscape ships digit verification with
   alternative readings for Devanagari** - a rank-1 review queue that keeps
   **27 of 29 audited real errors in the top-10 (0.93)** on a frozen set
   (Appendix AQ), with precision doubled by the digits-vs-text split
   (Appendix AO).
2. **Offline by default and provable**: courts/land records/health cannot
   send documents to any of the cloud rows above; ABBYY is the only known
   offline peer and it is per-seat with a 5k-page cap.
3. **Published, reproducible numbers**: frozen manifests, hash checks, CIs,
   kept negative results - while the competition publishes percentages on
   private data, if anything.
4. **Cost**: $0-0.004/page self-hosted; no meter, no per-seat, no retention.

**Loses, honestly:**

1. **Recognizer accuracy is mid-field.** VLM-class reads table-heavy pages
   better (Surya 0.166 CER) - at ~23x our page time and a weights licence
   that gates commercial use; closed VLMs at 150+ s/page with invented
   tokens. On clean English/Devanagari tables a VLM will look better.
2. **Handwriting: out of scope**, and the TU thesis + the
   r/technepal thread show demand there.
3. **Real phone photos: pending** real ground truth; only proxy numbers so
   far.
4. **Zero adoption so far** - no launch, no users; the demo is offline while
   hosting is sorted. A product's quality is only half the story; the other
   half is people knowing it exists.

**Demand signal:** a 2026 r/technepal thread asks specifically for a
**local (offline) Nepali OCR** for handwritten/citizen documents - exactly
the niche, in the exact community. The free-tool market is crowded at the
conversion end and empty at the trust end.

## Sources (all accessed 2026-10-10)

- Free tools: <https://www.i2ocr.com/free-online-nepali-ocr>,
  <https://olocr.com/nepali-ocr>, <https://textgens.com/niche-tools/nepali-ocr-tool>,
  <https://www.newocr.com>, <https://www.onlineocr.net>,
  <https://www.simpleocr.com/tag/nepali-ocr>, <https://ocr.space>
- Bhashini: <https://dibd-bhashini.gitbook.io/bhashini-apis/available-models-for-usage>,
  <https://bhashini.ai>
- Open source: <https://imagetotable.ai/blog/best-open-source-ocr-tools-2026>,
  <https://modal.com/blog/8-top-open-source-ocr-models-compared>,
  <https://reducto.ai/guides/best-ocr-models-accuracy-speed-cost>,
  <https://www.eklavvya.com/blog/best-ocr-answersheet-evaluation>
- Academic (Nepali): <https://zenodo.org/records/4361896>,
  <https://elibrary.tucl.edu.np/bitstreams/ce94b273-13bd-4ec8-99d3-ce9509fcd512/download>,
  <https://arxiv.org/html/2407.04577v3>
- Commercial IDP: <https://soceton.com/blogs/document-ai-ocr-pricing-comparison>,
  <https://www.erpresearch.com/erp-add-ons/ocr/mindee-vs-nanonets>,
  <https://www.klippa.com/en/blog/information/alternatives-to-nanonets>
- Demand: <https://www.reddit.com/r/technepal/comments/1r11zo9/local_llm_or_ocr_that_can_read_nepali_handwritten>
