"""BMW 原廠認證中古車 (BPS) vs 8891 二手車市場行情比較報告 — 318i / 320i Sedan.

Usage:  python build_report.py [bps_all.json] [8891_items.json]
Paths omitted -> fetches live data from https://bps.bmw.com.tw/api/search and
https://auto.8891.com.tw/bmw/3-series/{318i,320i} (8891 result cached to 8891_items.json).
"""
import datetime, json, re, sys, urllib.request
from usedcar_report import load_8891, make_report

# 新車建議售價 (萬元)
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


# 2 系列 Gran Coupe（四門）：Yahoo汽車 https://autos.yahoo.com.tw/new-cars/model/bmw-2-series-gran-coupe-{年式}
# F44：218i M Sport（限量版 / Edition M）、220i Edition M、M235i；F74（2025~）：220 M Racing Edition、M235 xDrive Racing Edition
GC_NEW = {
    "218i GC": {2020: 179, 2021: 179, 2022: 181, 2023: 181},
    "220i GC": {2021: 199, 2022: 201, 2023: 201, 2025: 189, 2026: 190},
    "M235 GC": {2020: 260, 2021: 260, 2022: 264, 2023: 264, 2025: 273, 2026: 275},
}
GC_TRIM = {"218i GC": "218i M Sport / Edition M", "220i GC": "220i Edition M（F44）/ 220 M Racing Edition（F74）",
           "M235 GC": "M235i xDrive（F44）/ M235 xDrive Racing Edition（F74）"}
GC_ORDER = ["218i GC", "220i GC", "M235 GC"]


def gc_group(name):
    """'218i Gran Coupe' / '220 M Racing Edition' / 'M235 xDrive ...' -> comparison group."""
    m = re.match(r"\s*(M235|218|220)", name)
    return {"218": "218i GC", "220": "220i GC", "M235": "M235 GC"}[m.group(1)] if m else None


def gc_new_price(group, year):
    tbl = GC_NEW[group]
    for y in (year, year + 1, year - 1):
        if y in tbl:
            why = f"Yahoo汽車 {y}年式 {GC_TRIM[group]} {tbl[y]}萬"
            return tbl[y], why + (f"（{year}年式未列，用相鄰年式）" if y != year else "")
    raise KeyError(f"no new price for {group} {year}")


def new_price(model, gen, year, kit):
    key = f"{model} {kit}" if kit else model
    # 例外：Yahoo 該年式無對應版本時的處理
    if model == "318i" and gen == "F30" and year == 2015:
        return (178, "Yahoo汽車 2016年式 318i 178萬（318i 自2016年式導入）")
    if model == "318i" and gen == "F30" and year == 2018:
        return (185, "2018年式 318i 建議售價185萬（Yahoo 只列豪華白金版促銷價159萬）")
    if model == "320i" and year == 2019:
        return (229, "G20 320i M Sport 2019/10 上市 229萬（Yahoo 2019年式未列）")
    if key == "318i M Sport" and year == 2025:
        return (227, "Yahoo汽車 2026年式 318i M Sport 227萬（2025下半年出廠，應為2026年式）")
    p = YAHOO.get(year, {}).get(key)
    if p is None and (p := YAHOO.get(year + 1, {}).get(key)) is not None:
        return (p, f"Yahoo汽車 {year+1}年式 {key} {p}萬（{year} 出廠之次年式）")
    if p is None:
        raise KeyError(f"no new price for {year} {key}")
    return (p, f"Yahoo汽車 {year}年式 {key} {p}萬")


# 8891 市場車只知車型與年份、不知版本：以該年式主力版本牌價估算折價（折價趨勢用）
MARKET_NEW = {
    "318i": {2015: 178, 2016: 178, 2017: 181, 2018: 185, 2020: 203, 2021: 206, 2022: 211, 2023: 213, 2024: 216, 2025: 219},
    "320i": {2015: 192, 2016: 199, 2017: 202, 2018: 209, 2019: 229, 2020: 229, 2021: 231, 2022: 240, 2023: 243, 2024: 246, 2025: 249},
}


def market_new(group, year):
    if group in GC_NEW:
        tbl = GC_NEW[group]
        return next((tbl[y] for y in (year, year + 1, year - 1) if y in tbl), None)
    return MARKET_NEW.get(group, {}).get(year)


