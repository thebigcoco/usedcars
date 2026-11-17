"""Shared engine: 原廠認證中古車 vs 8891 二手車市場行情比較報告.

Brand scripts (build_report.py for BMW, build_benz_report.py for Mercedes-Benz) build a list of
normalised certified-car rows and a config dict, then call `make_report()`.

Row fields each brand script must supply:
  id, url, model (comparison group label, e.g. "320i" / "C200"), family (colour / filter key),
  gen, kit, color_cat, fac ("YYYY/MM"), year (出廠年), lic ("YYYY/MM"), lic_date (datetime.date),
  km (int), price (萬), new (新車價 萬), note (新車價依據), status, dealer
"""
import datetime, html, json, re, time, urllib.request

TODAY = datetime.date(2026, 11, 17)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
PUSH = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)')


# ---------------------------------------------------------------- 8891 scraping
def parse_8891_page(t):
    """Extract listing objects (those with itemId/price/makeYear) from an 8891 Next.js page."""
    s = "".join(json.loads('"' + m + '"') for m in PUSH.findall(t))
    out = []
    for m in re.finditer(r'"itemId":(\d+)', s):
        i, depth = m.start(), 0
        while i > 0:
            i -= 1
            if s[i] == "}": depth += 1
            elif s[i] == "{":
                if depth == 0: break
                depth -= 1
        j, depth = i, 0
        while j < len(s):
            if s[j] == "{": depth += 1
            elif s[j] == "}":
                depth -= 1
                if depth == 0: break
            j += 1
        try:
            o = json.loads(s[i:j + 1])
        except ValueError:
            continue
        if "price" in o and "makeYear" in o:
            out.append(o)
    return out


def load_8891(paths, cache, path=None):
    """Fetch every page of each 8891 list path (e.g. "bmw/3-series/320i"); cache raw items to `cache`."""
    if path:
        return json.load(open(path, encoding="utf-8"))
    items = {}
    for p in paths:
        for page in range(1, 80):
            req = urllib.request.Request(f"https://auto.8891.com.tw/{p}?page={page}", headers={"User-Agent": UA})
            found = parse_8891_page(urllib.request.urlopen(req, timeout=30).read().decode("utf-8"))
            if not found:
                break
            for o in found:
                items[o["itemId"]] = o
            time.sleep(1)
    items = list(items.values())
    json.dump(items, open(cache, "w", encoding="utf-8"), ensure_ascii=False)
    return items


# ---------------------------------------------------------------- statistics
def quart(v, q):
    k = (len(v) - 1) * q; lo = int(k); hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def parse_market(items, group_of, cert_re):
    """8891 listings -> {(group, 出廠年): [(price, km, is_cert_relisting, itemId)]}.
    `group_of(item)` returns the comparison group label or None to skip. Drops 電洽."""
    groups = {}
    for o in items:
        m = re.match(r"([\d.]+)萬", o["price"])
        g = group_of(o)
        if not m or not g:
            continue
        km = re.match(r"([\d.]+)(萬)?公里", o.get("mileage", ""))
        km = float(km.group(1)) * (10000 if km.group(2) else 1) if km else None
        cert = bool(cert_re.search((o.get("title") or "") + (o.get("subTitle") or "")))
        groups.setdefault((g, int(o["makeYear"][:4])), []).append((float(m.group(1)), km, cert, o["itemId"]))
    return groups


def market_stats(groups):
    """Price / mileage distribution of the non-certified market per group. Drops bait prices (<40% of median)."""
    stats = {}
    for k, v in groups.items():
        med = quart(sorted(p for p, *_ in v), .5)
        v = [x for x in v if x[0] >= med * 0.4]
        mk = [x for x in v if not x[2]]
        if not mk:
            continue
        ps = sorted(x[0] for x in mk)
        kms = sorted(x[1] for x in mk if x[1] is not None)
        stats[k] = dict(n=len(ps), n_cert=sum(x[2] for x in v), pts=[(x[0], x[1]) for x in mk if x[1] is not None],
                        min=ps[0], p25=quart(ps, .25), med=quart(ps, .5), p75=quart(ps, .75), max=ps[-1],
                        km_med=quart(kms, .5) if kms else None,
                        km_p25=quart(kms, .25) if kms else None, km_p75=quart(kms, .75) if kms else None)
    return stats


def same_km_comp(s, km, k=7):
    """Median price of the k market listings (same group+year) closest in mileage."""
    if not s or len(s["pts"]) < 3:
        return None
    near = sorted(s["pts"], key=lambda t: abs(t[1] - km))[:k]
    ps = sorted(p for p, _ in near); kms = [m for _, m in near]
    return dict(price=quart(ps, .5), n=len(near), km_lo=min(kms), km_hi=max(kms))


def enrich(rows, mkt):
    """Add age, depreciation and market-comparison fields to each certified-car row."""
    for r in rows:
        age = round((TODAY - r["lic_date"]).days / 365.25, 1)  # 顯示用車齡：小數點後一位
        age_int = max(round(age), 1)                           # 計算用車齡：四捨五入取整數，最少 1 年
        dep = r["new"] - r["price"]; dep_pct = dep / r["new"] * 100
        s = mkt.get((r["model"], r["year"]))
        c = same_km_comp(s, r["km"])
        r.update(age=age, age_int=age_int, dep=dep, dep_pct=dep_pct, yr_pct=dep_pct / age_int,
                 cagr=(1 - (r["price"] / r["new"]) ** (1 / age_int)) * 100,
                 mkt_med=s["med"] if s else None, vs_mkt=(r["price"] / s["med"] - 1) * 100 if s else None,
                 comp=c, comp_price=c["price"] if c else None,
                 vs_comp=(r["price"] / c["price"] - 1) * 100 if c else None,
                 diff_comp=r["price"] - c["price"] if c else None)
    rows.sort(key=lambda r: (r["family"], r["model"], r["year"], r["price"]))
    return rows


