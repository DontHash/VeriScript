# OCR pricing research - verified 2026-10-10

Purpose: the cost comparisons used by the launch copy and the "State of
Devanagari OCR" report. **Every figure was read on 2026-10-10** from the
vendor's own pricing page where it renders statically; where a page renders
prices dynamically, the figure is marked *(3p-verified)* = third-party page
that states it re-read the official rate card. USD, US list rates unless
noted. Vendor prices move: re-check before quoting.

**What this document is not:** it contains **no cloud accuracy claims**. We
did not benchmark cloud APIs on our frozen sets - Gemini-2.5-Pro is the
ground-truth *anchor* for the PDF set, so scoring it against its own
annotation would be circular. Accuracy numbers live in `BENCHMARK.md`
(measured arms only, with CIs).

## 1. Cloud, per 1,000 pages (published rates)

| Vendor | Feature | $ / 1k pages | Volume tier | Source (accessed 2026-10-10) |
|---|---|---|---|---|
| AWS Textract | Detect Document Text (plain OCR) | **1.50** | 0.60 above 1M/mo | <https://aws.amazon.com/textract/pricing/> |
| AWS Textract | Analyze Document: Layout | 4.00 | 3.00 above 1M | *(3p-verified)* <https://receiptocr.ai/blog/aws-textract-pricing> |
| AWS Textract | Analyze Document: Tables | 15.00 | 10.00 above 1M | <https://aws.amazon.com/textract/pricing/> |
| AWS Textract | Analyze Expense (invoices) | 10.00 | 8.00 above 1M | <https://aws.amazon.com/textract/pricing/> |
| AWS Textract | Forms | 50.00 | 40.00 above 1M | <https://aws.amazon.com/textract/pricing/> |
| AWS Textract | Forms + Tables + Queries | 70.00 | 55.00 above 1M | <https://aws.amazon.com/textract/pricing/> |
| Google Cloud Vision | DOCUMENT_TEXT_DETECTION | 1.50 | first 1k/mo free; 0.60 above 5M | <https://cloud.google.com/vision/pricing> |
| Google Document AI | Enterprise Document OCR | 1.50 | 0.60 above 5M | <https://cloud.google.com/document-ai> |
| Google Document AI | Layout Parser | 10.00 | - | <https://cloud.google.com/document-ai> |
| Google Document AI | Form Parser / Custom Extractor | 30.00 | 20.00 above 1M | <https://cloud.google.com/document-ai> |
| Google Document AI | OCR add-ons (math/font detection) | 6.00 | - | <https://cloud.google.com/document-ai> |
| Azure AI Document Intelligence | Read (OCR) | 1.50 | 0.60 above 1M; F0 free tier 500 pages/mo (first 2 pages/doc) | <https://azure.microsoft.com/en-us/pricing/details/document-intelligence/> |
| Azure AI Document Intelligence | Layout / Prebuilt models | 10.00 | commitment tiers exist | same (official rate-card text; page renders prices dynamically) |
| Azure AI Document Intelligence | Custom extraction | 30.00 | 20.00 above 1M, 18.00 committed | same |
| Mistral | OCR 4.1 (per page, annotated 5.00) | 4.00 | batch 50% -> **2.00** | <https://docs.mistral.ai/models/mistral-ocr-latest>, <https://mistral.ai/news/ocr-4> |
| Mistral | OCR 3 (previous gen) | 2.00 | batch 1.00 | <https://aisotools.com/pricing/mistral-ocr-3> |

