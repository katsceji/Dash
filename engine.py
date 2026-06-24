"""
engine.py — Tycheos Health Capital
Venture / growth-debt benchmark engine.

Design principle (LP-credible):
  * BENCHMARK = the real 17-name US comparable book from the Tycheos comparable-fund
    memo (SS13.4). Reduced-form credit model: per-name PD and expected loss (EL) are
    CALIBRATION INPUTS taken from verified Q1-2026 diligence, so the book reconciles to
    the memo by construction. Recovery is BACKED OUT from EL = PD x LGD x drawn.
    Portfolio EL / loss-rate / return distribution are EMERGENT and checked against the
    memo's published portfolio numbers (SS13.5).
  * SUBJECT = an illustrative European PRIVATE book (25 names, Stage & Exit slide).
    Base risk is anchored to the US empirical cluster means (SS17 shrunk PDs); only the
    CLAIMED Tycheos edges are layered on top, each as an explicit, stress-testable toggle.
    Exit route (Repayment / Refinancing / M&A / Public) drives warrant-kicker realisation.

Two genuinely different books, one engine. The IRR/return delta therefore decomposes into
selection (geography/assets), structuring (terms), and exit mix — not a manufactured fee gap.

No Streamlit dependency here so the engine can be unit-tested headless.
"""

import numpy as np

DT = 0.25  # quarterly steps

# ----------------------------------------------------------------------------------------
# 1. US COMPARABLE BOOK — 17 positions, calibrated to memo SS13.4 (PD, EL, drawn, cluster)
#    rate / mat_q for the 7 Perceptive names from SS3 & SS6.1; cross-fund tenors/coupons are
#    defensible 2.5-4y IO-bullet assumptions (memo does not disclose per-name terms for these
#    10 names — flagged transparently in the reconciliation panel).
#    recovery_mean is DERIVED so that PD * (1-recovery) * drawn == memo EL  (reconciles exactly).
# ----------------------------------------------------------------------------------------
US_BOOK = [
    # name,    cluster,           drawn, rate,    mat_q, pd,    el,    exit
    ("BDSX",  "Dx",               40.0, 0.1325,   6,  0.138,  2.5, "Refinancing"),
    ("XGN",   "Dx",               25.0, 0.1175,  16,  0.088,  1.1, "Refinancing"),
    ("APYX",  "MedTech",          37.5, 0.1200,  10,  0.263,  3.7, "Refinancing"),
    ("STIM",  "MedTech",          50.0, 0.1175,  12,  0.192,  3.6, "Refinancing"),
    ("TRIB",  "Dx",               55.0, 0.1050,   3,  0.940, 29.7, "Repayment"),
    ("KEST",  "MedTech",          70.0, 0.1125,   8,  0.327, 10.3, "Refinancing"),
    ("MGTX",  "GeneTx",           30.0, 0.1325,   2,  0.000,  0.0, "M&A"),
    ("MLTX",  "ImmunoBinary",     99.0, 0.1200,  13,  0.379, 16.9, "Refinancing"),
    ("VRDN",  "ImmunoBinary",    150.0, 0.1150,  13,  0.177, 11.3, "Refinancing"),
    ("LXRX",  "SpecialtyPharma",  55.0, 0.1200,  12,  0.173,  4.5, "Repayment"),
    ("DYN",   "GeneTx",          100.0, 0.1150,  14,  0.000,  0.0, "Refinancing"),
    ("SENS",  "MedTech",          55.0, 0.1250,  12,  0.017,  0.4, "Repayment"),
    ("ENGN",  "GeneTx",           25.0, 0.1250,  12,  0.399,  5.7, "Refinancing"),
    ("AVITA", "MedTech",          55.0, 0.1200,  10,  0.086,  2.2, "Refinancing"),
    ("LEOCC", "MedTechSmall",     20.0, 0.1300,  12,  0.631,  6.0, "Repayment"),
    ("AMLRX", "DigitalHealth",    20.0, 0.1300,  12,  0.662,  6.9, "Repayment"),
    ("SPRY",  "SpecialtyPharma", 100.0, 0.1150,  13,  0.130,  5.5, "Refinancing"),
]

# ----------------------------------------------------------------------------------------
# 2. SHRUNK CLUSTER PDs (memo SS17.2) — empirical anchor for the EU book's base risk.
# ----------------------------------------------------------------------------------------
SHRUNK_CLUSTER_PD = {
    "Dx": 0.297, "MedTech": 0.102, "GeneTx": 0.692, "ImmunoBinary": 0.276,
    "SpecialtyPharma": 0.163, "MedTechSmall": 0.456, "DigitalHealth": 0.470, "Biotech": 0.350,
}

