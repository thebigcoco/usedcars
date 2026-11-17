# usedcars

BMW 原廠認證中古車（BPS）318i / 320i Sedan 與 8891 二手車市場行情比較報告。

- 報告：[bmw_318i_320i_report.html](bmw_318i_320i_report.html)（GitHub Pages 首頁即導向此報告）
- 比較方式：同車款、同出廠年份，並以里程最接近的 7 台 8891 市場車中位數作為「同里程行情」
- 新車售價：Yahoo汽車 各年式牌價

## 更新資料

```bash
python build_report.py
```

不帶參數時會即時抓取 bps.bmw.com.tw 與 auto.8891.com.tw 的資料並重新產生報告。
也可指定快取檔：`python build_report.py bps_all.json 8891_items.json`。
