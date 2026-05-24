"""
Build the mind-map dataset from the Navnoor Bawa Substack sitemap.

Output: data.json containing threads, concepts, clusters, edges, learning_paths,
quizzes — same shape consumed by index.html (modeled on Kris-SF/mind-map-explorer).

Strategy:
  - Each /p/<slug> URL becomes a "thread" node.
  - Title is derived from slug (titleized) with a small dictionary of fixes
    for known acronyms (LTCM, SEC, NDF, etc.) and the 12 posts whose true
    titles + subtitles we already have.
  - Concepts are extracted from slug tokens after stopword/junk removal,
    plus a curated taxonomy of finance entities (fund names, instruments,
    geographies, asset classes, quant methods).
  - Clusters are assigned by rule-based topic detection over the slug tokens.
  - Edges are weighted by Jaccard similarity over (concepts ∪ cluster).
  - Learning paths are pre-built reading sequences across a theme.
  - Quizzes are small auto-generated cards (title -> "What's the core mechanism?"
    with the slug-derived focus phrase as the answer side).
"""

import json, re, xml.etree.ElementTree as ET
from collections import defaultdict, Counter
from itertools import combinations
from pathlib import Path

SITEMAP = Path("/tmp/nb_sitemap.xml")
OUT     = Path(__file__).with_name("data.json")

# ---------------------------------------------------------------------------
# 1. Parse sitemap
# ---------------------------------------------------------------------------
NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
tree = ET.parse(SITEMAP)
posts = []
for u in tree.getroot().findall("s:url", NS):
    loc = u.find("s:loc", NS).text
    if "/p/" not in loc:
        continue
    lm = u.find("s:lastmod", NS)
    slug = loc.rsplit("/p/", 1)[1]
    posts.append({"slug": slug, "url": loc, "date": lm.text if lm is not None else ""})

posts.sort(key=lambda p: p["date"], reverse=True)
print(f"Loaded {len(posts)} posts")

# ---------------------------------------------------------------------------
# 2. Known posts (from archive scrape) — true titles + subtitles
# ---------------------------------------------------------------------------
KNOWN = {
  "the-cramer-rao-bound-killed-ltcm": {
    "title": "The Cramer-Rao Bound Killed LTCM. It's Why the SEC Just Fined Two Sigma $90M.",
    "summary": "Fisher Information sets a hard ceiling on every quant fund's Sharpe ratio."},
  "market-making-alpha-how-virtu-won": {
    "title": "Market Making Alpha: How Virtu Won 1,237 Days — and Why Jane Street Keeps Ending Up in Court",
    "summary": "Court filings, SEC orders, peer-reviewed papers, and executive interviews on market-making alpha."},
  "axie-infinity-cs2-skins-and-roblox": {
    "title": "Axie Infinity, CS2 Skins, and Roblox: How Hedge Funds Built Gaming Currency Alpha",
    "summary": "Every claim links directly to its source — interview, news report, investor letter, or court document."},
  "how-hedge-funds-made-billions-from": {
    "title": "How Hedge Funds Made Billions From SoftBank: Five Structural Trades",
    "summary": "Elliott's activist campaign and the Alibaba prepaid forward collar — every trade and mechanism."},
  "non-deliverable-forwards-ndfs-and": {
    "title": "Non-Deliverable Forwards (NDFs) and Emerging Market Currency Alpha",
    "summary": "Directional currency attacks, carry trades, basis arbitrage, fixing window exploitation."},
  "how-hedge-funds-turned-defense-stocks": {
    "title": "How Hedge Funds Turned Defense Stocks Into Their Best Trade of 2022",
    "summary": "Every claim carries a direct source link. No assertions without evidence."},
  "iran-war-hedge-fund-alpha-map-every": {
    "title": "Iran War Hedge Fund Alpha Map: Every Winner, Every Loser",
    "summary": "Pre-war CFTC crude positioning and the three-driver bond selloff."},
  "joint-spxvix-calibration-follow-up": {
    "title": "Joint SPX/VIX Calibration Follow-Up: Bates SVJ Degenerates on Daily Data",
    "summary": "Bates SVJ degenerates on daily data, HMM fails on novel crises, one logic fix recovers $300K."},
  "indias-oil-war-market-crisis-30-day": {
    "title": "India's Oil-War Market Crisis: 30-Day Nifty Outlook",
    "summary": "Built from RBI working papers, MUFG proprietary research, and SEBI's March 13 circular."},
  "the-holy-grail-of-volatility-modelling": {
    "title": "The Holy Grail of Volatility Modelling: What Happens When You Actually Try to Build It",
    "summary": "Quantitative volatility research from first principles."},
  "iran-war-oil-shock-2928-hedge-fund": {
    "title": "Iran War Oil Shock, 292.8% Hedge Fund Leverage, and Powell's Last FOMC",
    "summary": "30-Day market outlook, April FOMC reaction function, institutional liquidation protocol."},
  "the-desert-playbook-how-hedge-funds": {
    "title": "The Desert Playbook: How Hedge Funds Extracted Alpha from Dubai",
    "summary": "AED peg speculation, Dubai World CDS, Nakheel distressed sukuk, Emaar."},
}

