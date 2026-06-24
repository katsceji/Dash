# Tycheos Credit Benchmark Studio

Monte Carlo benchmark of the **Tycheos €510M / 25-deal book** (from
`Fund_deployment_model_11jun2026.xlsx`) against the **full 17-name US comparable book**
(Perceptive · Hercules · OrbiMed · Catalio · RA Capital), built from the Tycheos
comparable-fund memo.

**Design:** two genuinely different books through one engine. The IRR/return delta decomposes
into selection (geography/assets), structuring (terms) and exit mix — not a fee gap on
identical assets.

## Three layers
1. **Strategy** — IRR / MOIC / loss distributions, both books.
2. **Return bridge** — side by side: your deck base case (12 / 3 / 5 → 20 gross → 18 net) vs the
   model's bottom-up legs from the €510M book. The gap is the equity kicker.
3. **Attribution** — benchmark IRR → Tycheos IRR, one driver at a time (selection / structuring /
   workout / collateral / selection edge). Every edge is independently stress-testable.

## Credibility anchor
The engine reproduces the memo's verified portfolio EL (**11.2% / ~$110M on $986M**) and book
default rate (**~27%**) *before* Tycheos is added. Per-name PD/EL are verified memo inputs;
recovery is backed out of EL, so the risk side reconciles by construction.

## Base case (current defaults)
| | Deck base case | Model bottom-up | US benchmark |
|---|---|---|---|
| Net IRR | 18.0% | ~12.7% | 10.0% |
| Loss rate | — | 5.3% | 11.2% |

The deck's 18% is achievable but sits above the model base case; closing the gap needs the
M&A/Public-weighted exit tail (Abivax-style 5–6× warrants) or higher warrant coverage. EUR
caveat: at EUR base rates the 12% cash leg is ~1pp lighter than the deck's USD-implied figure.

## Notes / assumptions to refine
- Sector→PD: Medtech≈MedTech (0.12), Diagnostic≈Dx (0.22), Biotech 0.30, Healthtech 0.16
  (Biotech/Healthtech interpolated — not well-diligenced US clusters).
- Exit routes and warrant economics are **not** in the deployment model — assigned by sector and
  flagged. Replace with real per-deal exit/warrant terms when available.
- Model inputs are 11% coupon / 1.3% fees (conservative variant); base case uses the 12/3/5 steer.

## Run
```bash
pip install -r requirements.txt
streamlit run app.py
```
`engine.py` is pure NumPy and unit-testable headless. For Streamlit Community Cloud, push
`app.py`, `engine.py`, `requirements.txt` to a GitHub repo and point the app at `app.py`.