# Warrant-kicker realisation by exit route (fraction of full warrant coverage monetised).
KICKER_REAL = {"Repayment": 0.15, "Refinancing": 0.55, "M&A": 1.00, "Public": 1.00,
               "Repayment/M&A": 0.60}

# ----------------------------------------------------------------------------------------
# 3. TYCHEOS EU BOOK — the 25 deals from Fund_deployment_model_11jun2026.xlsx (real sizes,
#    sectors, countries, IO periods). EUR510M deployed, avg EUR20.4M ticket, EUR30M max.
#    Model inputs: interest 11%, fees 1.3% (conservative variant). Base case per ED steer:
#    12% cash / 3% fees / 5% kicker -> 20% gross; +2 leverage / -4 costs -> 18% net.
#
#    Sector -> base PD anchored to US comparable clusters (memo SS17): Medtech ~= MedTech
#    (0.12); Diagnostic ~= Dx, interpolated down for commercial Dx (0.22); Biotech (clinical,
#    secured-IO) ~0.30; Healthtech interpolated (0.16) — NOT a well-diligenced US cluster, so
#    flagged. Exit routes are assigned by sector (the deployment model has no exit/warrant data).
#    Fields: (deal, sector_cluster, country, drawn EURm, IO_months, exit_route)
# ----------------------------------------------------------------------------------------
SECTOR_BASE_PD = {"Biotech": 0.30, "MedTech": 0.12, "Dx": 0.22, "Healthtech": 0.16}
SECTOR_OF = {"Biotech": "Biotech", "Medtech": "MedTech",
             "Diagnostic": "Dx", "Healthtech": "Healthtech"}

EU_DEALS = [
    # deal, sector(model), country, drawn, IO_months, exit_route
    ("Deal 1",  "Medtech",    "EU",    15.0, 12, "Refinancing"),
    ("Deal 2",  "Medtech",    "UK",    20.0, 12, "M&A"),
    ("Deal 3",  "Biotech",    "EU",    25.0, 18, "Refinancing"),
    ("Deal 4",  "Healthtech", "EU",     5.0, 12, "Repayment"),
    ("Deal 5",  "Biotech",    "Other", 20.0, 18, "Refinancing"),
    ("Deal 6",  "Biotech",    "UK",    30.0, 12, "M&A"),
    ("Deal 7",  "Healthtech", "Other",  5.0, 18, "M&A"),
    ("Deal 8",  "Medtech",    "EU",    25.0, 12, "Refinancing"),
    ("Deal 9",  "Biotech",    "EU",    20.0,  6, "Refinancing"),
    ("Deal 10", "Diagnostic", "EU",    10.0, 12, "Repayment"),
    ("Deal 11", "Biotech",    "EU",    30.0,  9, "Refinancing"),
    ("Deal 12", "Healthtech", "EU",    20.0, 12, "Refinancing"),
    ("Deal 13", "Medtech",    "UK",    10.0, 15, "Repayment"),
    ("Deal 14", "Biotech",    "EU",    20.0,  6, "Repayment"),
    ("Deal 15", "Medtech",    "Other", 15.0, 12, "M&A"),
    ("Deal 16", "Biotech",    "EU",    30.0, 12, "Refinancing"),
    ("Deal 17", "Healthtech", "EU",    20.0,  6, "Repayment"),
    ("Deal 18", "Biotech",    "EU",    30.0, 12, "M&A"),
    ("Deal 19", "Healthtech", "EU",    15.0, 12, "M&A"),
    ("Deal 20", "Medtech",    "EU",    30.0, 24, "Repayment"),
    ("Deal 21", "Medtech",    "Other", 25.0, 18, "Refinancing"),
    ("Deal 22", "Diagnostic", "UK",    25.0, 12, "Refinancing"),
    ("Deal 23", "Medtech",    "EU",    30.0, 12, "M&A"),
    ("Deal 24", "Healthtech", "EU",    15.0,  6, "Repayment"),
    ("Deal 25", "Medtech",    "UK",    20.0,  6, "Repayment"),
]

# Base-case return targets (ED steer) and conservative model variant.
TYCHEOS_BASECASE = dict(coupon=0.12, fees_leg=0.03, kicker_leg=0.05, lev=0.02, costs=0.04)
MODEL_INPUTS = dict(coupon=0.11, fees=0.013)