# Known acronyms / canonical capitalization for slug-derived titles
ACRONYMS = {
  "ltcm","sec","cftc","fomc","rbi","sebi","ecb","fed","etf","etfs","vix","spx",
  "spx/vix","cds","cdx","cdo","mbs","abs","nav","ipo","spac","spacs",
  "ndf","ndfs","aed","usd","eur","jpy","gbp","cny","inr","brl","try","zar",
  "es","eu","us","uk","uae","emea","apac","esg","ets","eua","tcrcs","obdc",
  "lme","cme","cboe","ice","nyse","nasdaq","fx","oi","hmm","svj","gan","rl",
  "ml","ai","gpu","gpus","cpi","ppi","gdp","oas","yoy","mom","wti","dxy",
  "tbill","tbills","s&p","p&l","r&d","sov","emfx","gmt","ois","irs",
  "jane","virtu","de","shaw","jpm","td","ms","ubs","cs","bnp","hsbc","mufg",
  "boa","bofa","bac","goldman","gs","blackrock","blk","kkr","apollo","apo",
  "citadel","millennium","balyasny","two","sigma","point72","brevan","howard",
  "bridgewater","elliott","ackman","icahn","einhorn","klarman","griffin",
  "renaissance","medallion","bluecrest","marshall","wace","viking","tiger",
  "rkk","odey","vr","capital","da","vinci","alyeska","cqs","tpg","blue","owl",
}

TITLE_FIXES = {
  "spxvix":"SPX/VIX","spx":"SPX","vix":"VIX",
  "cramer":"Cramér","rao":"Rao",
}

def slug_to_title(slug):
    if slug in KNOWN: return KNOWN[slug]["title"]
    words = slug.split("-")
    out = []
    for w in words:
        wl = w.lower()
        if wl in ACRONYMS:
            out.append(wl.upper() if wl not in ("de","da","des","von") else wl)
        elif wl in TITLE_FIXES:
            out.append(TITLE_FIXES[wl])
        elif w.isdigit():
            out.append(w)
        elif re.match(r"^\d+[a-z]+$", wl):
            # e.g. "10b", "292", numbers with units
            out.append(w)
        else:
            out.append(w.capitalize())
    title = " ".join(out)
    # tidy
    title = re.sub(r"\bSpxvix\b","SPX/VIX",title,flags=re.I)
    return title

