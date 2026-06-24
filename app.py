"""
app.py  Tycheos Health Capital
Venture / Growth-Debt Benchmark Studio: Tycheos (EU private) vs the full 17-name US comparable book.

Three LP-credible layers:
  1. Strategy      -- two genuinely different books, one engine. IRR / return / loss distributions.
  2. Return bridge -- decompose Tycheos net return into cash / fees / kicker / leverage / costs and
                      anchor each leg externally. Surfaces the gap to the deck's 18% net honestly.
  3. Attribution   -- bridge benchmark IRR to Tycheos IRR by toggling one driver at a time.

Run:  streamlit run app.py
Requires: streamlit, numpy, pandas, plotly  (engine.py in the same folder)
"""

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import engine as E

st.set_page_config(page_title="Tycheos Benchmark Studio", layout="wide")

TYC = "#00857a"
BMK = "#9aa5b1"
ACC = "#c8a24b"

st.title("Tycheos Credit Benchmark Studio")
st.caption(
    "Tycheos illustrative EU private book vs the full 17-name US comparable book "
    "(Perceptive, Hercules, OrbiMed, Catalio, RA Capital). One engine, two real books."
)

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("Simulation")
    N = st.select_slider("Monte Carlo paths", options=[5000, 10000, 15000, 20000], value=10000)
    seed = st.number_input("Seed", 1, 9999, 42, step=1)

    st.header("Tycheos base case (deck legs)")
    cash_leg = st.slider("Cash interest %", 8.0, 14.0, 12.0, 0.5) / 100
    fees_leg = st.slider("Fees and exceptionals %", 0.0, 5.0, 3.0, 0.5) / 100
    kick_leg = st.slider("Equity kicker %", 0.0, 8.0, 5.0, 0.5) / 100

    st.header("Tycheos sim terms (bottom-up)")
    t_up = st.slider("Upfront fee %", 0.0, 4.0, 2.0, 0.5) / 100
    t_be = st.slider("Back-end fee %", 0.0, 6.0, 4.0, 0.5) / 100
    t_wr = st.slider("Warrant coverage %", 5, 40, 15, 1) / 100

    st.header("Competitor terms (US book)")
    c_up = st.slider("Competitor upfront fee %", 0.0, 4.0, 1.0, 0.5) / 100
    c_be = st.slider("Competitor back-end fee %", 0.0, 6.0, 2.5, 0.5) / 100
    c_wr = st.slider("Competitor warrant coverage %", 5, 30, 10, 1) / 100

    st.header("Tycheos edges (stress these)")
    e_sel = st.checkbox("Selection edge (smaller check vs runway)", True)
    e_work = st.checkbox("Active workout + grace", True)
    e_ip = st.checkbox("IP-inclusive collateral", True)

    st.header("Fund-level legs")
    lev = st.slider("Leverage / admin uplift (+pp)", 0.0, 4.0, 2.0, 0.5) / 100
    costs = st.slider("Fund costs (-pp)", 0.0, 8.0, 4.0, 0.5) / 100

tyc_terms = dict(upfront=t_up, backend=t_be, warrant=t_wr, recovery_lag_q=4, warrant_dispersion=0.6)
comp_terms = dict(upfront=c_up, backend=c_be, warrant=c_wr, recovery_lag_q=4, warrant_dispersion=0.6)


@st.cache_data(show_spinner=False)
def run(book_key, terms, edges, N, seed, coupon=0.12):
    if book_key == "us":
        book = E._us_book_prepared()
    else:
        book = E.build_eu_book(*edges, coupon=coupon)
    res = E.simulate(book, terms, N=N, seed=seed)
    s = E.summarize(res, book_key)
    drawn = sum(r[2] for r in book)
    wal = sum(r[2] * r[4] * E.DT for r in book) / drawn
    el = sum(r[5] * (1 - r[6]) * r[2] for r in book)
    s.update(drawn=drawn, wal=wal, el=el, el_pct=el / drawn)
    return s


edges = (e_sel, e_work, e_ip)
with st.spinner("Running correlated Monte Carlo on both books..."):
    s_us = run("us", comp_terms, (True, True, True), N, seed)
    s_eu = run("eu", tyc_terms, edges, N, seed, coupon=cash_leg)