def load(path=None):
    if path:
        return json.load(open(path, encoding="utf-8"))
    body = "--x\r\nContent-Disposition: form-data; name=\"pagesize\"\r\n\r\n1000\r\n--x\r\nContent-Disposition: form-data; name=\"page\"\r\n\r\n1\r\n--x--\r\n"
    req = urllib.request.Request("https://bps.bmw.com.tw/api/search", data=body.encode(),
                                 headers={"Content-Type": "multipart/form-data; boundary=x", "User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req))


def rows_from_bps(d):
    rows = []
    for x in d["data"]:
        if x["series_name"] == "2" and x["model_type"].startswith("Gran Coup"):
            model = gc_group(x["model_name"]); fam = "2GC"
            np, note = gc_new_price(model, x["fac_year"])
        elif x["model_name"] in ("318i", "320i") and x["model_type"].startswith("Sedan"):
            model = fam = x["model_name"]
            np, note = new_price(x["model_name"], x["source_no"], x["fac_year"], x["kit_name"])
        else:
            continue
        rows.append(dict(id=x["id"], url=f'https://bps.bmw.com.tw/info/{x["id"]}', model=model, family=fam,
                         gen=x["source_no"], kit=x["kit_name"] or "—", color_cat=x["color_category_name"] or "—",
                         fac=f'{x["fac_year"]}/{x["fac_month"]:02d}', year=x["fac_year"],
                         lic=f'{x["lic_year"]}/{x["lic_month"]:02d}', lic_date=datetime.date(x["lic_year"], x["lic_month"], 1),
                         km=int(x["mileage"]), price=float(x["price"]), new=np, note=note,
                         status=x["status_name"], dealer=x["show_name"]))
    return rows


def group_of(o):
    """8891 listing -> comparison group (318i / 320i Sedan, 2-Series Gran Coupe)."""
    if o.get("kindEnName") == "2-Series Gran Coupe":
        return gc_group(o["modelEnName"])
    if "Sedan" not in o.get("kindEnName", ""):
        return None
    m = o["modelEnName"][:4]
    return m if m in ("318i", "320i") else None


CFG = dict(
    title="BMW 認證中古車 vs 市場行情", h1="BMW 原廠認證中古車 vs 二手車市場行情",
    sub="3 系列 318i / 320i Sedan、2 系列 Gran Coupe（四門）｜BPS：bps.bmw.com.tw｜市場：8891中古車",
    cert="BPS", cert_re=re.compile(r"原廠認證|BPS|Premium Selection", re.I),
    families=[("318i", "318i"), ("320i", "320i"), ("2GC", "2 系列 Gran Coupe")], model_order=["318i", "320i"] + GC_ORDER, storage_key="bmw6",
    family_of=lambda g: "2GC" if g.endswith(" GC") else g, market_new=market_new,
    buy_advice=("<li><b>結論（2026-11 資料）：3 系列買約 3 年的車最划算。</b>新車或 1 年車開 3 年要虧掉買價約 30~42%；3 年車開 3 年只虧約 22~25%，320i 買 4 年車甚至只虧約 14%。</li>"
                "<li><b>2 系列 Gran Coupe</b>：第一年折約 15%（F74 220），F44 218i 4~6 年已折掉新車價 44~55%。2023~2024 年市場上幾乎沒有這款車，2~3 年車樣本不足，算不出最划算的車齡；表中「1 年 → 4 年」橫跨 F74 與 F44 兩代，僅供參考。"
                "BPS 的 2025 年 220 Gran Coupe 比同里程行情便宜約 2%，2022 年 218i 與行情持平；2020~2021 年的 218i 則貴約 9~13%。</li>"
                "<li><b>第一年折最多</b>：318i / 320i 第一年就折掉新車價約 21~24%，之後每年多折約 4~9 個百分點，5 年後約剩新車價一半。</li>"
                "<li><b>5~7 年車反而變貴</b>：開 3 年要虧 40~50%（8 年以上車價已低，約 30~36%），因為會碰上換代與小改款的價格斷層：2018 年 F30 → 2020 年 G20 換代、2022 → 2023 年小改款，舊款會一次掉一大截。</li>"
                "<li><b>加上認證車</b>：3 年內的 BPS 認證車價格與同里程市場車幾乎相同（±2% 內），卻多了原廠認證保固與保養紀錄，<b>2~3 年的 BPS 車 CP 值最高</b>。</li>"),
    trend_note="市場車以該年式主力版本牌價估算（318i：F30 標準版／G20 Luxury、Sport；320i：Sport Line／M Sport；2 系列 Gran Coupe：218i M Sport、220i Edition M／220 M Racing Edition、M235），未區分版本。",
    market_note='擷取 <a href="https://auto.8891.com.tw/bmw/3-series/318i" target="_blank">8891中古車</a> 318i、320i 與 2 系列全部在售刊登（%%N_ITEMS%% 筆），2 系列只取「2-Series Gran Coupe」（四門），依車型（218i / 220i / M235）分組，',
    newprice_note='取自 <a href="https://autos.yahoo.com.tw/new-cars/make/bmw" target="_blank">Yahoo汽車</a> 各年式牌價，以出廠年對應年式、依版本配對（滑鼠移到數字看依據）；少數缺漏改用相鄰年式或上市新聞價格，約 ±3 萬誤差。',
    variant_note="版本差異（Luxury / Sport / M Sport）、選配與車況未納入行情比較，同組內配備較高的車價格偏高屬正常。2 系列 Gran Coupe 有兩代：F44（2020~2023，218i / 220i / M235i）與 F74（2025~，220 / M235），2024 年無新車導入；BPS 的「220 Gran Coupe」（F74）與 220i 併為「220i GC」組，依年份自然分開兩代。",
)

if __name__ == "__main__":
    data = load(sys.argv[1] if len(sys.argv) > 1 else None)
    items = load_8891(["bmw/3-series/318i", "bmw/3-series/320i", "bmw/2-series"], "8891_items.json", sys.argv[2] if len(sys.argv) > 2 else None)
    make_report(rows_from_bps(data), items, group_of, CFG, "bmw_318i_320i_report.html", "bmw_318i_320i_data.json")