MAX_AGE = 12


def market_age(year):
    """8891 只有出廠年：假設年中出廠，算到今天後四捨五入，最少 1 年。"""
    return max(round(TODAY.year + (TODAY.month - 0.5) / 12 - (year + 0.5)), 1)


def depreciation_trend(rows, groups, cfg):
    """{family: {age: {"cert": [dep%...], "mkt": [dep%...]}}} — 認證車用整數車齡，市場車用出廠年估車齡。"""
    tr = {k: {} for k, _ in cfg["families"]}
    for r in rows:
        if r["age_int"] <= MAX_AGE:
            tr[r["family"]].setdefault(r["age_int"], {"cert": [], "mkt": []})["cert"].append(r["dep_pct"])
    mn = cfg.get("market_new")
    if mn:
        for (g, y), v in groups.items():
            fam = cfg["family_of"](g); np = mn(g, y); age = market_age(y)
            if fam not in tr or not np or age > MAX_AGE:
                continue
            med = quart(sorted(p for p, *_ in v), .5)
            for p, _, cert, _ in v:
                if not cert and p >= med * 0.4:
                    tr[fam].setdefault(age, {"cert": [], "mkt": []})["mkt"].append((np - p) / np * 100)
    return tr


def med(xs):
    return quart(sorted(xs), .5) if xs else None


def render_trend(tr, cfg):
    fams = cfg["families"]
    ages = sorted({a for t in tr.values() for a in t})
    if not ages:
        return "", ""
    amax = max(ages)
    # chart
    W, H, PL, PR, PT, PB = 760, 300, 46, 20, 14, 34
    X = lambda a: PL + a / amax * (W - PL - PR)
    Y = lambda p: PT + (100 - p) / 100 * (H - PT - PB)
    s = ""
    for p in range(0, 101, 20):
        s += f'<line x1="{PL}" x2="{W-PR}" y1="{Y(p):.1f}" y2="{Y(p):.1f}" class="g"/><text x="{PL-6}" y="{Y(p)+4:.1f}" text-anchor="end">{p}%</text>'
    for a in range(0, amax + 1):
        s += f'<text x="{X(a):.1f}" y="{H-12}" text-anchor="middle">{a}年</text>'
    for i, (k, lbl) in enumerate(fams):
        pts = [(0, 0.0)] + [(a, med(tr[k][a]["mkt"])) for a in sorted(tr[k]) if tr[k][a]["mkt"]]
        if len(pts) > 1:
            s += f'<polyline points="{" ".join(f"{X(a):.1f},{Y(p):.1f}" for a, p in pts)}" class="ln{i}"/>'
            for a, p in pts[1:]:
                n = len(tr[k][a]["mkt"])
                s += f'<circle cx="{X(a):.1f}" cy="{Y(p):.1f}" r="3.5" class="d{i}"><title>{esc(lbl)} 市場 {a}年：折價 {p:.1f}%（{n} 台中位數）</title></circle>'
        for a in sorted(tr[k]):
            c = tr[k][a]["cert"]
            if c:
                p = med(c)
                s += (f'<rect x="{X(a)-6:.1f}" y="{Y(p)-6:.1f}" width="12" height="12" transform="rotate(45 {X(a):.1f} {Y(p):.1f})" class="cd{i}">'
                      f'<title>{esc(lbl)} {cfg["cert"]} 認證車 {a}年：折價 {p:.1f}%（{len(c)} 台中位數）</title></rect>')
    chart = f'<svg viewBox="0 0 {W} {H}" width="100%" style="min-width:520px">{s}</svg>'
    # table
    head1 = '<tr><th rowspan="2">車齡</th>' + "".join(f'<th colspan="4" class="grp">{esc(lbl)}</th>' for _, lbl in fams) + "</tr>"
    head2 = "<tr>" + "".join('<th class="n">市場<br>累計折價%</th><th class="n">市場<br>當年新增</th><th class="n">市場<br>台數</th><th class="n bp">%%C%%<br>累計折價%</th>' for _ in fams) + "</tr>"
    body = ""
    for a in range(1, amax + 1):
        body += f"<tr><td>{a} 年</td>"
        for k, _ in fams:
            t = tr[k].get(a, {"cert": [], "mkt": []})
            m = med(t["mkt"])
            prev = 0.0 if a == 1 else med(tr[k].get(a - 1, {"mkt": []})["mkt"])
            inc = m - prev if m is not None and prev is not None else None
            c = med(t["cert"])
            body += (f'<td class="n"><b>{f(m)}{"%" if m is not None else ""}</b></td><td class="n">{sgn(inc)}{"%" if inc is not None else ""}</td>'
                     f'<td class="n mut">{len(t["mkt"]) or "—"}</td>'
                     f'<td class="n bp">{f(c)}{"%" if c is not None else ""}{f"<span class=mut>（{len(t["cert"])}）</span>" if c is not None else ""}</td>')
        body += "</tr>"
    table = f'<table><thead>{head1}{head2}</thead><tbody>{body}</tbody></table>'
    return chart, table


HOLD_YEARS, MIN_N = 3, 5