# ------------------------------------------------------------------ reconciliation
with st.expander("Reconciliation to comparable-fund memo (credibility anchor)", expanded=True):
    rc = pd.DataFrame({
        "Metric": ["Deployed", "Portfolio expected loss", "Loss rate", "Avg default rate (book)"],
        "Engine (US book)": [
            f"${s_us['drawn']:.0f}M",
            f"${s_us['el']:.1f}M",
            f"{100 * s_us['el_pct']:.1f}%",
            f"{100 * s_us['default_rate']:.1f}%",
        ],
        "Memo (SS13.4-13.5)": [
            "$986M",
            "$110.5M",
            "11.2%",
            "Perceptive 27.8% / pooled lower",
        ],
    })
    st.table(rc)
    st.caption(
        "EL and loss rate reconcile by construction: per-name PD and EL are verified memo "
        "inputs; recovery is backed out of EL. Return level is a forward model validated "
        "externally in the Return Bridge."
    )

# ------------------------------------------------------------------ headline
deck_gross = cash_leg + fees_leg + kick_leg
deck_net = deck_gross + lev - costs
model_net = s_eu["mean_irr"] + lev - costs

st.subheader("Headline")
c1, c2, c3, c4 = st.columns(4)
c1.metric(
    "Tycheos net IRR -- deck base case",
    f"{100 * deck_net:.1f}%",
    help=f"{100*cash_leg:.0f} + {100*fees_leg:.0f} + {100*kick_leg:.0f} = "
         f"{100*deck_gross:.0f}% gross, +{100*lev:.0f} / -{100*costs:.0f} fund legs.",
)
c2.metric(
    "Tycheos net IRR -- model bottom-up",
    f"{100 * model_net:.1f}%",
    delta=f"{100 * (model_net - deck_net):+.1f}pp vs deck",
    delta_color="off",
)
c3.metric(
    "US benchmark IRR",
    f"{100 * s_us['mean_irr']:.1f}%",
    delta=f"{100 * (model_net - s_us['mean_irr']):+.1f}pp net vs benchmark",
)
c4.metric(
    "Tycheos loss rate",
    f"{100 * s_eu['el_pct']:.1f}%",
    delta=f"{100 * (s_eu['el_pct'] - s_us['el_pct']):+.1f}pp vs benchmark",
    delta_color="inverse",
)

tab1, tab2, tab3 = st.tabs(["1 - Strategy comparison", "2 - Return bridge", "3 - Attribution"])

# ================================================================== LAYER 1
with tab1:
    st.markdown(
        "**Two different books, one engine.** Tycheos = the 25-deal EUR510M book from the "
        "fund deployment model (Biotech 8 / Medtech 9 / Diagnostic 2 / Healthtech 6; "
        "EU 16 / UK 5 / Other 4). The delta reflects geography, selection, structuring "
        "and exit mix -- not a fee gap on identical assets."
    )
    g1, g2 = st.columns(2)
    with g1:
        df_irr = pd.DataFrame({
            "IRR (%)": np.concatenate([s_eu["irr"] * 100, s_us["irr"] * 100]),
            "Book": ["Tycheos EU"] * len(s_eu["irr"]) + ["US comparable book"] * len(s_us["irr"]),
        })
        fig_irr = px.histogram(
            df_irr, x="IRR (%)", color="Book", barmode="overlay", nbins=60,
            color_discrete_map={"Tycheos EU": TYC, "US comparable book": BMK},
            title="Annualised IRR distribution",
        )
        fig_irr.update_layout(legend=dict(orientation="h", y=1.02))
        st.plotly_chart(fig_irr, use_container_width=True)
    with g2:
        df_moic = pd.DataFrame({
            "MOIC (x)": np.concatenate([s_eu["moic"], s_us["moic"]]),
            "Book": ["Tycheos EU"] * len(s_eu["moic"]) + ["US comparable book"] * len(s_us["moic"]),
        })
        fig_moic = px.histogram(
            df_moic, x="MOIC (x)", color="Book", barmode="overlay", nbins=60,
            color_discrete_map={"Tycheos EU": TYC, "US comparable book": BMK},
            title="Capital multiple (MOIC) distribution",
        )
        fig_moic.update_layout(legend=dict(orientation="h", y=1.02))
        st.plotly_chart(fig_moic, use_container_width=True)

    comp_table = pd.DataFrame({
        "": [
            "Mean IRR", "Median IRR", "Mean MOIC",
            "Loss rate", "Default rate", "CVaR(95%) return", "P5 / P95 return",
        ],
        "Tycheos EU": [
            f"{100 * s_eu['mean_irr']:.1f}%",
            f"{100 * s_eu['median_irr']:.1f}%",
            f"{s_eu['mean_moic']:.2f}x",
            f"{100 * s_eu['el_pct']:.1f}%",
            f"{100 * s_eu['default_rate']:.1f}%",
            f"{100 * s_eu['cvar95_return']:.1f}%",
            f"{100 * s_eu['p5_return']:.0f}% / {100 * s_eu['p95_return']:.0f}%",
        ],
        "US comparable book": [
            f"{100 * s_us['mean_irr']:.1f}%",
            f"{100 * s_us['median_irr']:.1f}%",
            f"{s_us['mean_moic']:.2f}x",
            f"{100 * s_us['el_pct']:.1f}%",
            f"{100 * s_us['default_rate']:.1f}%",
            f"{100 * s_us['cvar95_return']:.1f}%",
            f"{100 * s_us['p5_return']:.0f}% / {100 * s_us['p95_return']:.0f}%",
        ],
    })
    st.table(comp_table)