# ---------------------------------------------------------------------------
# 3. Concept taxonomy & extraction
# ---------------------------------------------------------------------------
TAXONOMY = {
  # Funds & firms
  "Citadel":["citadel"], "Millennium":["millennium"], "Bridgewater":["bridgewater","alpha-beta","pure-alpha","ray-dalio","dalio"],
  "Renaissance":["renaissance","medallion"], "Two Sigma":["two-sigma"], "Jane Street":["jane-street","jane"],
  "Virtu":["virtu"], "Elliott Management":["elliott"], "BlueCrest":["bluecrest"],
  "DE Shaw":["de-shaw","deshaw"], "Apollo":["apollo"], "KKR":["kkr"], "Blackstone":["blackstone"],
  "Blue Owl":["blue-owl","obdc"], "Brevan Howard":["brevan","howard"], "Point72":["point72"],
  "Balyasny":["balyasny"], "Bobby Jain":["bobby-jain"], "Boaz Weinstein":["boaz","weinstein","saba"],
  "Da Vinci":["da-vinci"], "Andurand":["andurand"], "Bill Ackman":["ackman"], "Carl Icahn":["icahn"],
  "Bank of America":["bank-of-america","bofa"], "Goldman Sachs":["goldman"], "JPMorgan":["jpmorgan","jpm"],
  "Morgan Stanley":["morgan-stanley"], "MUFG":["mufg"], "Alphabet":["alphabet","google"],
  "SoftBank":["softbank"], "Alibaba":["alibaba"],

  # Asset classes
  "Equities":["equities","equity","stocks","stock","nifty","sp500","spx","russell","nasdaq"],
  "Fixed Income":["bonds","bond","credit","yield","treasury","treasuries","duration","coupon","sukuk","cds","cdx"],
  "Commodities":["commodity","commodities","oil","crude","gold","silver","copper","wti","gas","grain","wheat"],
  "FX":["fx","currency","currencies","forex","ndf","ndfs","peg","aed","inr","try","yen","yuan","dollar","euro"],
  "Volatility":["volatility","vol","vix","spxvix","smile","skew","gamma","vega","variance","options","option"],
  "Credit":["credit","cds","cdx","cdo","high-yield","leveraged-loan","loan","loans","distressed","bankruptcy"],
  "Crypto":["crypto","bitcoin","ether","ethereum","defi","stablecoin","token","tokens","nft"],
  "Real Estate":["real-estate","reit","reits","property","mortgage","mbs","commercial-real-estate"],
  "Macro":["macro","fed","fomc","powell","inflation","cpi","gdp","employment","jobs","rates","rate"],
  "Private Credit":["private-credit","direct-lending","obdc"],

  # Strategies
  "Arbitrage":["arbitrage","arb","convergence","basis","statistical-arbitrage","stat-arb","merger-arb"],
  "Market Making":["market-making","market-maker","liquidity-provider"],
  "Activism":["activist","activism","activist-campaign"],
  "Distressed":["distressed","bankruptcy","restructuring","chapter-11"],
  "Event-Driven":["event-driven","merger","spin-off","spinoff","catalyst"],
  "Carry Trade":["carry","carry-trade"],
  "Macro Trading":["macro-trading","macro-trade","global-macro"],
  "Quantitative":["quant","quantitative","machine-learning","ml","ai","neural","deep-learning"],
  "Risk Premia":["risk-premium","risk-premia","factor","factors","smart-beta"],
  "Prediction Markets":["prediction-market","prediction-markets","polymarket","kalshi"],
  "Gaming Markets":["gaming","axie","roblox","cs2","skins","video-game"],

  # Quant methods
  "Cramér-Rao / Fisher Info":["cramer-rao","fisher-information"],
  "HMM":["hmm","hidden-markov"],
  "Bates SVJ":["bates","svj","stochastic-vol-jump"],
  "Black-Scholes":["black-scholes"],
  "Calibration":["calibration","calibrate"],
  "Greeks":["greeks","delta","gamma","vega","theta"],

  # Geopolitical / events
  "Iran War":["iran"], "Russia/Ukraine":["russia","ukraine","russias"], "China":["china","chinese","cny"],
  "India":["india","indias","nifty","sebi","rbi"], "UAE/Dubai":["uae","dubai","aed","nakheel","emaar"],
  "Europe":["europe","eu","ecb","euro"], "Japan":["japan","yen","boj","mufg"],
  "Geopolitics":["war","sanctions","embargo","geopolitical"],

  # Regulators & venues
  "SEC":["sec"], "CFTC":["cftc"], "FOMC/Fed":["fomc","fed","powell"],
  "RBI":["rbi"], "SEBI":["sebi"], "ECB":["ecb"], "CME":["cme"], "LME":["lme"], "CBOE":["cboe"],

  # Instruments
  "Forwards/Futures":["forward","forwards","futures","future"],
  "Options":["option","options","call","put","straddle","strangle"],
  "Swaps":["swap","swaps","ois","irs"],
  "ETFs":["etf","etfs"],
  "SPACs":["spac","spacs"],
  "Structured Products":["structured","note","notes","collar","prepaid-forward"],

  # Themes
  "Court / Legal":["court","filings","lawsuit","sec-fines","fines","fined","manipulation","insider-trading"],
  "Leverage":["leverage","leveraged"],
  "Liquidity":["liquidity","fire-sale","liquidation"],
  "Performance":["returns","performance","pnl","p&l","alpha"],
  "Crisis / Drawdown":["crisis","crash","drawdown","blowup","collapse","panic","selloff"],
}