def render_hold(tr, cfg):
    """買進車齡 a、持有 HOLD_YEARS 年後賣出：損失佔買價 % =(折價%[a+H] − 折價%[a]) ÷ (100 − 折價%[a])。"""
    fams = cfg["families"]
    curve = {}
    for k, _ in fams:
        m = {a: med(v["mkt"]) for a, v in tr[k].items() if len(v["mkt"]) >= MIN_N}
        m[0] = 0.0
        curve[k] = m
    buy_ages = [a for a in range(0, MAX_AGE) if any(a in curve[k] and a + HOLD_YEARS in curve[k] for k, _ in fams)]
    if not buy_ages:
        return ""
    loss = {k: {a: (curve[k][a + HOLD_YEARS] - curve[k][a]) / (100 - curve[k][a]) * 100
                for a in buy_ages if a in curve[k] and a + HOLD_YEARS in curve[k]} for k, _ in fams}
    best = {k: min(v, key=v.get) if v else None for k, v in loss.items()}
    head = "<tr><th>買進時車齡 → 賣出</th>" + "".join(f'<th class="n">{esc(lbl)}</th>' for _, lbl in fams) + "</tr>"
    body = ""
    for a in buy_ages:
        body += f'<tr><td>{"新車" if a == 0 else f"{a} 年"} → {a + HOLD_YEARS} 年</td>'
        for k, _ in fams:
            v = loss[k].get(a)
            cls = "lo" if a == best[k] else ""
            body += f'<td class="n {cls}">{"<b>" if cls else ""}{f(v, 0)}{"%" if v is not None else ""}{"</b> 最低" if cls else ""}</td>'
        body += "</tr>"
    return f'<table style="width:auto;min-width:60%"><thead>{head}</thead><tbody>{body}</tbody></table>'


# ---------------------------------------------------------------- rendering
def f(v, n=1): return "—" if v is None else f"{v:,.{n}f}"
def sgn(v): return "—" if v is None else f"{v:+,.1f}"
def pct(v): return "—" if v is None else f"{v:+.1f}%"
def kmw(v): return "—" if v is None else f"{v/10000:.1f}萬"
def esc(v): return html.escape(str(v))
def avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None
def tone(v):
    if v is None: return ""
    return "hi" if v >= 5 else "lo" if v <= -5 else ""


