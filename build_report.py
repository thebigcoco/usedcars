"""BMW 原廠認證中古車 (BPS) vs 8891 二手車市場行情比較報告 — 318i / 320i Sedan.

Usage:  python build_report.py [bps_all.json] [8891_items.json]
Paths omitted -> fetches live data from https://bps.bmw.com.tw/api/search and
https://auto.8891.com.tw/bmw/3-series/{318i,320i} (8891 result cached to 8891_items.json).
"""
import json, sys, html, urllib.request, datetime, re, time

TODAY = datetime.date(2026, 11, 17)

# 新車建議售價 (萬元) — keyed by (model, generation, factory year, trim)
# (price, source note, is_estimate)
# 主要來源：Yahoo汽車 新車年式價格 https://autos.yahoo.com.tw/new-cars/model/bmw-3-series-sedan-{年式}
YAHOO = {
    2015: {"320i": 192, "320i M Sport": 209},
    2016: {"318i": 178, "320i": 199, "320i M Sport": 215},
    2017: {"318i": 181, "320i Sport Line": 202, "320i M Sport": 219},
    2018: {"320i Sport Line": 209},
    2020: {"318i Luxury Line": 203, "320i M Sport": 229},
    2021: {"318i Luxury Line": 206, "320i M Sport": 231},
    2022: {"318i Luxury Line": 211, "320i M Sport": 240},
    2023: {"318i Sport Line": 213, "320i M Sport": 243},
    2024: {"318i Sport Line": 216, "318i": 216, "320i M Sport": 246},
    2025: {"318i Sport Line": 219, "320i M Sport": 249},
    2026: {"318i Sport Line": 219, "318i M Sport": 227, "320i M Sport": 249},
}


def new_price(model, gen, year, kit):
    key = f"{model} {kit}" if kit else model
    # 例外：Yahoo 該年式無對應版本時的處理
    if model == "318i" and gen == "F30" and year == 2015:
        return (178, "Yahoo汽車 2016年式 318i 178萬（318i 自2016年式導入）", False)
    if model == "318i" and gen == "F30" and year == 2018:
        return (185, "2018年式 318i 建議售價185萬（Yahoo 只列豪華白金版促銷價159萬）", False)
    if model == "320i" and year == 2019:
        return (229, "G20 320i M Sport 2019/10 上市 229萬（Yahoo 2019年式未列）", False)
    if key == "318i M Sport" and year == 2025:
        return (227, "Yahoo汽車 2026年式 318i M Sport 227萬（2025下半年出廠，應為2026年式）", False)
    p = YAHOO.get(year, {}).get(key)
    if p is None and (p := YAHOO.get(year + 1, {}).get(key)) is not None:
        return (p, f"Yahoo汽車 {year+1}年式 {key} {p}萬（{year} 出廠之次年式）", False)
    if p is None:
        raise KeyError(f"no new price for {year} {key}")
    return (p, f"Yahoo汽車 {year}年式 {key} {p}萬", False)


