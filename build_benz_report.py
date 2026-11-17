"""Mercedes-Benz 原廠精選中古車 (Mercedes-Benz Select) vs 8891 二手車市場行情比較報告 — A-Class (掀背) / C-Class Sedan.

Usage:  python build_benz_report.py [select_cars.json] [8891_benz_items.json]
Paths omitted -> fetches live data from https://www.mercedes-benz-select.com.tw/buy-car/list.aspx (+ each car's
detail page, cached to select_cars.json) and https://auto.8891.com.tw/mercedes-benz/{a,c} (cached to 8891_benz_items.json).
A-Class Sedan、C-Class Estate / Coupé / Cabriolet 與 CLA 不納入。
"""
import datetime, html, json, re, sys, time, urllib.request
from usedcar_report import load_8891, make_report

SITE = "https://www.mercedes-benz-select.com.tw/buy-car/"
UA = "Mozilla/5.0"

# 新車牌價 (萬元)，來源：Yahoo汽車 https://autos.yahoo.com.tw/new-cars/model/m-benz-{a-class|c-class-sedan}-{年式}
YAHOO = {
    "A180":     {2019: 160, 2020: 164, 2021: 169, 2022: 172, 2023: 172, 2024: 183, 2025: 184, 2026: 165},
    "AMG A35":  {2020: 250, 2021: 257, 2022: 260, 2023: 260, 2024: 267, 2025: 243, 2026: 243},
    "AMG A45":  {2020: 326, 2021: 331, 2022: 334, 2023: 334, 2024: 348, 2025: 349, 2026: 349},
    "C180":     {2019: 201, 2020: 203, 2021: 206, 2022: 213, 2023: 217, 2024: 221, 2025: 224, 2026: 225},
    "C200":     {2019: 227, 2020: 229, 2021: 233, 2022: 243, 2023: 247, 2024: 257, 2025: 260, 2026: 261},
    "C300":     {2019: 270, 2020: 270, 2021: 276, 2022: 292, 2023: 296, 2024: 301, 2025: 304, 2026: 305},
    "AMG C43":  {2019: 358, 2020: 358, 2021: 366, 2023: 382, 2024: 386, 2025: 389, 2026: 391},
    "AMG C63":  {2024: 604, 2025: 607},
}
TRIM_NOTE = {
    "A180": {2020: "運動版", 2021: "運動版", 2022: "運動版", 2023: "運動版", 2025: "進化版", 2026: "摘星版"},
    "AMG A35": {2025: "摘星版", 2026: "摘星版"}, "AMG C63": {2024: "S E Performance", 2025: "S E Performance"},
}
MODEL_ORDER = ["A180", "AMG A35", "AMG A45", "C180", "C200", "C300", "AMG C43", "AMG C63"]


def market_new(group, year):
    """8891 市場車只知出廠年：用同年式牌價（無則相鄰年式）估算折價（折價趨勢用）。"""
    tbl = YAHOO.get(group, {})
    for y in (year, year + 1, year - 1):
        if y in tbl:
            return tbl[y]
    return None


def model_year(year, month):
    """賓士第 4 季（10~12 月）出廠車多為次年式。"""
    return year + 1 if month >= 10 else year


def new_price(model, year, month):
    my = model_year(year, month)
    tbl = YAHOO[model]
    for y in (my, my - 1, my + 1):
        if y in tbl:
            trim = TRIM_NOTE.get(model, {}).get(y, "")
            why = f"Yahoo汽車 {y}年式 {model}{trim} {tbl[y]}萬"
            if y != my:
                why += f"（{my}年式未列，用相鄰年式）"
            elif my != year:
                why += f"（{year}/{month:02d} 出廠，視為 {my} 年式）"
            return tbl[y], why
    raise KeyError(f"no new price for {model} {year}")


def model_of_title(title):
    """Mercedes-Benz Select title -> comparison group, e.g. 'Mercedes-AMG C 43 4M' -> 'AMG C43'."""
    m = re.search(r"\b([AC]) (\d{2,3})", title)
    if not m:
        return None
    name = f"{m.group(1)}{m.group(2)}"
    return f"AMG {name}" if len(m.group(2)) == 2 else name


def group_of(o):
    """8891 listing -> comparison group. Only 'A-Class' (掀背) and 'C-Class Sedan'."""
    kind = o.get("kindEnName", "")
    if kind not in ("A-Class", "C-Class Sedan"):
        return None
    m = re.search(r"(\d{2,3})", re.sub(r"4\s*matic\+?", "", o["modelEnName"], flags=re.I))
    if not m:
        return None
    n = m.group(1); letter = kind[0]
    g = f"AMG {letter}{n}" if len(n) == 2 else f"{letter}{n}"
    return g if g in YAHOO else None