def render(rows, mkt, n_items, cfg, trend=None):
    C = cfg["cert"]
    trend_chart, trend_table = render_trend(trend, cfg) if trend else ("", "")
    hold_table = render_hold(trend, cfg) if trend else ""
    fam = {k: i for i, (k, _) in enumerate(cfg["families"])}
    dot = lambda r: f'd{fam[r["family"]]}'
    order = {m: i for i, m in enumerate(cfg.get("model_order", []))}
    groups = {}
    for r in rows:
        groups.setdefault((r["model"], r["year"]), []).append(r)
    keys = sorted(groups, key=lambda k: (fam[groups[k][0]["family"]], order.get(k[0], 99), k[0], k[1]))
    n_mkt = sum(mkt[k]["n"] for k in keys if k in mkt)
    n_cert_rel = sum(s["n_cert"] for s in mkt.values())

    # comparison table
    cmp_rows = ""
    for k in keys:
        g = groups[k]; s = mkt.get(k)
        bp = avg(r["price"] for r in g); bk = avg(r["km"] for r in g)
        vm = (bp / s["med"] - 1) * 100 if s else None
        vc = avg(r["vs_comp"] for r in g); dc = avg(r["diff_comp"] for r in g)
        cmp_rows += (f'<tr><td>{esc(k[0])}</td><td>{k[1]}</td><td>{esc(g[0]["gen"])}</td>'
                     f'<td class="n bp">{len(g)}</td><td class="n bp">{f(bp)}</td><td class="n bp">{kmw(bk)}</td>'
                     f'<td class="n">{s["n"] if s else 0}</td><td class="n">{f(s["med"]) if s else "—"}</td>'
                     f'<td class="n">{(f(s["p25"]) + " ~ " + f(s["p75"])) if s else "—"}</td><td class="n">{kmw(s["km_med"]) if s else "—"}</td>'
                     f'<td class="n {tone(vm)}">{pct(vm)}</td><td class="n {tone(vc)}">{sgn(dc)}</td><td class="n {tone(vc)}"><b>{pct(vc)}</b></td></tr>')

    # distribution strip chart
    RH, LW, CW = 34, 110, 620
    xmax = max(max([s["max"] for k, s in mkt.items() if k in groups] or [0]), max(r["price"] for r in rows)) * 1.05
    X = lambda v: LW + v / xmax * CW
    step = 25 if xmax <= 300 else 50 if xmax <= 600 else 100
    dist = ""
    for i, k in enumerate(keys):
        cy = 24 + i * RH + RH / 2
        dist += f'<text x="{LW-10}" y="{cy+4}" text-anchor="end" class="lbl">{esc(k[0])} {k[1]}</text>'
        s = mkt.get(k)
        if s:
            dist += (f'<g><title>市場 {esc(k[0])} {k[1]}年：{s["n"]} 台｜最低 {s["min"]}｜P25 {s["p25"]:.1f}｜中位數 {s["med"]:.1f}｜P75 {s["p75"]:.1f}｜最高 {s["max"]}｜中位里程 {kmw(s["km_med"])}公里</title>'
                     f'<line x1="{X(s["min"]):.1f}" x2="{X(s["max"]):.1f}" y1="{cy}" y2="{cy}" class="wh"/>'
                     f'<rect x="{X(s["p25"]):.1f}" y="{cy-8}" width="{max(X(s["p75"])-X(s["p25"]),2):.1f}" height="16" rx="3" class="bx"/>'
                     f'<line x1="{X(s["med"]):.1f}" x2="{X(s["med"]):.1f}" y1="{cy-10}" y2="{cy+10}" class="md"/></g>'
                     f'<text x="{X(s["max"])+6:.1f}" y="{cy+4}">n={s["n"]}・{kmw(s["km_med"])}km</text>')
        else:
            dist += f'<text x="{LW+4}" y="{cy+4}">8891 無同年份樣本</text>'
        for r in groups[k]:
            dist += (f'<circle cx="{X(r["price"]):.1f}" cy="{cy}" r="4.5" class="{dot(r)}">'
                     f'<title>{C} {esc(r["model"])} {r["fac"]} {esc(r["kit"])}｜{r["price"]}萬｜{r["km"]:,} km｜vs 同年中位數 {pct(r["vs_mkt"])}｜vs 同里程行情 {pct(r["vs_comp"])}</title></circle>')
    DH = 24 + len(keys) * RH + 24
    grid = "".join(f'<line x1="{X(v):.1f}" x2="{X(v):.1f}" y1="16" y2="{DH-20}" class="g"/><text x="{X(v):.1f}" y="{DH-6}" text-anchor="middle">{v}萬</text>'
                   for v in range(0, int(xmax) + 1, step))
    dist_svg = f'<svg viewBox="0 0 {LW+CW+110} {DH}" width="100%" style="min-width:560px">{grid}{dist}</svg>'

    # small multiples: price vs mileage
    pan = ""
    PW, PH, PL, PB = 300, 190, 40, 26
    for k in keys:
        s = mkt.get(k); g = groups[k]
        pts = (s["pts"] if s else []) + [(r["price"], r["km"]) for r in g]
        kmax = max(t[1] for t in pts) * 1.08 or 1
        lo = min(t[0] for t in pts); hi = max(t[0] for t in pts)
        pad = max((hi - lo) * .12, 3); lo -= pad; hi += pad
        px = lambda km: PL + km / kmax * (PW - PL - 10)
        py = lambda p: 10 + (hi - p) / (hi - lo) * (PH - 10 - PB)
        body = ""
        for t in range(3):
            v = lo + pad + (hi - lo - 2 * pad) * t / 2
            body += f'<line x1="{PL}" x2="{PW-10}" y1="{py(v):.1f}" y2="{py(v):.1f}" class="g"/><text x="{PL-4}" y="{py(v)+4:.1f}" text-anchor="end">{v:.0f}</text>'
        for t in range(3):
            v = kmax / 1.08 * t / 2
            body += f'<text x="{px(v):.1f}" y="{PH-8}" text-anchor="middle">{v/10000:.1f}萬km</text>'
        if s:
            for p, km in s["pts"]:
                body += f'<circle cx="{px(km):.1f}" cy="{py(p):.1f}" r="3" class="mk"><title>市場 {p}萬｜{km:,.0f} km</title></circle>'
        for r in g:
            body += (f'<circle cx="{px(r["km"]):.1f}" cy="{py(r["price"]):.1f}" r="4.5" class="{dot(r)}">'
                     f'<title>{C} {r["fac"]} {esc(r["kit"])}｜{r["price"]}萬｜{r["km"]:,} km｜同里程行情 {f(r["comp_price"])}萬（{pct(r["vs_comp"])}）</title></circle>')
        vc = avg(r["vs_comp"] for r in g)
        pan += (f'<div class="pan"><div class="pt"><b>{esc(k[0])} {k[1]}</b><span class="mut">{C} {len(g)}・市場 {s["n"] if s else 0}</span>'
                f'<span class="tag {tone(vc)}">{pct(vc)}</span></div><svg viewBox="0 0 {PW} {PH}" width="100%">{body}</svg></div>')

    # depreciation scatter + table
    W, H, P = 720, 280, 40
    maxage = max(max(r["age"] for r in rows) * 1.05, 2)
    dep_svg = ""
    for p in range(0, 101, 20):
        y = H - P - p / 100 * (H - 2 * P)
        dep_svg += f'<line x1="{P}" x2="{W-P}" y1="{y}" y2="{y}" class="g"/><text x="{P-6}" y="{y+4}" text-anchor="end">{p}%</text>'
    for a in range(0, int(maxage) + 1, 1 if maxage < 8 else 2):
        dep_svg += f'<text x="{P + a / maxage * (W - 2 * P):.1f}" y="{H-P+16}" text-anchor="middle">{a}年</text>'
    for r in rows:
        dep_svg += (f'<circle cx="{P + r["age"] / maxage * (W - 2 * P):.1f}" cy="{H - P - max(r["dep_pct"], 0) / 100 * (H - 2 * P):.1f}" r="5" class="{dot(r)}">'
                    f'<title>{esc(r["model"])} {r["fac"]} {esc(r["kit"])}｜售價 {r["price"]}萬｜新車 {r["new"]}萬｜折價 {r["dep_pct"]:.1f}%｜車齡 {r["age"]:.1f}年</title></circle>')
    dep_rows = ""
    for k in keys:
        g = groups[k]
        dep_rows += (f'<tr><td>{esc(k[0])}</td><td>{k[1]}</td><td class="n">{len(g)}</td><td class="n">{f(avg(r["new"] for r in g),0)}</td>'
                     f'<td class="n">{f(avg(r["price"] for r in g))}</td><td class="n">{f(avg(r["dep"] for r in g))}</td>'
                     f'<td class="n">{f(avg(r["dep_pct"] for r in g))}%</td><td class="n">{f(avg(r["yr_pct"] for r in g))}%</td>'
                     f'<td class="n">{f(avg(r["age"] for r in g))}</td></tr>')

    # detail table
    det = ""
    dv = lambda v: "" if v is None else v
    for r in rows:
        c = r["comp"]
        ctitle = f'取市場同年份里程最接近的 {c["n"]} 台（{kmw(c["km_lo"])}~{kmw(c["km_hi"])}公里）之中位數' if c else "市場樣本不足（少於 3 台）"
        det += (f'<tr data-fam="{esc(r["family"])}"><td><a href="{esc(r["url"])}" target="_blank">{esc(r["model"])}</a></td>'
                f'<td data-v="{r["year"]}">{r["fac"]}</td><td>{esc(r["kit"])}</td><td>{esc(r["color_cat"])}</td>'
                f'<td class="n" data-v="{r["km"]}">{r["km"]:,}</td>'
                f'<td class="n bp" data-v="{r["price"]}"><b>{f(r["price"])}</b></td>'
                f'<td class="n" data-v="{dv(r["mkt_med"])}">{f(r["mkt_med"])}</td>'
                f'<td class="n {tone(r["vs_mkt"])}" data-v="{dv(r["vs_mkt"])}">{pct(r["vs_mkt"])}</td>'
                f'<td class="n" data-v="{dv(r["comp_price"])}" title="{esc(ctitle)}">{f(r["comp_price"])}</td>'
                f'<td class="n {tone(r["vs_comp"])}" data-v="{dv(r["diff_comp"])}">{sgn(r["diff_comp"])}</td>'
                f'<td class="n {tone(r["vs_comp"])}" data-v="{dv(r["vs_comp"])}"><b>{pct(r["vs_comp"])}</b></td>'
                f'<td>{r["lic"]}</td><td class="n" data-v="{r["age"]}">{r["age"]:.1f}</td>'
                f'<td class="n" data-v="{r["new"]}" title="{esc(r["note"])}">{r["new"]:g}</td>'
                f'<td class="n" data-v="{r["dep"]}">{f(r["dep"])}</td>'
                f'<td class="n" data-v="{r["dep_pct"]}">{f(r["dep_pct"])}%</td>'
                f'<td class="n" data-v="{r["yr_pct"]}">{f(r["yr_pct"])}%</td>'
                f'<td class="n" data-v="{r["cagr"]}">{f(r["cagr"])}%</td>'
                f'<td>{esc(r["gen"])}</td><td>{esc(r["status"])}</td><td>{esc(r["dealer"])}</td></tr>')

    # KPIs & findings
    vcs = [r["vs_comp"] for r in rows if r["vs_comp"] is not None]
    vms = [r["vs_mkt"] for r in rows if r["vs_mkt"] is not None]
    n_hi = sum(v >= 5 for v in vcs); n_lo = sum(v <= -5 for v in vcs); n_mid = len(vcs) - n_hi - n_lo
    grp_vc = sorted(((avg(r["vs_comp"] for r in groups[k]), k) for k in keys if avg(r["vs_comp"] for r in groups[k]) is not None), reverse=True)
    exp = "、".join(f'{k[0]} {k[1]}（{pct(v)}）' for v, k in grp_vc if v >= 5) or "無"
    chp = "、".join(f'{k[0]} {k[1]}（{pct(v)}）' for v, k in grp_vc if v <= -5) or "無"
    young = [r["vs_comp"] for r in rows if r["vs_comp"] is not None and r["year"] >= 2023]
    old = [r["vs_comp"] for r in rows if r["vs_comp"] is not None and r["year"] < 2023]
    no_cmp = [r for r in rows if r["vs_comp"] is None]
    extra = f'<li>{len(no_cmp)} 台因 8891 同車款同年份樣本少於 3 台，無法計算同里程行情：' + "、".join(sorted({f'{r["model"]} {r["year"]}' for r in no_cmp})) + '。</li>' if no_cmp else ""

    fam_css = "".join(f'svg .d{i}{{fill:var(--f{i});stroke:var(--card)}}' for i in range(len(cfg["families"])))
    pal_l = ["#1c69d4", "#e4572e", "#12b76a", "#7a5af8"]; pal_d = ["#5b9bff", "#ff7a52", "#47cd89", "#a48afb"]
    vars_l = "".join(f"--f{i}:{pal_l[i]};" for i in range(len(cfg["families"])))
    vars_d = "".join(f"--f{i}:{pal_d[i]};" for i in range(len(cfg["families"])))
    legend = "".join(f'<span style="background:var(--f{i})"></span>{esc(lbl)}' for i, (_, lbl) in enumerate(cfg["families"]))
    buttons = '<button class="on" data-f="">全部</button>' + "".join(f'<button data-f="{esc(k)}">{esc(lbl)}</button>' for k, lbl in cfg["families"])

    trend_css = "".join(f'svg .ln{i}{{fill:none;stroke:var(--f{i});stroke-width:2.5}}svg .cd{i}{{fill:var(--card);stroke:var(--f{i});stroke-width:2.5}}'
                        for i in range(len(cfg["families"])))
    trend_legend = "".join(f'<span style="background:var(--f{i})"></span>{esc(lbl)}' for i, (_, lbl) in enumerate(cfg["families"]))
    rep = {
        "TREND_TABLE": trend_table, "TREND_CHART": trend_chart, "TREND_CSS": trend_css, "TREND_LEGEND": trend_legend,
        "TREND_NOTE": cfg.get("trend_note", ""), "HOLD_TABLE": hold_table, "BUY_ADVICE": cfg.get("buy_advice", ""),
        "HOLD_YEARS": str(HOLD_YEARS), "MIN_N": str(MIN_N),
        "TITLE": cfg["title"], "H1": cfg["h1"], "SUB": cfg["sub"], "C": C, "LEGEND": legend, "BUTTONS": buttons,
        "FAMVARS_L": vars_l, "FAMVARS_D": vars_d, "FAMCSS": fam_css, "KEY": cfg["storage_key"],
        "MARKET_NOTE": cfg["market_note"], "NEWPRICE_NOTE": cfg["newprice_note"], "VARIANT_NOTE": cfg["variant_note"],
        "KIT_LABEL": cfg.get("kit_label", "版本"), "INFO_LABEL": cfg.get("info_label", "世代・狀態・經銷商"),
        "TODAY": str(TODAY), "N_CERT": str(len(rows)), "N_MKT": str(n_mkt), "N_ITEMS": str(n_items), "N_CERTREL": str(n_cert_rel),
        "MED_VC": pct(quart(sorted(vcs), .5)) if vcs else "—", "AVG_VM": pct(avg(vms)),
        "N_HI": str(n_hi), "N_MID": str(n_mid), "N_LO": str(n_lo),
        "YOUNG": pct(avg(young)), "OLD": pct(avg(old)), "EXP": exp, "CHP": chp, "EXTRA": extra,
        "CMP_ROWS": cmp_rows, "DIST_SVG": dist_svg, "PANELS": pan, "DEP_SVG": f'<svg viewBox="0 0 {W} {H}" width="100%">{dep_svg}</svg>',
        "DEP_ROWS": dep_rows, "DET": det,
    }
    out = TEMPLATE
    for k, v in rep.items():
        out = out.replace("%%" + k + "%%", v)
    return out


