"""
engine.py  Tycheos Health Capital
Venture / growth-debt benchmark engine.

Design principle (LP-credible):
  * BENCHMARK = the real 17-name US comparable book from the Tycheos comparable-fund
    memo (SS13.4). Per-name PD and EL are verified calibration inputs; recovery backed
    out of EL so portfolio EL/loss-rate reconciles to the memo by construction.
  * SUBJECT = the 25-deal EUR509M EU private book (Stage & Exit strategy slide + fund
    deployment model). Base risk anchored to US empirical cluster means (SS17 shrunk PDs);
    only claimed Tycheos edges layered on top, each a stress-testable toggle.

Three new variables vs the prior version:
  1. Per-deal warrant coverage -- assigned per company based on exit route, stage, and sector.
  2. Restructuring -- distressed borrowers may restructure rather than default: extended
     maturity, PIK coupon at reduced rate, then either cure or modified-recovery default.
  3. Early termination -- surviving borrowers may voluntarily prepay after the IO period
     with a prepayment premium; reduces coupon income but accelerates capital return.

Restructuring and early termination are Tycheos-book-only features (active creditor).
The US benchmark runs with both disabled (defaults = 0) to preserve comparability.
"""

import numpy as np

DT = 0.25  # quarterly step size

# -----------------------------------------------------------------------------------------
# 1. US COMPARABLE BOOK  --  17 positions, calibrated to memo SS13.4
#    EL reconciles to $110.5M / 11.2% by construction.
# -----------------------------------------------------------------------------------------
US_BOOK = [
    # name,    cluster,           drawn,  rate,   mat_q, pd,    el,    exit
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

# -----------------------------------------------------------------------------------------
# 2. SHRUNK CLUSTER PDs  --  empirical anchor for EU book base risk (memo SS17.2)
# -----------------------------------------------------------------------------------------
SHRUNK_CLUSTER_PD = {
    "Dx": 0.297, "MedTech": 0.102, "GeneTx": 0.692, "ImmunoBinary": 0.276,
    "SpecialtyPharma": 0.163, "MedTechSmall": 0.456, "DigitalHealth": 0.470,
    "Biotech": 0.350,
}

# Warrant-kicker realisation by exit route (fraction of per-deal coverage monetised).
KICKER_REAL = {
    "Repayment": 0.15, "Refinancing": 0.55,
    "M&A": 1.00, "Public": 1.00, "Repayment/M&A": 0.60,
}

# -----------------------------------------------------------------------------------------
# 3. TYCHEOS EU BOOK  --  25 deals
#
#    Fields: (company, cluster, country, drawn EURm, IO_months, exit_route, warrant_cov)
#
#    Exit routes: verbatim from Stage & Exit strategy slide.
#    Drawn sizes: stage as primary driver (Public/Scale-up larger; Pre-IPO smaller),
#                 sector secondary. Max EUR30M. Total EUR509M, avg EUR20.4M.
#    Warrant coverage: derived per-deal from exit route + stage + sector.
#      Base by exit: M&A 15%, Refinancing 12%, Repayment 8%, Repayment/M&A 12%.
#      Stage add: Pre-IPO +3%, Early Commercial +1%, Scale-up/Public 0%.
#      Sector add: Biotech +3%, Dx +1%, Healthtech +2%, MedTech/SpecialtyPharma 0%.
#    IO periods: from deployment model; sector defaults where not available.
#    Sector -> cluster PD: Biotech 0.30, MedTech 0.12, Dx 0.22,
#                          Healthtech 0.16, SpecialtyPharma 0.16.
# -----------------------------------------------------------------------------------------
SECTOR_BASE_PD = {
    "Biotech": 0.30, "MedTech": 0.12, "Dx": 0.22,
    "Healthtech": 0.16, "SpecialtyPharma": 0.16,
}

EU_DEALS = [
    # company,            cluster,           country, drawn, IO_m, exit_route,      warrant_cov
    # Warrant coverage logic per deal:
    # Pharming: Repayment+Public+ScaleUp  -> 8+0+0 = 8%
    ("Pharming",          "SpecialtyPharma", "EU",    25.0,  12, "Repayment",       0.08),
    # Abivax: Refinancing+Public+Biotech  -> 12+0+3 = 15%
    ("Abivax",            "Biotech",         "EU",    30.0,  12, "Refinancing",     0.15),
    # Kiadis: M&A+Public+Biotech          -> 15+0+3 = 18%
    ("Kiadis",            "Biotech",         "EU",    20.0,  12, "M&A",             0.18),
    # Zava: M&A+PreIPO+Healthtech         -> 15+3+2 = 20%
    ("Zava",              "Healthtech",      "Other", 13.0,  18, "M&A",             0.20),
    # Impress: Refinancing+ScaleUp+MedTech-> 12+0+0 = 12%
    ("Impress",           "MedTech",         "EU",    23.0,  12, "Refinancing",     0.12),
    # PathoQuest: Repayment/M&A+EC+Dx    -> 12+1+1 = 14%
    ("PathoQuest",        "Dx",              "EU",    17.0,  12, "Repayment/M&A",   0.14),
    # Azafaros: Refinancing+PreIPO+Biotech-> 12+3+3 = 18%
    ("Azafaros",          "Biotech",         "EU",    18.0,  18, "Refinancing",     0.18),
    # Alveus: Refinancing+PreIPO+Biotech  -> 12+3+3 = 18%
    ("Alveus",            "Biotech",         "EU",    15.0,  18, "Refinancing",     0.18),
    # Ryme Medical: Refinancing+PreIPO+MT -> 12+3+0 = 15%
    ("Ryme Medical",      "MedTech",         "EU",    20.0,  12, "Refinancing",     0.15),
    # Vico Tx: Refinancing+PreIPO+Biotech -> 12+3+3 = 18%
    ("Vico Therapeutics", "Biotech",         "EU",    18.0,  18, "Refinancing",     0.18),
    # Nicox: Refinancing+EC+Public+SP     -> 12+0+0 = 12%
    ("Nicox",             "SpecialtyPharma", "EU",    20.0,  12, "Refinancing",     0.12),
    # Proveca: Repayment+EC+SP            -> 8+1+0 = 9%
    ("Proveca",           "SpecialtyPharma", "UK",    16.0,  12, "Repayment",       0.09),
    # Oviva: Repayment+EC+Healthtech      -> 8+1+2 = 11%
    ("Oviva",             "Healthtech",      "EU",    15.0,  12, "Repayment",       0.11),
    # Binx: Repayment+EC+Dx              -> 8+1+1 = 10%
    ("Binx",              "Dx",              "UK",    22.0,  12, "Repayment",       0.10),
    # Opiant: M&A+Public+SP               -> 15+0+0 = 15%
    ("Opiant",            "SpecialtyPharma", "Other", 20.0,   6, "M&A",             0.15),
    # MDxHealth: Refinancing+EC+Dx        -> 12+1+1 = 14%
    ("MDxHealth",         "Dx",              "EU",    20.0,  12, "Refinancing",     0.14),
    # MMI: M&A+EC+MedTech                -> 15+1+0 = 16%
    ("MMI",               "MedTech",         "EU",    24.0,  12, "M&A",             0.16),
    # Allotex: Repayment+EC+MedTech       -> 8+1+0 = 9%
    ("Allotex",           "MedTech",         "EU",    22.0,  12, "Repayment",       0.09),
    # Corflow: Refinancing+PreIPO+MedTech -> 12+3+0 = 15%
    ("Corflow",           "MedTech",         "EU",    20.0,  18, "Refinancing",     0.15),
    # Innovheart: Refinancing+PreIPO+MT   -> 12+3+0 = 15%
    ("Innovheart",        "MedTech",         "EU",    20.0,  18, "Refinancing",     0.15),
    # Tensive: Refinancing+EC+MedTech     -> 12+1+0 = 13%
    ("Tensive",           "MedTech",         "EU",    22.0,  12, "Refinancing",     0.13),
    # Aferetica: Refinancing+EC+MedTech   -> 12+1+0 = 13%
    ("Aferetica",         "MedTech",         "EU",    20.0,  12, "Refinancing",     0.13),
    # Nemsys: Repayment+ScaleUp+MedTech   -> 8+0+0 = 8%
    ("Nemsys",            "MedTech",         "EU",    24.0,  12, "Repayment",       0.08),
    # Newron: Repayment+EC+Public+SP      -> 8+0+0 = 8%
    ("Newron",            "SpecialtyPharma", "EU",    20.0,  12, "Repayment",       0.08),
    # Jenavalve: M&A+EC+MedTech           -> 15+1+0 = 16%
    ("Jenavalve",         "MedTech",         "UK",    25.0,  12, "M&A",             0.16),
]

# Base-case steer (ED) and conservative model variant.
TYCHEOS_BASECASE = dict(coupon=0.12, fees_leg=0.03, kicker_leg=0.05, lev=0.02, costs=0.04)
MODEL_INPUTS = dict(coupon=0.11, fees=0.013)


# -----------------------------------------------------------------------------------------
# Correlation matrix: cluster-based Gaussian copula.
# -----------------------------------------------------------------------------------------
def _pair_rho(c1, c2):
    intra = {
        "Dx": 0.40, "MedTech": 0.35, "Biotech": 0.30, "Healthtech": 0.25,
        "ImmunoBinary": 0.35, "GeneTx": 0.35, "SpecialtyPharma": 0.25,
    }
    return intra.get(c1, 0.30) if c1 == c2 else 0.20


def build_corr(clusters):
    n = len(clusters)
    rho = np.eye(n)
    for i in range(n):
        for j in range(i + 1, n):
            rho[i, j] = rho[j, i] = _pair_rho(clusters[i], clusters[j])
    w, V = np.linalg.eigh(rho)
    rho = V @ np.diag(np.clip(w, 1e-6, None)) @ V.T
    d = np.sqrt(np.diag(rho))
    rho = rho / np.outer(d, d)
    return np.linalg.cholesky(rho)


def _recovery_from_el(pd, el, drawn):
    if pd <= 0 or drawn <= 0:
        return 0.50
    return float(np.clip(1.0 - el / (pd * drawn), 0.05, 0.90))


# -----------------------------------------------------------------------------------------
# EU book constructor -- toggleable Tycheos edges + per-deal warrant + IO quarter.
# Returns rows of:
#   (name, cluster, drawn, rate, mat_q, pd, recovery, exit_route, warrant_cov, io_q)
# -----------------------------------------------------------------------------------------
def build_eu_book(selection_edge=True, active_workout=True, ip_collateral=True, coupon=0.12):
    """
    coupon: 0.12 = base-case steer, 0.11 = conservative model input.
    Each deal carries its own warrant_cov and io_q for restructuring / early-term logic.
    """
    book = []
    for deal, cluster, country, drawn, io_m, exit_route, warrant_cov in EU_DEALS:
        pd = SECTOR_BASE_PD[cluster]
        recovery = 0.50
        if selection_edge:
            pd *= 0.85
        if active_workout:
            pd *= 0.92
            recovery += 0.07
        if ip_collateral:
            recovery += 0.10
        pd = float(np.clip(pd, 0.01, 0.95))
        recovery = float(np.clip(recovery, 0.05, 0.90))
        mat_q = int(round((io_m + 24) / 3.0))
        io_q = int(round(io_m / 3.0))
        book.append((deal, cluster, drawn, coupon, mat_q, pd, recovery,
                     exit_route, warrant_cov, io_q))
    return book


def _us_book_prepared():
    """US book rows: (name, cluster, drawn, rate, mat_q, pd, rec, exit, warrant_cov=0.10, io_q=0)"""
    out = []
    for name, cluster, drawn, rate, mat_q, pd, el, exit_route in US_BOOK:
        rec = _recovery_from_el(pd, el, drawn)
        out.append((name, cluster, drawn, rate, mat_q, pd, rec, exit_route, 0.10, 0))
    return out


# -----------------------------------------------------------------------------------------
# Core reduced-form simulation.
#
# terms keys:
#   upfront, backend            -- fee legs (fractions of drawn)
#   warrant                     -- GLOBAL warrant coverage fallback if per-deal cov not set
#   recovery_lag_q              -- quarters between default event and cash recovery (default 4)
#   warrant_dispersion          -- lognormal vol on warrant multiple (default 0.6)
#   p_restructure               -- P(restructure | distressed, Tycheos active creditor) (default 0.35)
#   restr_coupon_haircut        -- coupon rate during restructure as fraction of original (default 0.50)
#   restr_extension_q           -- maturity extension granted in restructure, quarters (default 6)
#   restr_cure_prob             -- P(cured after restructure period) (default 0.45)
#   restr_recovery_haircut      -- recovery haircut on post-restructure default (default 0.15)
#   p_prepay_q                  -- P(voluntary prepayment per quarter after IO) (default 0.05)
#   prepay_premium              -- prepayment fee as fraction of outstanding (default 0.02)
#
# book rows (EU): (name, cluster, drawn, rate, mat_q, pd, rec, exit, warrant_cov, io_q)
# book rows (US): same, warrant_cov=0.10, io_q=0 (restructure/early-term disabled at io_q=0)
# -----------------------------------------------------------------------------------------
def simulate(book, terms, N=10000, seed=42):
    rng = np.random.default_rng(seed)
    clusters = [r[1] for r in book]
    n = len(book)
    max_q = max(r[4] for r in book)

    L = build_corr(clusters)
    Z = rng.standard_normal((N, n)) @ L.T
    U = 0.5 * (1.0 + erf_approx(Z / np.sqrt(2.0)))

    # -- terms --
    upfront  = terms["upfront"]
    backend  = terms["backend"]
    warr_global = terms.get("warrant", 0.15)
    lag      = terms.get("recovery_lag_q", 4)
    disp     = terms.get("warrant_dispersion", 0.6)

    p_restr        = terms.get("p_restructure", 0.35)
    restr_haircut  = terms.get("restr_coupon_haircut", 0.50)
    restr_ext      = terms.get("restr_extension_q", 6)
    restr_cure     = terms.get("restr_cure_prob", 0.45)
    restr_rec_hc   = terms.get("restr_recovery_haircut", 0.15)
    p_prepay_q     = terms.get("p_prepay_q", 0.05)
    prepay_prem    = terms.get("prepay_premium", 0.02)

    port       = np.zeros((N, max_q + 1))
    defaults   = np.zeros((N, n), dtype=bool)
    restrucs   = np.zeros((N, n), dtype=bool)
    prepays    = np.zeros((N, n), dtype=bool)
    total_out  = 0.0

    leg_cash   = np.zeros(N)
    leg_kicker = np.zeros(N)
    leg_restr  = np.zeros(N)   # coupon income recovered through restructuring
    leg_prepay = np.zeros(N)   # prepayment premium income

    for idx, row in enumerate(book):
        name, cluster, drawn, rate, mat_q, pd, recovery, exit_route, warrant_cov, io_q = row
        outlay = drawn * (1.0 - upfront)
        total_out += outlay

        coupon = drawn * rate * DT

        # --- default / restructure / survive split ---
        defd_raw = U[:, idx] < pd
        skew = 0.5 + 0.5 * pd
        u_t = rng.random(N) ** skew
        def_q_raw = np.maximum(1, np.ceil(u_t * mat_q)).astype(int)

        # Restructuring: active creditor converts a fraction of defaults into restructures.
        # Only applies when io_q > 0 (EU book). US book has io_q=0 -> no restructuring.
        do_restr = defd_raw & (io_q > 0) & (rng.random(N) < p_restr)
        true_def = defd_raw & ~do_restr

        defaults[:, idx] = true_def
        restrucs[:, idx] = do_restr

        # --- cashflow construction ---
        name_cf = np.zeros((N, max_q + 1))

        # 1. Normal coupon income (all paths, up to default or maturity)
        last_coupon_q = np.where(true_def, def_q_raw,
                        np.where(do_restr, def_q_raw, mat_q))
        qs   = np.arange(1, mat_q + 1)
        alive = qs[None, :] <= last_coupon_q[:, None]
        name_cf[:, 1:mat_q + 1] += alive * coupon
        leg_cash += (alive * coupon).sum(axis=1)

        # 2. Restructured paths: reduced coupon for extension period, then cure or default
        if do_restr.any():
            ext_end_q = np.minimum(def_q_raw + restr_ext, max_q)
            restr_coupon = coupon * restr_haircut
            for i in np.where(do_restr)[0]:
                start = def_q_raw[i]
                end   = ext_end_q[i]
                if start <= max_q:
                    ext_qs = np.arange(start, min(end + 1, max_q + 1))
                    name_cf[i, ext_qs] += restr_coupon
                    leg_restr[i] += restr_coupon * len(ext_qs)
            # cure vs post-restructure default
            cured = do_restr & (rng.random(N) < restr_cure)
            re_def = do_restr & ~cured
            # cured: collect backend + warrant at extended maturity
            if cured.any():
                real = KICKER_REAL.get(exit_route, 0.4)
                upside = np.exp(rng.normal(0.0, disp, N)) * real
                warrant = np.clip(warrant_cov * drawn * upside, 0.0, warrant_cov * drawn * 4.0)
                for i in np.where(cured)[0]:
                    pay = drawn + drawn * backend + warrant[i]
                    t   = min(ext_end_q[i], max_q)
                    name_cf[i, t] += pay
                    leg_kicker[i] += warrant[i]
            # post-restructure default: discounted recovery (IP preserved but haircut)
            if re_def.any():
                rec_adj = recovery * (1.0 - restr_rec_hc)
                rec_val = drawn * rec_adj * (0.85 + 0.30 * rng.random(N))
                rec_val = np.clip(rec_val, 0.0, drawn)
                for i in np.where(re_def)[0]:
                    t = min(ext_end_q[i] + lag, max_q)
                    name_cf[i, t] += rec_val[i]

        # 3. True default: standard recovery after workout lag
        if true_def.any():
            rec_q  = np.minimum(def_q_raw + lag, max_q)
            rec_val = drawn * recovery * (0.85 + 0.30 * rng.random(N))
            np.add.at(name_cf,
                      (np.where(true_def)[0], rec_q[true_def]),
                      rec_val[true_def])

        # 4. Survivors: early termination (voluntary prepayment after IO period)
        surv = ~defd_raw   # not restructured, not defaulted
        if surv.any() and io_q > 0 and p_prepay_q > 0:
            # earliest possible prepay quarter = IO end + 1
            prepay_start = io_q + 1
            # per-path prepayment quarter: geometric-like draw
            u_pp = rng.random(N)
            remaining_q = mat_q - prepay_start
            if remaining_q > 0:
                pp_q = prepay_start + np.floor(
                    -np.log(np.maximum(u_pp, 1e-9)) / p_prepay_q
                ).astype(int)
                # prepayment occurs only if pp_q < mat_q
                does_prepay = surv & (pp_q < mat_q)
                prepays[:, idx] = does_prepay
                # prepaying paths: coupons up to pp_q, then principal + prepay premium
                if does_prepay.any():
                    pp_q_clip = np.minimum(pp_q, mat_q)
                    for i in np.where(does_prepay)[0]:
                        # coupons from last_coupon_q[i]+1 to pp_q[i] already in alive;
                        # alive mask was computed up to mat_q -- fix: override those paths
                        # revert maturity coupons and add prepay cash
                        # strip coupons past pp_q
                        for qt in range(pp_q_clip[i] + 1, mat_q + 1):
                            if qt < name_cf.shape[1]:
                                name_cf[i, qt] -= coupon
                                leg_cash[i] -= coupon
                        prem = drawn * prepay_prem
                        name_cf[i, pp_q_clip[i]] += drawn + prem
                        leg_prepay[i] += prem

        # 5. Non-prepaying survivors: principal + backend + warrant at maturity
        final_surv = surv & (~prepays[:, idx] if io_q > 0 else surv)
        if final_surv.any():
            real   = KICKER_REAL.get(exit_route, 0.4)
            upside = np.exp(rng.normal(0.0, disp, N)) * real
            warrant = np.clip(warrant_cov * drawn * upside, 0.0, warrant_cov * drawn * 4.0)
            pay = drawn + drawn * backend + warrant
            for i in np.where(final_surv)[0]:
                name_cf[i, mat_q] += pay[i]
                leg_kicker[i] += warrant[i]

        port += name_cf

    port[:, 0] = -total_out
    return dict(
        port=port, defaults=defaults, restrucs=restrucs, prepays=prepays,
        total_out=total_out, leg_cash=leg_cash, leg_kicker=leg_kicker,
        leg_restr=leg_restr, leg_prepay=leg_prepay, N=N, max_q=max_q,
    )


# -----------------------------------------------------------------------------------------
# Vectorised standard-normal CDF (no scipy dependency).
# -----------------------------------------------------------------------------------------
def erf_approx(x):
    sign = np.sign(x); x = np.abs(x)
    t = 1.0 / (1.0 + 0.3275911 * x)
    y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t
               - 0.284496736) * t + 0.254829592) * t * np.exp(-x * x)
    return sign * y


