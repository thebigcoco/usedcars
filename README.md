# usedcars

原廠認證中古車 vs 8891 二手車市場行情比較報告。GitHub Pages 首頁列出所有報告。

| 報告 | 認證車來源 | 產生程式 |
|---|---|---|
| [BMW 318i / 320i Sedan](bmw_318i_320i_report.html) | bps.bmw.com.tw | `build_report.py` |
| [Mercedes-Benz A-Class / C-Class Sedan](benz_a_c_report.html) | mercedes-benz-select.com.tw | `build_benz_report.py` |

- 比較方式：同車款、同出廠年份，並以里程最接近的 7 台 8891 市場車中位數作為「同里程行情」
- 新車售價：Yahoo汽車 各年式牌價
- 共用引擎：`usedcar_report.py`（8891 抓取、行情統計、HTML 版面）

## 更新資料

```bash
python build_report.py
python build_benz_report.py
```

不帶參數時會即時抓取認證車網站與 8891 的資料並重新產生報告（8891 每頁間隔 1 秒，賓士約需 1 分鐘）。