# ----------------------------------------------------------------------------------------
# Correlation: cluster-based Gaussian copula (memo SS5 / SS11.4).
# ----------------------------------------------------------------------------------------
def _pair_rho(c1, c2):
    intra = {"Dx": 0.40, "MedTech": 0.35, "Biotech": 0.30, "Healthtech": 0.25,
             "ImmunoBinary": 0.35, "GeneTx": 0.35, "SpecialtyPharma": 0.25}
    if c1 == c2:
        return intra.get(c1, 0.30)  # intra-cluster
    return 0.20  # cross-cluster default


def build_corr(clusters):
    n = len(clusters)
    rho = np.eye(n)
    for i in range(n):
        for j in range(i + 1, n):
            rho[i, j] = rho[j, i] = _pair_rho(clusters[i], clusters[j])
    # nearest-PD safeguard so Cholesky always succeeds
    w, V = np.linalg.eigh(rho)
    w = np.clip(w, 1e-6, None)
    rho = V @ np.diag(w) @ V.T
    d = np.sqrt(np.diag(rho))
    rho = rho / np.outer(d, d)
    return np.linalg.cholesky(rho)


def _recovery_from_el(pd, el, drawn):
    if pd <= 0 or drawn <= 0:
        return 0.50  # moot — name does not default
    lgd = el / (pd * drawn)
    return float(np.clip(1.0 - lgd, 0.05, 0.90))


# ----------------------------------------------------------------------------------------
# EU book construction with explicit, toggleable Tycheos edges.
# ----------------------------------------------------------------------------------------
def build_eu_book(selection_edge=True, active_workout=True, ip_collateral=True, coupon=0.12):
    """EU book from the fund deployment model. coupon defaults to the 12% base-case steer
    (model input is 11% — pass coupon=0.11 for the conservative variant)."""
    book = []
    for deal, sector, country, drawn, io_m, exit_route in EU_DEALS:
        cluster = SECTOR_OF[sector]
        pd = SECTOR_BASE_PD[cluster]
        recovery = 0.50  # specialist secured baseline
        if selection_edge:      # smaller check vs runway -> lower default risk
            pd *= 0.85
        if active_workout:      # grace + cost-cut intervention
            pd *= 0.92
            recovery += 0.07
        if ip_collateral:       # IP-inclusive specialist collateral
            recovery += 0.10
        pd = float(np.clip(pd, 0.01, 0.95))
        recovery = float(np.clip(recovery, 0.05, 0.90))
        # total IO-bullet tenor ~= IO period + ~24m amortisation/bullet, in quarters
        mat_q = int(round((io_m + 24) / 3.0))
        book.append((deal, cluster, drawn, coupon, mat_q, pd, recovery, exit_route))
    return book


def _us_book_prepared():
    out = []
    for name, cluster, drawn, rate, mat_q, pd, el, exit_route in US_BOOK:
        rec = _recovery_from_el(pd, el, drawn)
        out.append((name, cluster, drawn, rate, mat_q, pd, rec, exit_route))
    return out