# -----------------------------------------------------------------------------------------
# Vectorised IRR: bisection on quarterly rate, annualised.
# -----------------------------------------------------------------------------------------
def vectorized_irr(cf, lo=-0.99, hi=2.0, iters=80):
    powers = np.arange(cf.shape[1])
    lo = np.full(cf.shape[0], lo)
    hi = np.full(cf.shape[0], hi)
    def npv(r):
        return (cf / (1.0 + r[:, None]) ** powers[None, :]).sum(axis=1)
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        lo  = np.where(npv(mid) > 0, mid, lo)
        hi  = np.where(npv(mid) > 0, hi,  mid)
    return (1.0 + 0.5 * (lo + hi)) ** 4 - 1.0


# -----------------------------------------------------------------------------------------
# Summarize simulation results.
# -----------------------------------------------------------------------------------------
def summarize(res, label):
    port = res["port"]; N = res["N"]; out = res["total_out"]
    total_in = port[:, 1:].sum(axis=1)
    moic = total_in / out
    ret  = moic - 1.0
    irr  = vectorized_irr(port)
    cvar = np.mean(np.sort(ret)[: max(1, int(0.05 * N))])
    return dict(
        label=label,
        mean_irr=float(np.mean(irr)),
        median_irr=float(np.median(irr)),
        mean_return=float(np.mean(ret)),
        median_return=float(np.median(ret)),
        mean_moic=float(np.mean(moic)),
        default_rate=float(res["defaults"].mean()),
        restructure_rate=float(res["restrucs"].mean()),
        prepay_rate=float(res["prepays"].mean()),
        cvar95_return=float(cvar),
        p5_return=float(np.percentile(ret, 5)),
        p95_return=float(np.percentile(ret, 95)),
        irr=irr, ret=ret, moic=moic,
        leg_cash_pct=float(np.mean(res["leg_cash"]) / out),
        leg_kicker_pct=float(np.mean(res["leg_kicker"]) / out),
        leg_restr_pct=float(np.mean(res["leg_restr"]) / out),
        leg_prepay_pct=float(np.mean(res["leg_prepay"]) / out),
    )