Notes that change real bills: AWS/Google/Azure all list **1.50 per 1,000
pages for plain text** - reading text is a commodity; the 10-70x jump is for
structure (tables, forms, layout). Free tiers exist (AWS 3 months for new
accounts; Google 1k units/mo on Vision; Azure F0). Azure Document
Intelligence **containers run on your own hardware at the same per-page
price** plus your infrastructure (<https://learn.microsoft.com/azure/ai-services/document-intelligence/service-limits>)
- the nearest thing to an on-premises option among the majors.

## 2. Desktop licenses (the offline peer class)

| Product | Price | Notes | Source |
|---|---|---|---|
| ABBYY FineReader PDF Standard | **$99 / year / seat** | 1 standalone license | <https://pdf.abbyy.com/pricing> |
| ABBYY FineReader PDF Corporate | **$165 / year / seat** | includes automated conversion **up to 5,000 pages/month** | same |
| ABBYY FineReader PDF for Mac | $69 / year / seat | macOS build | same |
| ABBYY volume licensing | min. 5 seats, quote | per-seat / remote / concurrent / site (50+) | <https://pdf.abbyy.com/licensing/pricing> |
| CDW street price (Standard) | $73.99-91.99 / year | corroboration | <https://www.cdw.com/product/7199331> |

The 5,000 pages/month conversion cap on Corporate matters at archive scale:
100,000 pages is a multi-month or multi-seat job even after the license.

## 3. Free / open (license $0; cost = engineering + review)

| Option | License | Measured caveat (our bake-off, `BENCHMARK.md`) |
|---|---|---|
| Tesseract 5 (nep) | Apache-2.0 | page CER 0.353 (beats our engine raw) but invents **5,080 tokens / 532 digit tokens** on 69 letterpress pages - fails the honesty gate |
| OCRmyPDF | MPL-2.0 | wraps Tesseract; same behaviour |
| PaddleOCR 3.x full pipeline | Apache-2.0 | 0.662 CER at 21.8 s/page CPU on the hard-10 table slice (worse than its own raw engine at 0.530) |
| Raw RapidOCR engine | Apache-2.0 | 0.530 hard-10 CER; no queue, no trust layer |

## 4. Self-hosted VeriScript (this project)

License $0 (MIT code, Apache-2.0 engine). The only recurring cost is
compute you already own or rent. Model - with assumptions explicit:

- Warm throughput on the public demo (1 vCPU): **~8-10 s/page** end-to-end
  (`deploy/gcp-cloudrun.md`, measured). A 4 GB laptop GPU runs the hard-10
  table slice at 7.3 s/page.
- A $20/month 1-vCPU instance saturated = ~290k pages/month; at 5%
  utilisation = ~14.5k pages/month; at 1% = ~2.9k pages/month.

| Volume | Compute basis | Cost/page |
|---|---|---|
| 5,000 pages/mo | $20 instance even at 1% use; or an existing office PC ($0 marginal) | **$0.004** (worst case) - **$0** on owned hardware |
| 50,000 pages/mo | $20 instance at ~35% use | **$0.0004** |
| 100,000 pages, one-off | ~250 h of one instance (10.4 days) pro-rata | **~$7** of instance time, or overnight batches on a desktop |

No meter, no egress, no retention fee, no per-seat license, and the review
queue ships with it.

## 5. Worked comparisons - "what it normally costs"

**A. Small office, 5,000 register pages/month, digits must be trusted.**

| Option | Monthly list cost | What you still don't get |
|---|---|---|
| Cloud raw OCR (Textract/Google/Azure Read) | $7.50 | No structure, no digit trust, no review queue; data leaves |
| Cloud layout/tables (register-shaped) | $50-75 | Structure yes; digit trust and review still on you |
| Mistral OCR 4.1 (batch) | $10-20 | Best structure-per-dollar of the cloud rows; data leaves |
| ABBYY Corporate, 1 seat | $13.75/mo | Fits the 5,000-page cap; offline; no digit queue |
| This project, on an office PC | **$0** | - |

**B. Court archive, 100,000 pages, one-off.**

| Option | One-off list cost | Hidden work |
|---|---|---|
| Cloud plain text | $150 | You build structure + digit verification yourself |
| Cloud layout/tables | $1,000-1,500 | Same, minus layout |
| Mistral OCR 4.1 batch | $200 | Data leaves |
| ABBYY | >= $275/yr in seats (5k/mo cap) - or ~20 months with one seat | Operational |
| This project | **~$0-10 of compute** on hardware you own | Human review (below) |

**C. The cost line nobody advertises: human review.** Our measured,
digit-first queue is **~3.9 tokens/page** (v2, was 7.8 before the split) and
**~4.4/page** on letterpress (was 10.0) - Appendix AO. On 100k pages that is
~400k confirmations instead of ~800k. Cloud and desktop vendors do not
price this line; the queue exists to halve it. We deliberately do not
dollarise wages here (no sourced rate).

**D. Privacy-mandated buyers (courts, land offices, health).** The cloud
rows require a legal basis before price even applies; Azure containers
(customer-run, same per-page price + your infra) are the nearest official
mitigation among the majors; self-hosting carries no such gate.

## 6. Caveats

- List prices only; commitment/volume discounts exist and are not modelled.
- Enterprise IDP suites (sales-quoted) are out of scope here.
- Regional pricing differs (e.g. Azure China lists in CNY at different
  rates); we quote US rates.
- Withdrawn claims kept out: a Microsoft Q&A answer circulating in search
  results contains incorrect Document Intelligence figures ($300+/1k for
  custom extraction); the official rate card says $30.
- Reproduce: every URL above, accessed 2026-10-10; pages marked
  *(3p-verified)* state they re-read the official rate card on the date
  shown there.