def fetch_select():
    req = urllib.request.Request(SITE + "list.aspx", data=b"", method="POST",
                                 headers={"X-Requested-With": "XMLHttpRequest", "User-Agent": UA})
    cars = json.load(urllib.request.urlopen(req, timeout=30))
    out = []
    for x in cars:
        a = x["array"]
        model = model_of_title(x["title"])
        # series 2/8 = A-Class 掀背 / AMG A；5/10 = C-Class / AMG C（4 = A-Class Sedan，不納入）
        if a.get("bodyType") != "Car" or a.get("series") not in ("2", "8", "5", "10") or "Estate" in x["title"] or model not in YAHOO:
            continue
        t = urllib.request.urlopen(urllib.request.Request(SITE + f"detail.aspx?id={x['id']}", headers={"User-Agent": UA}), timeout=30).read().decode("utf-8")
        t = re.sub(r"<script.*?</script>|<style.*?</style>", "", t, flags=re.S)
        txt = re.sub(r"(\s*\|\s*)+", " | ", re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " | ", t))))
        g = lambda k: (re.search(k + r" \| ([^|]+) \|", txt) or [None, None])[1]
        x["detail"] = {k: (g(k) or "").strip() for k in ("出廠年份", "掛牌年份", "車色", "引擎動能型式", "排氣量")}
        out.append(x)
        time.sleep(0.5)
    json.dump(out, open("select_cars.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return out


def rows_from_select(cars):
    rows = []
    for x in cars:
        model = model_of_title(x["title"]); d = x["detail"]
        fy, fm = map(int, (d["出廠年份"] or x["make"]).split("/"))
        ly, lm = map(int, (d["掛牌年份"] or x["make"]).split("/"))
        np, note = new_price(model, fy, fm)
        my = model_year(fy, fm)
        fam = model.replace("AMG ", "")[0]
        gen = "W177" if fam == "A" else ("W206" if my >= 2022 else "W205")
        color = re.sub(r"\(.*?\)|色$", "", d["車色"]).split("-")[-1] or "—"
        rows.append(dict(id=x["id"], url=SITE + f"detail.aspx?id={x['id']}", model=model, family=fam,
                         gen=gen, kit=d["引擎動能型式"] or "—", color_cat=color,
                         fac=f"{fy}/{fm:02d}", year=fy, lic=f"{ly}/{lm:02d}", lic_date=datetime.date(ly, lm, 1),
                         km=int(x["_mileage"].replace(",", "")), price=float(x["_price"]), new=np, note=note,
                         status="—", dealer=x["seller"]))
    return rows


CFG = dict(
    title="賓士認證中古車 vs 市場行情", h1="Mercedes-Benz 原廠精選中古車 vs 二手車市場行情",
    sub="A-Class（掀背，含 AMG A35/A45）/ C-Class Sedan（含 AMG C43/C63）｜認證車：mercedes-benz-select.com.tw｜市場：8891中古車",
    cert="Select", cert_re=re.compile(r"原廠認證|原廠精選|Benz Select|賓士認證|精選中古", re.I),
    families=[("A", "A-Class"), ("C", "C-Class Sedan")], model_order=MODEL_ORDER, storage_key="benz1",
    family_of=lambda g: g.replace("AMG ", "")[0], market_new=market_new,
    buy_advice=("<li><b>結論（2026-11 資料）：A-Class 買 3~5 年、C-Class 買約 2 年的車最划算。</b>新車開 3 年要虧掉買價約 34~37%；A-Class 3~4 年車開 3 年約虧 19~21%，C-Class 2 年車約虧 16%。</li>"
                "<li><b>A-Class</b>：同一代 W177 賣到現在，折價曲線平順，3~5 年車都在 19~21%。</li>"
                "<li><b>C-Class</b>：2021 → 2022 年 W205 換代成 W206，3~4 年以上的車容易碰上換代後的價格斷層（開 3 年虧 32~45%），所以 2 年車最划算。</li>"
                "<li><b>加上認證車</b>：Mercedes-Benz Select 認證車平均比同里程行情貴約 8~12%，會吃掉買 2~3 年車省下的折價；除非很在意原廠認證保固，否則同車齡的一般市場車較划算。</li>"),
    trend_note="市場車以出廠年同年式牌價估算（A180 2020~2023 以運動版計），AMG 車款與一般車型合併計算折價%。",
    kit_label="動力", info_label="世代・經銷商",
    market_note='擷取 <a href="https://auto.8891.com.tw/mercedes-benz/c" target="_blank">8891中古車</a> 賓士 A、C 系列全部在售刊登（%%N_ITEMS%% 筆），只取「A-Class」（掀背）與「C-Class Sedan」，依車型（A180 / AMG A35 / C200 / AMG C43…）分組，再',
    newprice_note='取自 <a href="https://autos.yahoo.com.tw/new-cars/make/m-benz" target="_blank">Yahoo汽車</a> 各年式牌價。10~12 月出廠的車視為次年式；A180 2020~2023 年式以「運動版」計（另有較便宜的摘星版）。滑鼠移到數字看依據。',
    variant_note="同車型內的版本與選配（如 AMG Line、摘星版、進化版）、車況未納入行情比較。Mercedes-Benz Select 網站未提供銷售狀態，「狀態」欄留空。8891 上 2024~2025 年的 C-Class 刊登很少（多數組別 1~2 台），這些組別只列同年中位數、不計算同里程行情，參考性較低。",
)

if __name__ == "__main__":
    cars = json.load(open(sys.argv[1], encoding="utf-8")) if len(sys.argv) > 1 else fetch_select()
    items = load_8891(["mercedes-benz/a", "mercedes-benz/c"], "8891_benz_items.json", sys.argv[2] if len(sys.argv) > 2 else None)
    make_report(rows_from_select(cars), items, group_of, CFG, "benz_a_c_report.html", "benz_a_c_data.json")