# ================================================================== LAYER 2
with tab2:
    st.markdown(
        "**Return bridge.** Left: your deck base case (12 / 3 / 5). "
        "Right: the model bottom-up legs from the EUR510M book. "
        "Where they diverge is the honest finding."
    )
    wal = s_eu["wal"]
    bu_cash = s_eu["leg_cash_pct"] / wal
    bu_kick = s_eu["leg_kicker_pct"] / wal
    bu_fees = (t_up + t_be * (1 - s_eu["default_rate"])) / wal
    bu_loss = s_eu["el_pct"] / wal
    bu_gross = bu_cash + bu_fees + bu_kick - bu_loss
    bu_net = bu_gross + lev - costs

    g1, g2 = st.columns(2)
    with g1:
        wf_deck = go.Figure(go.Waterfall(
            orientation="v",
            measure=["relative", "relative", "relative", "total", "relative", "relative", "total"],
            x=["Cash interest", "Fees", "Equity kicker", "Gross IRR", "+ Leverage", "- Costs", "Net IRR"],
            y=[cash_leg * 100, fees_leg * 100, kick_leg * 100, 0, lev * 100, -costs * 100, 0],
            connector={"line": {"color": "#cccccc"}},
            increasing={"marker": {"color": TYC}},
            decreasing={"marker": {"color": "#d97b66"}},
            totals={"marker": {"color": ACC}},
        ))
        wf_deck.update_layout(
            title="Deck base case (top-down)", yaxis_title="%", showlegend=False, height=430
        )
        st.plotly_chart(wf_deck, use_container_width=True)
        st.metric("Deck net IRR", f"{100 * deck_net:.1f}%")

    with g2:
        wf_bu = go.Figure(go.Waterfall(
            orientation="v",
            measure=["relative", "relative", "relative", "relative", "total",
                     "relative", "relative", "total"],
            x=["Cash interest", "Fees", "Equity kicker", "- Credit losses",
               "Gross IRR", "+ Leverage", "- Costs", "Net IRR"],
            y=[bu_cash * 100, bu_fees * 100, bu_kick * 100, -bu_loss * 100,
               0, lev * 100, -costs * 100, 0],
            connector={"line": {"color": "#cccccc"}},
            increasing={"marker": {"color": TYC}},
            decreasing={"marker": {"color": "#d97b66"}},
            totals={"marker": {"color": BMK}},
        ))
        wf_bu.add_hline(
            y=deck_net * 100, line_dash="dash", line_color="#888",
            annotation_text=f"deck {100 * deck_net:.0f}%",
        )
        wf_bu.update_layout(
            title="Model bottom-up (EUR510M book)", yaxis_title="%", showlegend=False, height=430
        )
        st.plotly_chart(wf_bu, use_container_width=True)
        st.metric(
            "Model net IRR",
            f"{100 * bu_net:.1f}%",
            delta=f"{100 * (bu_net - deck_net):+.1f}pp vs deck",
        )

    anchor = pd.DataFrame({
        "Leg": ["Cash interest", "Equity kicker", "Credit losses"],
        "Deck": [f"{100 * cash_leg:.1f}%", f"{100 * kick_leg:.1f}%", "(in costs)"],
        "Model": [f"{100 * bu_cash:.1f}%", f"{100 * bu_kick:.1f}%", f"-{100 * bu_loss:.1f}%"],
        "External anchor": [
            "Model coupon 11% / deck 12%; EURIBOR ~2.5% + 8-9% spread",
            "Listed venture-debt BDC realised warrant income (cycle-dependent)",
            "Hercules 2.3bps realised / 33% resolved base rate, CI [15-61%]",
        ],
    })
    st.table(anchor)
    st.info(
        f"The cash leg reconciles (model {100 * bu_cash:.1f}% vs deck {100 * cash_leg:.0f}%). "
        f"The gap is the equity kicker: bottom-up {100 * bu_kick:.1f}% vs your "
        f"{100 * kick_leg:.0f}% target. Closing it requires the M&A/Public-weighted exit tail "
        "or higher warrant coverage -- use the sidebar to see what it takes. "
        "EUR caveat: at EUR base rates the cash leg is ~1pp lighter than a USD-implied 12%."
    )