def make_report(rows, items, group_of, cfg, out_html, out_json):
    groups = parse_market(items, group_of, cfg["cert_re"])
    mkt = market_stats(groups)
    rows = enrich(rows, mkt)
    trend = depreciation_trend(rows, groups, cfg)
    open(out_html, "w", encoding="utf-8").write(render(rows, mkt, len(items), cfg, trend))
    json.dump([{k: (str(v) if isinstance(v, datetime.date) else v) for k, v in r.items()} for r in rows],
              open(out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(len(rows), "rows ->", out_html)
    return rows, mkt


TEMPLATE = r"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>%%TITLE%%</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--fg:#1a1d23;--mut:#667085;--line:#e4e7ec;--acc:#1c69d4;%%FAMVARS_L%%--box:#d0d5dd;--mk:#98a2b3;--bpbg:#f2f6fc;--hi:#b42318;--hibg:#fef3f2;--lo:#067647;--lobg:#ecfdf3}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#171a21;--fg:#e6e8ec;--mut:#98a2b3;--line:#2a2f3a;--acc:#5b9bff;%%FAMVARS_D%%--box:#3a4150;--mk:#5d6575;--bpbg:#1b2230;--hi:#ff8a80;--hibg:#3a1d1d;--lo:#6ce9a6;--lobg:#12291f}}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.55 system-ui,"Noto Sans TC","Microsoft JhengHei",sans-serif}
main{max-width:1600px;margin:auto;padding:24px 16px}h1{margin:0 0 4px;font-size:24px}h2{font-size:18px;margin:32px 0 6px}
h2+p{margin:0 0 10px}.mut{color:var(--mut)}a{color:var(--acc);text-decoration:none}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;overflow-x:auto}
.kpi{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-top:16px}
.kpi div{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}.kpi b{display:block;font-size:24px}
.find{margin-top:12px}.find li{margin:4px 0}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:5px 7px;border-bottom:1px solid var(--line);text-align:left}td{white-space:nowrap}
th{white-space:normal;line-height:1.3;vertical-align:bottom;min-width:2.5em;position:sticky;top:0;background:var(--card);font-weight:600}
#det td:first-child,#det th:first-child{position:sticky;left:0;z-index:1;background:var(--card)}#det th:first-child{z-index:3}
#det.h-dep .c-dep,#det.h-info .c-info{display:none}#det th{cursor:pointer}#det th:hover{color:var(--acc)}
.views{display:inline-flex;gap:4px;margin-left:12px}.views label{cursor:pointer;user-select:none;border:1px solid var(--line);border-radius:16px;padding:3px 10px;background:var(--card)}
.views input{margin:0 4px 0 0;vertical-align:-1px}.tblwrap{max-height:75vh;overflow:auto}
th::after{content:attr(data-s);color:var(--acc)}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.bp{background:var(--bpbg)}td.hi,.tag.hi{color:var(--hi);background:var(--hibg)}td.lo,.tag.lo{color:var(--lo);background:var(--lobg)}
th.grp{text-align:center;border-bottom:2px solid var(--line)}
svg text{fill:var(--mut);font-size:11px}svg text.lbl{fill:var(--fg)}svg .g{stroke:var(--line)}
svg .wh{stroke:var(--mut);stroke-width:2}svg .bx{fill:var(--box);stroke:var(--mut)}svg .md{stroke:var(--fg);stroke-width:3}
%%FAMCSS%%%%TREND_CSS%%svg .mk{fill:var(--mk);fill-opacity:.7}
.lg span{display:inline-block;width:10px;height:10px;border-radius:50%;margin:0 4px 0 12px;vertical-align:-1px}
.pans{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}
.pan{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px}
.pt{display:flex;gap:8px;align-items:baseline}.pt .tag{margin-left:auto;padding:1px 8px;border-radius:10px;font-weight:600;font-size:13px}
.filters{display:flex;flex-wrap:wrap;gap:8px;align-items:center}.sortctl{margin-left:auto}
.filters button{border:1px solid var(--line);background:var(--card);color:var(--fg);padding:4px 12px;border-radius:16px;cursor:pointer}
.filters button.on{background:var(--acc);color:#fff;border-color:var(--acc)}
.sortctl select{border:1px solid var(--line);background:var(--card);color:var(--fg);padding:4px 8px;border-radius:6px;margin-left:4px}
</style></head><body><main>
<h1>%%H1%%</h1>
<div class="mut">%%SUB%%｜擷取日 %%TODAY%%｜金額單位：萬元</div>

<div class="kpi">
<div><span class="mut">%%C%% 認證車在售</span><b>%%N_CERT%% 台</b><span class="mut">對比市場刊登 %%N_MKT%% 台</span></div>
<div><span class="mut">%%C%% vs 同里程市場行情（中位數）</span><b>%%MED_VC%%</b><span class="mut">同年份、里程最接近的市場車</span></div>
<div><span class="mut">%%C%% vs 同年份市場中位數（平均）</span><b>%%AVG_VM%%</b><span class="mut">未考慮里程差異</span></div>
<div><span class="mut">相較同里程行情</span><b>%%N_HI%% / %%N_MID%% / %%N_LO%%</b><span class="mut">貴 5% 以上 / ±5% 內 / 便宜 5% 以上</span></div>
</div>
<ul class="find">
<li>2023 年以後的新車：%%C%% 平均比同里程行情 <b>%%YOUNG%%</b>；2022 年以前的車：<b>%%OLD%%</b>。</li>
<li>%%C%% 明顯較貴（≥ +5%）的車款年份：%%EXP%%。</li>
<li>%%C%% 明顯較便宜（≤ −5%）的車款年份：%%CHP%%。</li>
%%EXTRA%%<li>%%C%% 價格通常含原廠認證保固、整備與保養紀錄，價差可視為這些保障的成本。</li>
</ul>

<h2>1. 依車款・年份比較</h2>
<p class="mut">「vs 同里程行情」為該組每台 %%C%% 車與里程最接近之市場車比較後的平均，比單純比中位數更公平。</p>
<div class="card"><table><thead>
<tr><th colspan="3"></th><th colspan="3" class="grp bp">%%C%% 認證車</th><th colspan="4" class="grp">8891 市場行情</th><th colspan="3" class="grp">%%C%% 價差</th></tr>
<tr><th>車款</th><th>年份</th><th>世代</th><th class="n bp">台數</th><th class="n bp">平均售價</th><th class="n bp">平均里程</th>
<th class="n">台數</th><th class="n">中位數</th><th class="n">P25~P75</th><th class="n">中位<br>里程</th>
<th class="n">vs 同年<br>中位數</th><th class="n">同里程<br>行情價差</th><th class="n">vs 同里程<br>行情</th></tr></thead><tbody>%%CMP_ROWS%%</tbody></table></div>

<h2>2. 價格分布</h2>
<p class="mut">灰線＝市場最低~最高，方框＝P25~P75（中間 50%），粗線＝中位數；圓點＝%%C%% 認證車。</p>
<div class="card"><div class="lg mut">%%LEGEND%%（滑鼠移到圖上看數字）</div>
%%DIST_SVG%%</div>

<h2>3. 價格 vs 里程</h2>
<p class="mut">每格為同車款同年份；灰點＝8891 市場車，彩色點＝%%C%% 認證車。彩色點落在灰點雲上方＝比同里程市場車貴。右上角為該組 vs 同里程行情。</p>
<div class="pans">%%PANELS%%</div>

<h2>4. 車輛明細</h2>
<div class="filters">%%BUTTONS%%
<span class="views mut">顯示欄位：<label><input type="checkbox" data-g="dep">折舊</label><label><input type="checkbox" data-g="info">%%INFO_LABEL%%</label></span>
<label class="sortctl">排序：<select id="sortKey"></select><select id="sortDir"><option value="asc">由低到高</option><option value="desc">由高到低</option></select></label></div>
<div class="card tblwrap" style="margin-top:10px"><table id="det"><thead><tr>
<th>車款</th><th>年份<br>(出廠)</th><th>%%KIT_LABEL%%</th><th>車色</th><th class="n">里程<br>(km)</th><th class="n bp">%%C%%<br>售價</th>
<th class="n">市場同年<br>中位數</th><th class="n">vs 同年<br>中位數</th><th class="n">同里程<br>行情</th><th class="n">同里程<br>行情價差</th><th class="n">vs 同里程<br>行情</th>
<th>領牌</th><th class="n">車齡<br>(年)</th><th class="n">新車<br>售價</th><th class="n">折價</th><th class="n">折價%</th><th class="n">一年<br>折價%</th><th class="n">年複合<br>折價%</th>
<th>世代</th><th>狀態</th><th>經銷商</th>
</tr></thead><tbody>%%DET%%</tbody></table></div>

<h2>5. 折價趨勢：一年、兩年、三年…</h2>
<p class="mut">車齡每增加一年，相對新車牌價累計折價多少。實線＝8891 市場車（各車齡折價% 中位數），空心菱形＝%%C%% 認證車。「當年新增」＝該車齡比前一年多折的百分點。</p>
<div class="card"><div class="lg mut">%%TREND_LEGEND%%（滑鼠移到點上看台數）</div>%%TREND_CHART%%</div>
<div class="card" style="margin-top:12px">%%TREND_TABLE%%</div>
<p class="mut" style="margin-top:6px">%%TREND_NOTE%% 市場車只有出廠年份，車齡＝假設年中出廠算到今天（四捨五入）；認證車車齡依領牌年月。部分車齡市場無資料或樣本很少，趨勢僅供參考。</p>

<h2>6. 買幾年的中古車最划算？</h2>
<p class="mut">假設買進後開 %%HOLD_YEARS%% 年再賣，這 %%HOLD_YEARS%% 年的折價佔買進價格的比例（越低越划算）。以 8891 市場各車齡折價% 中位數計算，只用每個車齡至少 %%MIN_N%% 台的資料；綠底為各車系最低。</p>
<div class="card">%%HOLD_TABLE%%</div>
<div class="card" style="margin-top:12px"><ul class="find" style="margin:0;padding-left:20px">%%BUY_ADVICE%%
<li class="mut">只計算折價，未含保養維修成本：車齡越大維修費越高，5 年以上的實際持有成本會比表上更高。新車原廠保固通常為 3 年，3 年左右的車搭配原廠認證保固特別實用。新車價用牌價、市場價用刊登價，部分車齡樣本僅 5~10 台，以未來 %%HOLD_YEARS%% 年會跟現在的折價曲線一樣為前提，數字當大方向參考。</li></ul></div>

<h2>7. 認證車折舊明細</h2>
<p class="mut">以 Yahoo汽車 各年式新車牌價計算 %%C%% 認證車的折價。</p>
<div class="card"><div class="lg mut">%%LEGEND%%　車齡 vs 折價%</div>%%DEP_SVG%%</div>
<div class="card" style="margin-top:12px"><table><thead><tr><th>車款</th><th>年份</th><th class="n">台數</th><th class="n">新車售價(平均)</th><th class="n">平均售價</th>
<th class="n">平均折價</th><th class="n">平均折價%</th><th class="n">平均一年折價%</th><th class="n">平均車齡(年)</th></tr></thead><tbody>%%DEP_ROWS%%</tbody></table></div>

<h2>計算方式與說明</h2>
<div class="card mut">
<p>・<b>市場行情</b>：%%MARKET_NOTE%% 依「年份產」對應認證車出廠年份分組。已排除：標題含「原廠認證」等字樣的刊登（%%N_CERTREL%% 筆，多為認證車在 8891 重複刊登，避免拿認證車和自己比）、「電洽」、以及低於該組中位數 40% 的誘餌價。8891 為刊登價（非成交價），實際成交通常再低一些，也可能有同車重複刊登。</p>
<p>・<b>vs 同年中位數</b> = %%C%% 售價 ÷ 同車款同年份市場中位數 − 1。<b>同里程行情</b> = 同車款同年份中、里程最接近的 7 台市場車售價中位數（滑鼠移到數字上看里程範圍）；<b>同里程行情價差</b> = %%C%% 售價 − 同里程行情（萬元，比較表為該組平均）；<b>vs 同里程行情</b> = %%C%% 售價 ÷ 同里程行情 − 1。正值＝%%C%% 較貴。紅底 ≥ +5%，綠底 ≤ −5%。</p>
<p>・<b>折價</b> = 新車售價 − %%C%% 售價；<b>折價%</b> = 折價 ÷ 新車售價。<b>車齡</b> 以領牌年月起算，顯示至小數一位；<b>一年折價%</b> = 折價% ÷ 整數車齡（四捨五入，最少 1 年）；<b>年複合折價%</b> = 1 − (售價/新車價)^(1/整數車齡)。</p>
<p>・<b>新車售價</b>：%%NEWPRICE_NOTE%%</p>
<p>・%%VARIANT_NOTE%%</p>
</div>
</main>
<script>
const KEY='%%KEY%%';
const tb=document.querySelector('#det tbody'),sk=document.getElementById('sortKey'),sd=document.getElementById('sortDir');
const ths=document.querySelectorAll('#det th');
ths.forEach((t,i)=>{const o=document.createElement('option');o.value=i;o.textContent=t.textContent;sk.appendChild(o)});
function sortBy(i,asc){const rs=[...tb.rows];rs.sort((a,b)=>{const x=a.cells[i],y=b.cells[i];const va=x.dataset.v??x.textContent,vb=y.dataset.v??y.textContent;
if(va===''&&vb!=='')return 1;if(vb===''&&va!=='')return -1;
const c=(isNaN(va)||isNaN(vb))?va.localeCompare(vb,'zh-Hant'):va-vb;return asc?c:-c});rs.forEach(r=>tb.appendChild(r));
ths.forEach((t,j)=>t.dataset.s=j==i?(asc?' ▲':' ▼'):'');sk.value=i;sd.value=asc?'asc':'desc';
try{localStorage.setItem(KEY+'Sort',JSON.stringify([i,asc]))}catch(e){}}
ths.forEach((th,i)=>th.onclick=()=>sortBy(i,sk.value==i?sd.value!=='asc':true));
sk.onchange=sd.onchange=()=>sortBy(+sk.value,sd.value==='asc');
let init=[10,false];try{const s=JSON.parse(localStorage.getItem(KEY+'Sort'));if(Array.isArray(s)&&s[0]<ths.length)init=s}catch(e){}
sortBy(init[0],init[1]);
const G={dep:[11,12,13,14,15,16,17],info:[18,19,20]},det=document.getElementById('det');
for(const g in G)for(const r of det.rows)G[g].forEach(i=>r.cells[i]&&r.cells[i].classList.add('c-'+g));
let vis={dep:true,info:true};try{Object.assign(vis,JSON.parse(localStorage.getItem(KEY+'Cols')||'{}'))}catch(e){}
document.querySelectorAll('.views input').forEach(cb=>{const g=cb.dataset.g;cb.checked=!!vis[g];det.classList.toggle('h-'+g,!cb.checked);
cb.onchange=()=>{vis[g]=cb.checked;det.classList.toggle('h-'+g,!cb.checked);try{localStorage.setItem(KEY+'Cols',JSON.stringify(vis))}catch(e){}}});
document.querySelectorAll('.filters button').forEach(b=>b.onclick=()=>{document.querySelectorAll('.filters button').forEach(x=>x.classList.remove('on'));b.classList.add('on');
[...tb.rows].forEach(r=>r.style.display=!b.dataset.f||r.dataset.fam===b.dataset.f?'':'none')});
</script></body></html>"""