# Cluster definitions (broader buckets — color groups in the graph)
CLUSTERS = [
  ("Quant Methods",        {"Cramér-Rao / Fisher Info","HMM","Bates SVJ","Black-Scholes","Calibration","Greeks","Quantitative","Volatility"}),
  ("Hedge Fund Strategy",  {"Citadel","Millennium","Bridgewater","Renaissance","Two Sigma","BlueCrest","DE Shaw","Brevan Howard","Point72","Balyasny","Elliott Management","Bill Ackman","Carl Icahn","Activism","Event-Driven","Distressed","Market Making","Virtu","Jane Street","Da Vinci","Bobby Jain","Boaz Weinstein"}),
  ("Macro & Geopolitics",  {"Macro","Macro Trading","Iran War","Russia/Ukraine","China","India","UAE/Dubai","Europe","Japan","Geopolitics","FOMC/Fed","ECB","RBI","SEBI"}),
  ("FX & EM",              {"FX","Carry Trade","Forwards/Futures"}),  # NDFs => FX
  ("Credit & Private Credit", {"Credit","Fixed Income","Private Credit","Distressed","Blue Owl","Apollo","KKR","Blackstone"}),
  ("Commodities",          {"Commodities","Andurand"}),
  ("Microstructure & Regulation", {"Market Making","Arbitrage","SEC","CFTC","Court / Legal","Liquidity"}),
  ("Alternative Markets",  {"Prediction Markets","Gaming Markets","Crypto","Real Estate","SPACs","Structured Products","ETFs"}),
]

CLUSTER_COLORS = {
  "Quant Methods":              "#4e79a7",
  "Hedge Fund Strategy":        "#e15759",
  "Macro & Geopolitics":        "#f28e2b",
  "FX & EM":                    "#76b7b2",
  "Credit & Private Credit":    "#59a14f",
  "Commodities":                "#edc948",
  "Microstructure & Regulation":"#b07aa1",
  "Alternative Markets":        "#ff9da7",
  "Other":                      "#9c755f",
}

def extract_concepts(slug):
    s = slug.lower()
    hits = []
    for concept, patterns in TAXONOMY.items():
        for p in patterns:
            # match as whole token (slug uses '-' separators); allow substring for multi-word patterns
            if "-" in p:
                if p in s:
                    hits.append(concept); break
            else:
                if re.search(rf"(^|-){re.escape(p)}($|-)", s):
                    hits.append(concept); break
    return list(dict.fromkeys(hits))   # dedupe preserve order

def assign_cluster(concepts):
    scores = []
    for name, members in CLUSTERS:
        scores.append((name, sum(1 for c in concepts if c in members)))
    scores.sort(key=lambda x: -x[1])
    return scores[0][0] if scores[0][1] > 0 else "Other"

def infer_difficulty(concepts, slug):
    quanty = {"Cramér-Rao / Fisher Info","HMM","Bates SVJ","Calibration","Greeks","Black-Scholes","Quantitative","Volatility"}
    if any(c in quanty for c in concepts): return "advanced"
    if "Arbitrage" in concepts or "Market Making" in concepts: return "advanced"
    if any(c in concepts for c in ["Macro","Macro Trading","Geopolitics","Iran War","Russia/Ukraine","China","India"]): return "intermediate"
    if not concepts: return "beginner"
    return "intermediate"

# ---------------------------------------------------------------------------
# 4. Build thread nodes
# ---------------------------------------------------------------------------
threads = []
concept_set = Counter()
for idx, p in enumerate(posts):
    slug = p["slug"]
    title = slug_to_title(slug)
    concepts = extract_concepts(slug)
    cluster = assign_cluster(concepts)
    diff = infer_difficulty(concepts, slug)
    known = KNOWN.get(slug, {})
    summary = known.get("summary") or f"Substack post · {p['date']}"
    threads.append({
        "id": f"t{idx}",
        "slug": slug,
        "title": title,
        "url": p["url"],
        "date": p["date"],
        "summary": summary,
        "concepts": concepts,
        "cluster": cluster,
        "difficulty": diff,
    })
    for c in concepts: concept_set[c] += 1

# ---------------------------------------------------------------------------
# 5. Concept nodes (only those used by 2+ threads stay as graph nodes)
# ---------------------------------------------------------------------------
concepts_out = []
for name, count in concept_set.most_common():
    concepts_out.append({
        "id": f"c_{re.sub(r'[^a-z0-9]+','_', name.lower())}",
        "name": name,
        "count": count,
    })