# ================================================================== LAYER 3
with tab3:
    st.markdown(
        "**Attribution.** Bridge from the benchmark IRR to Tycheos by switching on one "
        "driver at a time. Each bar is a separate Monte Carlo run; an LP can zero any "
        "edge in the sidebar and watch its contribution disappear."
    )

    @st.cache_data(show_spinner=False)
    def attribution(N, seed, tyc_terms, comp_terms, coupon):
        steps = []
        steps.append((
            "US benchmark",
            E.summarize(E.simulate(E._us_book_prepared(), comp_terms, N, seed), "x")["mean_irr"],
        ))
        b1 = E.build_eu_book(False, False, False, coupon=coupon)
        steps.append((
            "+ EU selection",
            E.summarize(E.simulate(b1, comp_terms, N, seed), "x")["mean_irr"],
        ))
        steps.append((
            "+ Structuring terms",
            E.summarize(E.simulate(b1, tyc_terms, N, seed), "x")["mean_irr"],
        ))
        b3 = E.build_eu_book(False, True, False, coupon=coupon)
        steps.append((
            "+ Active workout",
            E.summarize(E.simulate(b3, tyc_terms, N, seed), "x")["mean_irr"],
        ))
        b4 = E.build_eu_book(False, True, True, coupon=coupon)
        steps.append((
            "+ IP collateral",
            E.summarize(E.simulate(b4, tyc_terms, N, seed), "x")["mean_irr"],
        ))
        b5 = E.build_eu_book(True, True, True, coupon=coupon)
        steps.append((
            "+ Selection edge",
            E.summarize(E.simulate(b5, tyc_terms, N, seed), "x")["mean_irr"],
        ))
        return steps

    steps = attribution(N, seed, tyc_terms, comp_terms, cash_leg)
    labels = [s[0] for s in steps]
    vals = [s[1] * 100 for s in steps]
    deltas = [vals[0]] + [vals[i] - vals[i - 1] for i in range(1, len(vals))]
    measures = ["absolute"] + ["relative"] * (len(vals) - 1)

    wf_attr = go.Figure(go.Waterfall(
        orientation="v",
        measure=measures,
        x=labels,
        y=deltas,
        connector={"line": {"color": "#cccccc"}},
        increasing={"marker": {"color": TYC}},
        decreasing={"marker": {"color": "#d97b66"}},
        totals={"marker": {"color": BMK}},
    ))
    wf_attr.update_layout(
        title="Asset-IRR attribution: benchmark to Tycheos",
        yaxis_title="IRR %",
        showlegend=False,
        height=440,
    )
    st.plotly_chart(wf_attr, use_container_width=True)
    st.caption(
        "Each bar is an independent Monte Carlo run switching on one driver. "
        "Zero any edge in the sidebar to see its contribution disappear."
    )

st.divider()
st.caption(
    "Benchmark reconciles to the comparable-fund memo on the risk side (EL 11.2%, default 27%). "
    "Tycheos = the EUR510M / 25-deal fund deployment model; base risk anchored to verified US "
    "cluster means by sector, with only the claimed edges layered on top. Exit routes and warrant "
    "economics are not in the deployment model -- assigned by sector and flagged. Not investment advice."
)