# ----------------------------------------------------------------------------------------
# Core reduced-form simulation. Returns dated portfolio cashflows + diagnostics.
#   terms = dict(upfront, backend, warrant, recovery_lag_q, warrant_dispersion)
#   book rows: (name, cluster, drawn, rate, mat_q, pd, recovery, exit_route)
# ----------------------------------------------------------------------------------------
def simulate(book, terms, N=10000, seed=42):
    rng = np.random.default_rng(seed)
    clusters = [r[1] for r in book]
    n = len(book)
    max_q = max(r[4] for r in book)

    L = build_corr(clusters)
    Z = rng.standard_normal((N, n)) @ L.T
    U = 0.5 * (1.0 + erf_approx(Z / np.sqrt(2.0)))  # standard-normal CDF -> correlated uniforms

    port = np.zeros((N, max_q + 1))
    defaults = np.zeros((N, n), dtype=bool)
    total_out = 0.0

    upfront = terms["upfront"]; backend = terms["backend"]; warr_cov = terms["warrant"]
    lag = terms.get("recovery_lag_q", 4); disp = terms.get("warrant_dispersion", 0.6)

    leg_cash = np.zeros(N)      # coupon income
    leg_kicker = np.zeros(N)    # warrant upside

    for idx, (name, cluster, drawn, rate, mat_q, pd, recovery, exit_route) in enumerate(book):
        outlay = drawn * (1.0 - upfront)
        total_out += outlay

        defd = U[:, idx] < pd
        defaults[:, idx] = defd
        # default timing: uniform over life, skewed slightly early for high-PD names
        skew = 0.5 + 0.5 * pd
        u_t = rng.random(N) ** skew
        def_q = np.maximum(1, np.ceil(u_t * mat_q)).astype(int)
        last_coupon_q = np.where(defd, def_q, mat_q)

        coupon = drawn * rate * DT
        qs = np.arange(1, mat_q + 1)
        alive = qs[None, :] <= last_coupon_q[:, None]          # (N, mat_q)
        name_cf = np.zeros((N, max_q + 1))
        name_cf[:, 1:mat_q + 1] += alive * coupon
        leg_cash += (alive * coupon).sum(axis=1)

        # recovery at default + workout lag
        if defd.any():
            rec_q = np.minimum(def_q + lag, max_q)
            rec_val = drawn * recovery * (0.85 + 0.30 * rng.random(N))  # dispersion around mean
            np.add.at(name_cf, (np.arange(N)[defd], rec_q[defd]), rec_val[defd])

        # maturity payoff for survivors: principal + backend + warrant (exit-route scaled)
        surv = ~defd
        if surv.any():
            real = KICKER_REAL.get(exit_route, 0.4)
            # warrant upside ~ coverage * drawn * realisation * lognormal multiple
            upside = np.exp(rng.normal(0.0, disp, N)) * real
            warrant = np.clip(warr_cov * drawn * upside, 0.0, warr_cov * drawn * 4.0)
            pay = drawn + drawn * backend + warrant
            name_cf[surv, mat_q] += pay[surv]
            leg_kicker += np.where(surv, warrant, 0.0)

        port += name_cf

    port[:, 0] = -total_out
    return dict(port=port, defaults=defaults, total_out=total_out,
                leg_cash=leg_cash, leg_kicker=leg_kicker, N=N, max_q=max_q)


# vectorised standard-normal CDF without scipy
def erf_approx(x):
    # Abramowitz & Stegun 7.1.26
    sign = np.sign(x); x = np.abs(x)
    t = 1.0 / (1.0 + 0.3275911 * x)
    y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t
               - 0.284496736) * t + 0.254829592) * t * np.exp(-x * x)
    return sign * y


# ----------------------------------------------------------------------------------------
# Vectorised IRR (bisection on quarterly rate, annualised). cf: (N, T+1), cf[:,0] < 0.
# ----------------------------------------------------------------------------------------
def vectorized_irr(cf, lo=-0.99, hi=2.0, iters=80):
    T = cf.shape[1]
    powers = np.arange(T)
    lo = np.full(cf.shape[0], lo); hi = np.full(cf.shape[0], hi)

    def npv(rate):
        disc = (1.0 + rate[:, None]) ** powers[None, :]
        return (cf / disc).sum(axis=1)

    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        v = npv(mid)
        pos = v > 0
        lo = np.where(pos, mid, lo)
        hi = np.where(pos, hi, mid)
    rq = 0.5 * (lo + hi)               # quarterly
    return (1.0 + rq) ** 4 - 1.0       # annualised


def summarize(res, label):
    port = res["port"]; N = res["N"]; out = res["total_out"]
    total_in = port[:, 1:].sum(axis=1)
    moic = total_in / out
    ret = moic - 1.0                                   # life-of-book total return on deployed
    irr = vectorized_irr(port)
    def_rate = res["defaults"].mean()
    losses = np.maximum(0.0, -(total_in - out))        # not used directly; EL below
    # gross EL proxy: expected principal loss share captured via return tail
    cvar = np.mean(np.sort(ret)[: max(1, int(0.05 * N))])
    return dict(
        label=label,
        mean_irr=float(np.mean(irr)),
        median_irr=float(np.median(irr)),
        mean_return=float(np.mean(ret)),
        median_return=float(np.median(ret)),
        mean_moic=float(np.mean(moic)),
        default_rate=float(def_rate),
        cvar95_return=float(cvar),
        p5_return=float(np.percentile(ret, 5)),
        p95_return=float(np.percentile(ret, 95)),
        irr=irr, ret=ret, moic=moic,
        leg_cash_pct=float(np.mean(res["leg_cash"]) / out),
        leg_kicker_pct=float(np.mean(res["leg_kicker"]) / out),
    )