def load(path=None):
    if path:
        return json.load(open(path, encoding="utf-8"))
    body = "--x\r\nContent-Disposition: form-data; name=\"pagesize\"\r\n\r\n1000\r\n--x\r\nContent-Disposition: form-data; name=\"page\"\r\n\r\n1\r\n--x--\r\n"
    req = urllib.request.Request("https://bps.bmw.com.tw/api/search", data=body.encode(),
                                 headers={"Content-Type": "multipart/form-data; boundary=x", "User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req))


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
PUSH = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)')


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


def load_8891(path=None):
    if path:
        return json.load(open(path, encoding="utf-8"))
    items = {}
    for model in ("318i", "320i"):
        for page in range(1, 20):
            req = urllib.request.Request(f"https://auto.8891.com.tw/bmw/3-series/{model}?page={page}", headers={"User-Agent": UA})
            found = parse_8891_page(urllib.request.urlopen(req).read().decode("utf-8"))
            if not found:
                break
            for o in found:
                items[o["itemId"]] = o
            time.sleep(1)
    items = list(items.values())
    json.dump(items, open("8891_items.json", "w", encoding="utf-8"), ensure_ascii=False)
    return items


def quart(v, q):
    k = (len(v) - 1) * q; lo = int(k); hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


BPS_RE = re.compile(r"原廠認證|BPS|Premium Selection", re.I)


def parse_market(items):
    """8891 listings -> {(318i/320i, 出廠年): [(price, km, is_bps_relisting, itemId)]}. Drops 電洽 and non-Sedan."""
    groups = {}
    for o in items:
        m = re.match(r"([\d.]+)萬", o["price"])
        if not m or "Sedan" not in o.get("kindEnName", ""):
            continue
        km = re.match(r"([\d.]+)(萬)?公里", o.get("mileage", ""))
        km = float(km.group(1)) * (10000 if km.group(2) else 1) if km else None
        bps = bool(BPS_RE.search((o.get("title") or "") + (o.get("subTitle") or "")))
        groups.setdefault((o["modelEnName"][:4], int(o["makeYear"][:4])), []).append((float(m.group(1)), km, bps, o["itemId"]))
    return groups


def market_stats(groups):
    """Price / mileage distribution of the non-BPS market per group. Drops bait prices (<40% of median)."""
    stats = {}
    for k, v in groups.items():
        allp = sorted(p for p, *_ in v)
        med = quart(allp, .5)
        v = [x for x in v if x[0] >= med * 0.4]
        mk = [x for x in v if not x[2]]
        if not mk:
            continue
        ps = sorted(x[0] for x in mk)
        kms = sorted(x[1] for x in mk if x[1] is not None)
        stats[k] = dict(n=len(ps), n_bps=sum(x[2] for x in v), pts=[(x[0], x[1]) for x in mk if x[1] is not None],
                        bps_pts=[(x[0], x[1]) for x in v if x[2] and x[1] is not None],
                        min=ps[0], p25=quart(ps, .25), med=quart(ps, .5), p75=quart(ps, .75), max=ps[-1],
                        km_med=quart(kms, .5) if kms else None,
                        km_p25=quart(kms, .25) if kms else None, km_p75=quart(kms, .75) if kms else None)
    return stats


def same_km_comp(s, km, k=7):
    """Median price of the k market listings (same model+year) closest in mileage."""
    if not s or len(s["pts"]) < 3:
        return None
    near = sorted(s["pts"], key=lambda t: abs(t[1] - km))[:k]
    ps = sorted(p for p, _ in near); kms = [m for _, m in near]
    return dict(price=quart(ps, .5), n=len(near), km_lo=min(kms), km_hi=max(kms))


def build(d, mkt):
    rows = []
    for x in d["data"]:
        if x["model_name"] not in ("318i", "320i") or not x["model_type"].startswith("Sedan"):
            continue
        kit = x["kit_name"] or "—"
        np, note, est = new_price(x["model_name"], x["source_no"], x["fac_year"], x["kit_name"])
        price = float(x["price"])
        km = int(x["mileage"])
        lic = datetime.date(x["lic_year"], x["lic_month"], 1)
        age = round((TODAY - lic).days / 365.25, 1)  # 顯示用車齡：小數點後一位
        age_int = max(round(age), 1)  # 計算用車齡：四捨五入取整數，最少 1 年
        dep = np - price
        dep_pct = dep / np * 100
        s = mkt.get((x["model_name"], x["fac_year"]))
        c = same_km_comp(s, km)
        rows.append(dict(id=x["id"], model=x["model_name"], gen=x["source_no"], kit=kit,
                         color=(x["color_name"] or "").strip(), color_cat=x["color_category_name"] or "—",
                         fac=f'{x["fac_year"]}/{x["fac_month"]:02d}', year=x["fac_year"],
                         lic=f'{x["lic_year"]}/{x["lic_month"]:02d}', age=age, age_int=age_int,
                         km=km, price=price, new=np, est=est, note=note,
                         dep=dep, dep_pct=dep_pct, yr_pct=dep_pct / age_int,
                         cagr=(1 - (price / np) ** (1 / age_int)) * 100,
                         status=x["status_name"], dealer=x["show_name"], store=x["store"],
                         mkt_med=s["med"] if s else None,
                         vs_mkt=(price / s["med"] - 1) * 100 if s else None,
                         comp=c, comp_price=c["price"] if c else None,
                         vs_comp=(price / c["price"] - 1) * 100 if c else None,
                         diff_comp=price - c["price"] if c else None))
    rows.sort(key=lambda r: (r["model"], r["year"], r["price"]))
    return rows


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


def render(rows, mkt, n_items):
    groups = {}
    for r in rows:
        groups.setdefault((r["model"], r["year"]), []).append(r)
    keys = sorted(groups)
    n_mkt = sum(mkt[k]["n"] for k in keys if k in mkt)
    n_bps_rel = sum(s["n_bps"] for s in mkt.values())

    # ---------- comparison table ----------
    cmp_rows = ""
    for k in keys:
        g = groups[k]; s = mkt.get(k)
        bp = avg(r["price"] for r in g); bk = avg(r["km"] for r in g)
        vm = (bp / s["med"] - 1) * 100 if s else None
        vc = avg(r["vs_comp"] for r in g); dc = avg(r["diff_comp"] for r in g)
        cmp_rows += (f'<tr><td>{k[0]}</td><td>{k[1]}</td><td>{g[0]["gen"]}</td>'
                     f'<td class="n bp">{len(g)}</td><td class="n bp">{f(bp)}</td><td class="n bp">{kmw(bk)}</td>'
                     f'<td class="n">{s["n"] if s else 0}</td><td class="n">{f(s["med"]) if s else "—"}</td>'
                     f'<td class="n">{(f(s["p25"]) + " ~ " + f(s["p75"])) if s else "—"}</td><td class="n">{kmw(s["km_med"]) if s else "—"}</td>'
                     f'<td class="n {tone(vm)}">{pct(vm)}</td><td class="n {tone(vc)}">{sgn(dc)}</td><td class="n {tone(vc)}"><b>{pct(vc)}</b></td></tr>')

    # ---------- distribution strip chart ----------
    RH, LW, CW = 34, 92, 620
    xmax = max(max(s["max"] for k, s in mkt.items() if k in groups), max(r["price"] for r in rows)) * 1.05
    X = lambda v: LW + v / xmax * CW
    dist = ""
    for i, k in enumerate(keys):
        cy = 24 + i * RH + RH / 2
        dist += f'<text x="{LW-10}" y="{cy+4}" text-anchor="end" class="lbl">{k[0]} {k[1]}</text>'
        s = mkt.get(k)
        if s:
            dist += (f'<g><title>市場 {k[0]} {k[1]}年：{s["n"]} 台｜最低 {s["min"]}｜P25 {s["p25"]:.1f}｜中位數 {s["med"]:.1f}｜P75 {s["p75"]:.1f}｜最高 {s["max"]}｜中位里程 {kmw(s["km_med"])}公里</title>'
                     f'<line x1="{X(s["min"]):.1f}" x2="{X(s["max"]):.1f}" y1="{cy}" y2="{cy}" class="wh"/>'
                     f'<rect x="{X(s["p25"]):.1f}" y="{cy-8}" width="{max(X(s["p75"])-X(s["p25"]),2):.1f}" height="16" rx="3" class="bx"/>'
                     f'<line x1="{X(s["med"]):.1f}" x2="{X(s["med"]):.1f}" y1="{cy-10}" y2="{cy+10}" class="md"/></g>'
                     f'<text x="{X(s["max"])+6:.1f}" y="{cy+4}">n={s["n"]}・{kmw(s["km_med"])}km</text>')
        for r in groups[k]:
            dist += (f'<circle cx="{X(r["price"]):.1f}" cy="{cy}" r="4.5" class="{"d318" if r["model"]=="318i" else "d320"}">'
                     f'<title>BPS {r["model"]} {r["fac"]} {r["kit"]}｜{r["price"]}萬｜{r["km"]:,} km｜vs 同年中位數 {pct(r["vs_mkt"])}｜vs 同里程行情 {pct(r["vs_comp"])}</title></circle>')
    DH = 24 + len(keys) * RH + 24
    grid = ""
    for v in range(0, int(xmax) + 1, 25):
        grid += f'<line x1="{X(v):.1f}" x2="{X(v):.1f}" y1="16" y2="{DH-20}" class="g"/><text x="{X(v):.1f}" y="{DH-6}" text-anchor="middle">{v}萬</text>'
    dist_svg = f'<svg viewBox="0 0 {LW+CW+110} {DH}" width="100%" style="min-width:560px">{grid}{dist}</svg>'

    # ---------- small multiples: price vs mileage ----------
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
            body += f'<text x="{px(v):.1f}" y="{PH-8}" text-anchor="middle">{v/10000:.0f}萬km</text>'
        if s:
            for p, km in s["pts"]:
                body += f'<circle cx="{px(km):.1f}" cy="{py(p):.1f}" r="3" class="mk"><title>市場 {p}萬｜{km:,.0f} km</title></circle>'
        for r in g:
            body += (f'<circle cx="{px(r["km"]):.1f}" cy="{py(r["price"]):.1f}" r="4.5" class="{"d318" if r["model"]=="318i" else "d320"}">'
                     f'<title>BPS {r["fac"]} {r["kit"]}｜{r["price"]}萬｜{r["km"]:,} km｜同里程行情 {f(r["comp_price"])}萬（{pct(r["vs_comp"])}）</title></circle>')
        vc = avg(r["vs_comp"] for r in g)
        pan += (f'<div class="pan"><div class="pt"><b>{k[0]} {k[1]}</b><span class="mut">BPS {len(g)}・市場 {s["n"] if s else 0}</span>'
                f'<span class="tag {tone(vc)}">{pct(vc)}</span></div><svg viewBox="0 0 {PW} {PH}" width="100%">{body}</svg></div>')

    # ---------- depreciation scatter ----------
    W, H, P = 720, 280, 40
    maxage = max(r["age"] for r in rows) * 1.05
    dep_svg = ""
    for p in range(0, 101, 20):
        y = H - P - p / 100 * (H - 2 * P)
        dep_svg += f'<line x1="{P}" x2="{W-P}" y1="{y}" y2="{y}" class="g"/><text x="{P-6}" y="{y+4}" text-anchor="end">{p}%</text>'
    for a in range(0, int(maxage) + 1, 2):
        dep_svg += f'<text x="{P + a / maxage * (W - 2 * P):.1f}" y="{H-P+16}" text-anchor="middle">{a}年</text>'
    for r in rows:
        dep_svg += (f'<circle cx="{P + r["age"] / maxage * (W - 2 * P):.1f}" cy="{H - P - r["dep_pct"] / 100 * (H - 2 * P):.1f}" r="5" class="{"d318" if r["model"]=="318i" else "d320"}">'
                    f'<title>{r["model"]} {r["fac"]} {r["kit"]}｜售價 {r["price"]}萬｜新車 {r["new"]}萬｜折價 {r["dep_pct"]:.1f}%｜車齡 {r["age"]:.1f}年</title></circle>')
    dep_rows = ""
    for k in keys:
        g = groups[k]
        dep_rows += (f'<tr><td>{k[0]}</td><td>{k[1]}</td><td class="n">{len(g)}</td><td class="n">{f(avg(r["new"] for r in g),0)}</td>'
                     f'<td class="n">{f(avg(r["price"] for r in g))}</td><td class="n">{f(avg(r["dep"] for r in g))}</td>'
                     f'<td class="n">{f(avg(r["dep_pct"] for r in g))}%</td><td class="n">{f(avg(r["yr_pct"] for r in g))}%</td>'
                     f'<td class="n">{f(avg(r["age"] for r in g))}</td></tr>')

    # ---------- detail table ----------
    det = ""
    for r in rows:
        c = r["comp"]
        ctitle = f'取市場同年份里程最接近的 {c["n"]} 台（{kmw(c["km_lo"])}~{kmw(c["km_hi"])}公里）之中位數' if c else "市場樣本不足"
        dv = lambda v: "" if v is None else v
        det += (f'<tr><td><a href="https://bps.bmw.com.tw/info/{r["id"]}" target="_blank">{r["model"]}</a></td>'
                f'<td data-v="{r["year"]}">{r["fac"]}</td><td>{esc(r["kit"])}</td><td>{esc(r["color_cat"])}</td>'
                f'<td class="n" data-v="{r["km"]}">{r["km"]:,}</td>'
                f'<td class="n bp" data-v="{r["price"]}"><b>{f(r["price"])}</b></td>'
                f'<td class="n" data-v="{dv(r["mkt_med"])}">{f(r["mkt_med"])}</td>'
                f'<td class="n {tone(r["vs_mkt"])}" data-v="{dv(r["vs_mkt"])}">{pct(r["vs_mkt"])}</td>'
                f'<td class="n" data-v="{dv(r["comp_price"])}" title="{esc(ctitle)}">{f(r["comp_price"])}</td>'
                f'<td class="n {tone(r["vs_comp"])}" data-v="{dv(r["diff_comp"])}">{sgn(r["diff_comp"])}</td>'
                f'<td class="n {tone(r["vs_comp"])}" data-v="{dv(r["vs_comp"])}"><b>{pct(r["vs_comp"])}</b></td>'
                f'<td>{r["lic"]}</td><td class="n" data-v="{r["age"]}">{r["age"]:.1f}</td>'
                f'<td class="n" data-v="{r["new"]}" title="{esc(r["note"])}">{r["new"]}</td>'
                f'<td class="n" data-v="{r["dep"]}">{f(r["dep"])}</td>'
                f'<td class="n" data-v="{r["dep_pct"]}">{f(r["dep_pct"])}%</td>'
                f'<td class="n" data-v="{r["yr_pct"]}">{f(r["yr_pct"])}%</td>'
                f'<td class="n" data-v="{r["cagr"]}">{f(r["cagr"])}%</td>'
                f'<td>{esc(r["gen"])}</td><td>{esc(r["status"])}</td><td>{esc(r["dealer"])}</td></tr>')

    # ---------- KPIs & findings ----------
    vcs = [r["vs_comp"] for r in rows if r["vs_comp"] is not None]
    vms = [r["vs_mkt"] for r in rows if r["vs_mkt"] is not None]
    med_vc = quart(sorted(vcs), .5)
    n_hi = sum(v >= 5 for v in vcs); n_lo = sum(v <= -5 for v in vcs); n_mid = len(vcs) - n_hi - n_lo
    grp_vc = sorted(((avg(r["vs_comp"] for r in groups[k]), k) for k in keys if avg(r["vs_comp"] for r in groups[k]) is not None), reverse=True)
    exp = "、".join(f'{k[0]} {k[1]}（{pct(v)}）' for v, k in grp_vc if v >= 5) or "無"
    chp = "、".join(f'{k[0]} {k[1]}（{pct(v)}）' for v, k in grp_vc if v <= -5) or "無"
    young = [r["vs_comp"] for r in rows if r["vs_comp"] is not None and r["year"] >= 2023]
    old = [r["vs_comp"] for r in rows if r["vs_comp"] is not None and r["year"] < 2023]

    rep = {
        "TODAY": str(TODAY), "N_BPS": str(len(rows)), "N_MKT": str(n_mkt), "N_ITEMS": str(n_items), "N_BPSREL": str(n_bps_rel),
        "MED_VC": pct(med_vc), "AVG_VM": pct(avg(vms)), "N_HI": str(n_hi), "N_MID": str(n_mid), "N_LO": str(n_lo),
        "YOUNG": pct(avg(young)), "OLD": pct(avg(old)), "EXP": exp, "CHP": chp,
        "CMP_ROWS": cmp_rows, "DIST_SVG": dist_svg, "PANELS": pan, "DEP_SVG": f'<svg viewBox="0 0 {W} {H}" width="100%">{dep_svg}</svg>',
        "DEP_ROWS": dep_rows, "DET": det,
    }
    out = TEMPLATE
    for k, v in rep.items():
        out = out.replace("%%" + k + "%%", v)
    return out


TEMPLATE = r"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>BMW 認證中古車 vs 市場行情</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--fg:#1a1d23;--mut:#667085;--line:#e4e7ec;--acc:#1c69d4;--c318:#1c69d4;--c320:#e4572e;--box:#d0d5dd;--mk:#98a2b3;--bpbg:#f2f6fc;--hi:#b42318;--hibg:#fef3f2;--lo:#067647;--lobg:#ecfdf3}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#171a21;--fg:#e6e8ec;--mut:#98a2b3;--line:#2a2f3a;--acc:#5b9bff;--c318:#5b9bff;--c320:#ff7a52;--box:#3a4150;--mk:#5d6575;--bpbg:#1b2230;--hi:#ff8a80;--hibg:#3a1d1d;--lo:#6ce9a6;--lobg:#12291f}}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.55 system-ui,"Noto Sans TC","Microsoft JhengHei",sans-serif}
main{max-width:1600px;margin:auto;padding:24px 16px}h1{margin:0 0 4px;font-size:24px}h2{font-size:18px;margin:32px 0 6px}
h2+p{margin:0 0 10px}.mut{color:var(--mut)}a{color:var(--acc);text-decoration:none}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;overflow-x:auto}
.kpi{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-top:16px}
.kpi div{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}.kpi b{display:block;font-size:24px}
.find{margin-top:12px}.find li{margin:4px 0}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:5px 7px;border-bottom:1px solid var(--line);text-align:left}td{white-space:nowrap}th{white-space:normal;line-height:1.3;vertical-align:bottom;min-width:2.5em}#det td:first-child,#det th:first-child{position:sticky;left:0;z-index:1;background:var(--card)}#det th:first-child{z-index:3}#det.h-dep .c-dep,#det.h-info .c-info{display:none}.views{display:inline-flex;gap:4px;margin-left:12px}.views label{cursor:pointer;user-select:none;border:1px solid var(--line);border-radius:16px;padding:3px 10px;background:var(--card)}.views input{margin:0 4px 0 0;vertical-align:-1px}.tblwrap{max-height:75vh;overflow:auto}
th{position:sticky;top:0;background:var(--card);font-weight:600}#det th{cursor:pointer}#det th:hover{color:var(--acc)}
th::after{content:attr(data-s);color:var(--acc)}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.bp{background:var(--bpbg)}td.hi,.tag.hi{color:var(--hi);background:var(--hibg)}td.lo,.tag.lo{color:var(--lo);background:var(--lobg)}
th.grp{text-align:center;border-bottom:2px solid var(--line)}
svg text{fill:var(--mut);font-size:11px}svg text.lbl{fill:var(--fg)}svg .g{stroke:var(--line)}
svg .wh{stroke:var(--mut);stroke-width:2}svg .bx{fill:var(--box);stroke:var(--mut)}svg .md{stroke:var(--fg);stroke-width:3}
svg .d318{fill:var(--c318);stroke:var(--card)}svg .d320{fill:var(--c320);stroke:var(--card)}svg .mk{fill:var(--mk);fill-opacity:.7}
.lg span{display:inline-block;width:10px;height:10px;border-radius:50%;margin:0 4px 0 12px;vertical-align:-1px}
.pans{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}
.pan{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px}
.pt{display:flex;gap:8px;align-items:baseline}.pt .tag{margin-left:auto;padding:1px 8px;border-radius:10px;font-weight:600;font-size:13px}
.filters{display:flex;flex-wrap:wrap;gap:8px;align-items:center}.sortctl{margin-left:auto}
.filters button{border:1px solid var(--line);background:var(--card);color:var(--fg);padding:4px 12px;border-radius:16px;cursor:pointer}
.filters button.on{background:var(--acc);color:#fff;border-color:var(--acc)}
.sortctl select{border:1px solid var(--line);background:var(--card);color:var(--fg);padding:4px 8px;border-radius:6px;margin-left:4px}
</style></head><body><main>
<h1>BMW 原廠認證中古車 vs 二手車市場行情</h1>
<div class="mut">318i / 320i Sedan｜BPS：bps.bmw.com.tw｜市場：8891中古車｜擷取日 %%TODAY%%｜金額單位：萬元</div>

<div class="kpi">
<div><span class="mut">BPS 認證車在售</span><b>%%N_BPS%% 台</b><span class="mut">對比市場刊登 %%N_MKT%% 台</span></div>
<div><span class="mut">BPS vs 同里程市場行情（中位數）</span><b>%%MED_VC%%</b><span class="mut">同年份、里程最接近的市場車</span></div>
<div><span class="mut">BPS vs 同年份市場中位數（平均）</span><b>%%AVG_VM%%</b><span class="mut">未考慮里程差異</span></div>
<div><span class="mut">相較同里程行情</span><b>%%N_HI%% / %%N_MID%% / %%N_LO%%</b><span class="mut">貴 5% 以上 / ±5% 內 / 便宜 5% 以上</span></div>
</div>
<ul class="find">
<li>2023 年以後的新車：BPS 平均比同里程行情 <b>%%YOUNG%%</b>；2022 年以前的車：<b>%%OLD%%</b>。</li>
<li>BPS 明顯較貴（≥ +5%）的車款年份：%%EXP%%。</li>
<li>BPS 明顯較便宜（≤ −5%）的車款年份：%%CHP%%。</li>
<li>BPS 價格通常含原廠認證保固、整備與保養紀錄，價差可視為這些保障的成本。</li>
</ul>

<h2>1. 依車款・年份比較</h2>
<p class="mut">「vs 同里程行情」為該組每台 BPS 車與里程最接近之市場車比較後的平均，比單純比中位數更公平。</p>
<div class="card"><table><thead>
<tr><th colspan="3"></th><th colspan="3" class="grp bp">BPS 認證車</th><th colspan="4" class="grp">8891 市場行情</th><th colspan="3" class="grp">BPS 價差</th></tr>
<tr><th>車款</th><th>年份</th><th>世代</th><th class="n bp">台數</th><th class="n bp">平均售價</th><th class="n bp">平均里程</th>
<th class="n">台數</th><th class="n">中位數</th><th class="n">P25~P75</th><th class="n">中位<br>里程</th>
<th class="n">vs 同年<br>中位數</th><th class="n">同里程<br>行情價差</th><th class="n">vs 同里程<br>行情</th></tr></thead><tbody>%%CMP_ROWS%%</tbody></table></div>

<h2>2. 價格分布</h2>
<p class="mut">灰線＝市場最低~最高，方框＝P25~P75（中間 50%），粗線＝中位數；圓點＝BPS 認證車。</p>
<div class="card"><div class="lg mut"><span style="background:var(--c318)"></span>BPS 318i<span style="background:var(--c320)"></span>BPS 320i（滑鼠移到圖上看數字）</div>
%%DIST_SVG%%</div>

<h2>3. 價格 vs 里程</h2>
<p class="mut">每格為同車款同年份；灰點＝8891 市場車，彩色點＝BPS 認證車。BPS 點落在灰點雲上方＝比同里程市場車貴。右上角為該組 vs 同里程行情。</p>
<div class="pans">%%PANELS%%</div>

<h2>4. 車輛明細</h2>
<div class="filters"><button class="on" data-f="">全部</button><button data-f="318i">318i</button><button data-f="320i">320i</button>
<span class="views mut">顯示欄位：<label><input type="checkbox" data-g="dep">折舊</label><label><input type="checkbox" data-g="info">世代・狀態・經銷商</label></span>
<label class="sortctl">排序：<select id="sortKey"></select><select id="sortDir"><option value="asc">由低到高</option><option value="desc">由高到低</option></select></label></div>
<div class="card tblwrap" style="margin-top:10px"><table id="det"><thead><tr>
<th>車款</th><th>年份<br>(出廠)</th><th>版本</th><th>車色</th><th class="n">里程<br>(km)</th><th class="n bp">BPS<br>售價</th>
<th class="n">市場同年<br>中位數</th><th class="n">vs 同年<br>中位數</th><th class="n">同里程<br>行情</th><th class="n">同里程<br>行情價差</th><th class="n">vs 同里程<br>行情</th>
<th>領牌</th><th class="n">車齡<br>(年)</th><th class="n">新車<br>售價</th><th class="n">折價</th><th class="n">折價%</th><th class="n">一年<br>折價%</th><th class="n">年複合<br>折價%</th>
<th>世代</th><th>狀態</th><th>經銷商</th>
</tr></thead><tbody>%%DET%%</tbody></table></div>

<h2>5. 折舊參考</h2>
<p class="mut">以 Yahoo汽車 各年式新車牌價計算 BPS 認證車的折價。</p>
<div class="card"><div class="lg mut"><span style="background:var(--c318)"></span>318i<span style="background:var(--c320)"></span>320i　車齡 vs 折價%</div>%%DEP_SVG%%</div>
<div class="card" style="margin-top:12px"><table><thead><tr><th>車款</th><th>年份</th><th class="n">台數</th><th class="n">新車售價(平均)</th><th class="n">平均售價</th>
<th class="n">平均折價</th><th class="n">平均折價%</th><th class="n">平均一年折價%</th><th class="n">平均車齡(年)</th></tr></thead><tbody>%%DEP_ROWS%%</tbody></table></div>

<h2>計算方式與說明</h2>
<div class="card mut">
<p>・<b>市場行情</b>：擷取 <a href="https://auto.8891.com.tw/bmw/3-series/318i" target="_blank">8891中古車</a> 318i、320i 全部在售刊登（%%N_ITEMS%% 筆），依「年份產」對應 BPS 出廠年份分組。已排除：標題含「原廠認證 / BPS」的刊登（%%N_BPSREL%% 筆，多為 BPS 車重複刊登，避免拿 BPS 和自己比）、「電洽」、以及低於該組中位數 40% 的誘餌價。8891 為刊登價（非成交價），實際成交通常再低一些，也可能有同車重複刊登。</p>
<p>・<b>vs 同年中位數</b> = BPS 售價 ÷ 同車款同年份市場中位數 − 1。<b>同里程行情</b> = 同車款同年份中、里程最接近的 7 台市場車售價中位數（滑鼠移到數字上看里程範圍）；<b>同里程行情價差</b> = BPS 售價 − 同里程行情（萬元，比較表為該組平均）；<b>vs 同里程行情</b> = BPS 售價 ÷ 同里程行情 − 1。正值＝BPS 較貴。紅底 ≥ +5%，綠底 ≤ −5%。</p>
<p>・<b>折價</b> = 新車售價 − BPS 售價；<b>折價%</b> = 折價 ÷ 新車售價。<b>車齡</b> 以領牌年月起算，顯示至小數一位；<b>一年折價%</b> = 折價% ÷ 整數車齡（四捨五入，最少 1 年）；<b>年複合折價%</b> = 1 − (售價/新車價)^(1/整數車齡)。</p>
<p>・<b>新車售價</b> 取自 <a href="https://autos.yahoo.com.tw/new-cars/make/bmw" target="_blank">Yahoo汽車</a> 各年式牌價，以出廠年對應年式、依版本配對（滑鼠移到數字看依據）；少數缺漏改用相鄰年式或上市新聞價格，約 ±3 萬誤差。</p>
<p>・版本差異（Luxury / Sport / M Sport）、選配與車況未納入行情比較，同組內配備較高的車價格偏高屬正常。</p>
</div>
</main>
<script>
const tb=document.querySelector('#det tbody'),sk=document.getElementById('sortKey'),sd=document.getElementById('sortDir');
const ths=document.querySelectorAll('#det th');
ths.forEach((t,i)=>{const o=document.createElement('option');o.value=i;o.textContent=t.textContent;sk.appendChild(o)});
function sortBy(i,asc){const rs=[...tb.rows];rs.sort((a,b)=>{const x=a.cells[i],y=b.cells[i];const va=x.dataset.v??x.textContent,vb=y.dataset.v??y.textContent;
if(va===''&&vb!=='')return 1;if(vb===''&&va!=='')return -1;
const c=(isNaN(va)||isNaN(vb))?va.localeCompare(vb,'zh-Hant'):va-vb;return asc?c:-c});rs.forEach(r=>tb.appendChild(r));
ths.forEach((t,j)=>t.dataset.s=j==i?(asc?' ▲':' ▼'):'');sk.value=i;sd.value=asc?'asc':'desc';
try{localStorage.setItem('bmwSort4',JSON.stringify([i,asc]))}catch(e){}}
ths.forEach((th,i)=>th.onclick=()=>sortBy(i,sk.value==i?sd.value!=='asc':true));
sk.onchange=sd.onchange=()=>sortBy(+sk.value,sd.value==='asc');
let init=[10,false];try{const s=JSON.parse(localStorage.getItem('bmwSort4'));if(Array.isArray(s)&&s[0]<ths.length)init=s}catch(e){}
sortBy(init[0],init[1]);
const G={dep:[11,12,13,14,15,16,17],info:[18,19,20]},det=document.getElementById('det');
for(const g in G)for(const r of det.rows)G[g].forEach(i=>r.cells[i]&&r.cells[i].classList.add('c-'+g));
let vis={dep:true,info:true};try{Object.assign(vis,JSON.parse(localStorage.getItem('bmwCols2')||'{}'))}catch(e){}
document.querySelectorAll('.views input').forEach(cb=>{const g=cb.dataset.g;cb.checked=!!vis[g];det.classList.toggle('h-'+g,!cb.checked);
cb.onchange=()=>{vis[g]=cb.checked;det.classList.toggle('h-'+g,!cb.checked);try{localStorage.setItem('bmwCols2',JSON.stringify(vis))}catch(e){}}});
document.querySelectorAll('.filters button').forEach(b=>b.onclick=()=>{document.querySelectorAll('.filters button').forEach(x=>x.classList.remove('on'));b.classList.add('on');
[...tb.rows].forEach(r=>r.style.display=!b.dataset.f||r.cells[0].textContent===b.dataset.f?'':'none')});
</script></body></html>"""


if __name__ == "__main__":
    data = load(sys.argv[1] if len(sys.argv) > 1 else None)
    items = load_8891(sys.argv[2] if len(sys.argv) > 2 else None)
    mkt = market_stats(parse_market(items))
    rows = build(data, mkt)
    open("bmw_318i_320i_report.html", "w", encoding="utf-8").write(render(rows, mkt, len(items)))
    json.dump([{k: v for k, v in r.items() if k != "comp"} | {"comp": r["comp"]} for r in rows],
              open("bmw_318i_320i_data.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(len(rows), "rows written")