# ---------------------------------------------------------------------------
# 6. Edges between threads (shared concepts, Jaccard weighted)
# ---------------------------------------------------------------------------
edges = []
by_id = {t["id"]: set(t["concepts"]) | {"@cluster:" + t["cluster"]} for t in threads}
ids = list(by_id.keys())
EDGE_THRESHOLD = 0.18
MAX_DEG = 8
adj = defaultdict(list)
for a, b in combinations(ids, 2):
    sa, sb = by_id[a], by_id[b]
    if not sa or not sb: continue
    inter = len(sa & sb)
    if inter < 2: continue
    union = len(sa | sb)
    j = inter / union
    if j >= EDGE_THRESHOLD:
        adj[a].append((b, j, inter))
        adj[b].append((a, j, inter))

seen = set()
for a, neighbors in adj.items():
    neighbors.sort(key=lambda x: -x[1])
    for b, j, inter in neighbors[:MAX_DEG]:
        key = tuple(sorted([a,b]))
        if key in seen: continue
        seen.add(key)
        edges.append({"source": a, "target": b, "weight": round(j,3), "shared": inter, "type":"thread"})

print(f"Edges: {len(edges)}; threads: {len(threads)}; concepts: {len(concepts_out)}")

# ---------------------------------------------------------------------------
# 7. Learning paths (curated reading sequences)
# ---------------------------------------------------------------------------
def path_for(name, *needles, limit=10):
    matches = []
    for t in threads:
        s = t["slug"]
        if any(n in s for n in needles):
            matches.append(t["id"])
    return {"name": name, "threads": matches[:limit]}

learning_paths = [
    path_for("Quant Volatility Deep Dive",
             "volatility","spxvix","calibration","bates","svj","black-scholes","cramer-rao","fisher"),
    path_for("Hedge Fund Alpha Tour",
             "hedge-fund","alpha","virtu","jane","citadel","millennium","renaissance","bluecrest","de-shaw","bridgewater"),
    path_for("FX, EM & Carry",
             "ndf","currency","carry","peg","emerging","aed","inr","yen","yuan"),
    path_for("Geopolitical Alpha",
             "iran","war","russia","china","india","defense","oil-war","dubai","desert"),
    path_for("Credit, Distressed & Activism",
             "credit","obdc","elliott","activist","distressed","sukuk","collapse","cds"),
    path_for("Microstructure & Regulation",
             "market-making","arbitrage","sec","cftc","manipulation","fines","court"),
    path_for("Alternative Markets",
             "prediction","gaming","axie","roblox","cs2","crypto","spac"),
    path_for("Commodities & Energy",
             "oil","crude","copper","gold","silver","gas","commodity","andurand","tcrcs","eua","ets"),
]
learning_paths = [p for p in learning_paths if len(p["threads"]) >= 3]

# ---------------------------------------------------------------------------
# 8. Quizzes (one per cluster, sampled threads)
# ---------------------------------------------------------------------------
quizzes = []
by_cluster = defaultdict(list)
for t in threads: by_cluster[t["cluster"]].append(t)
for cl, ts in by_cluster.items():
    for t in ts[:3]:
        if not t["concepts"]: continue
        quizzes.append({
            "id": f"q_{t['id']}",
            "thread": t["id"],
            "question": f"Which concepts does \"{t['title']}\" primarily touch?",
            "answer": ", ".join(t["concepts"][:4]) or "—",
            "cluster": cl,
        })

# ---------------------------------------------------------------------------
# 9. Emit
# ---------------------------------------------------------------------------
data = {
  "publication": {
    "name": "Navnoor Bawa",
    "tagline": "Quantitative Researcher",
    "url": "https://navnoorbawa.substack.com/",
    "post_count": len(threads),
  },
  "clusters": [{"name": name, "color": CLUSTER_COLORS.get(name,"#9c755f")} for name,_ in CLUSTERS] + [{"name":"Other","color":CLUSTER_COLORS["Other"]}],
  "threads": threads,
  "concepts": concepts_out,
  "edges": edges,
  "learning_paths": learning_paths,
  "quizzes": quizzes,
}

OUT.write_text(json.dumps(data, indent=2))
print(f"Wrote {OUT} ({OUT.stat().st_size:,} bytes)")
