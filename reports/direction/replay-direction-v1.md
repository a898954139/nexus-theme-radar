# 方向模型回放報告（direction-v1）

產生時間：2026-11-18 16:12 台北

資料：`data/pre-market-latest.json` 的 28 個歷史版本（git），去重後 327 則事件，涵蓋 2026-11-10 ~ 2026-11-18（9 天，台北日期）。

> **限制**：盤前看板自 2026-11-13 才開始 commit 快照，git 內只有約 5–6 天。Issue 要求的 ≥14 天回放需等快照累積（或取得 Actions 環境的 `pre-market-archive/`）後重跑本腳本：`python scripts/replay_direction.py`。下方另以翻譯快取（全部歷史標題、無日期）補充分佈檢查。

## 改判前後：每日統計

改判前：所有事件都在同一個風險清單（重大/留意），沒有利多欄。改判後：三條已建模路徑拆成利多/利空/中性。

| 日期 | 全部事件 | 三路徑事件 | 利多 | 利空 | 中性 | 改判前利多欄 |
|---|---:|---:|---:|---:|---:|---:|
| 2026-11-10 | 8 | 5 | 0 | 2 | 3 | 0 |
| 2026-11-11 | 47 | 29 | 0 | 2 | 27 | 0 |
| 2026-11-12 | 35 | 12 | 1 | 0 | 11 | 0 |
| 2026-11-13 | 56 | 26 | 0 | 0 | 26 | 0 |
| 2026-11-14 | 41 | 29 | 0 | 5 | 24 | 0 |
| 2026-11-15 | 7 | 1 | 1 | 0 | 0 | 0 |
| 2026-11-16 | 28 | 9 | 0 | 0 | 9 | 0 |
| 2026-11-17 | 54 | 27 | 1 | 3 | 23 | 0 |
| 2026-11-18 | 51 | 24 | 0 | 0 | 24 | 0 |

## 各路徑分佈

| 路徑 | 利多 | 利空 | 中性 | 中性原因前三 |
|---|---:|---:|---:|---|
| fed_rates | 1 | 11 | 130 | fed_rates.gate ×71, no_rule ×59 |
| tariff | 1 | 0 | 10 | tariff.gate ×7, no_rule ×3 |
| export_control | 1 | 1 | 7 | no_rule ×6, export_control.gate ×1 |

## 改判明細（方向 ≠ 0 的事件）

改判前這些事件全部以風險卡呈現；改判後依方向進入利多或利空欄。

| 日期 | 層級 | 路徑 | 方向 | 標題 | 命中規則 |
|---|---|---|---|---|---|
| 2026-11-10 | watch | fed_rates | bear | 聯準會洛根：今年冬天升息的速度可能會比聯準會迄今為止的速度更快。 | `fed_rates.hike:'raise interest rates'` |
| 2026-11-10 | normal | fed_rates | bear | 德意志銀行預計聯準會將在 2027 年 1 月額外升息 25 個基點，較先前預測的 12 月和 3 月升息 | `fed_rates.hike:'rate hike'` |
| 2026-11-11 | normal | fed_rates | bear | 聯準會古爾斯比在 PBS Newshour 節目中表示：消費者物價指數 (CPI) 已接近通膨水平 | `fed_rates.hawkish:'troubling on inflation'` |
| 2026-11-11 | normal | fed_rates | bear | 聯準會保爾森：鑑於高通膨，進一步「漸進」升息是適當的 | `fed_rates.hike:'rate increases'` |
| 2026-11-12 | normal | tariff | bull | 商務部：中美雙方就降稅事宜保持密切溝通 | `tariff.relief:'tariff reduction'` |
| 2026-11-14 | watch | fed_rates | bear | 聯準會戴利：我們很可能需要升息。 | `fed_rates.hike:'raise rates'` |
| 2026-11-14 | normal | fed_rates | bear | 美國銀行經濟學家將聯準會 2027 年 3 月前第三次升息的觀點納入其中。 | `fed_rates.hike:'rate hike'` |
| 2026-11-14 | normal | fed_rates | bear | 聯準會傑佛遜：人工智慧的發展讓我對總需求保持警惕，這是通膨壓力的根源 | `fed_rates.hawkish:'inflation pressure'` |
| 2026-11-14 | normal | fed_rates | bear | 傑佛遜：通膨率遠高於2%目標 | `fed_rates.hawkish:'inflation stays significantly above 2'` |
| 2026-11-14 | normal | fed_rates | bear | 聯準會柯林斯：鑑於通膨和就業數據，央行可能需要將利率提高到超出近期預測的水平 | `fed_rates.hike:'raise rates'` |
| 2026-11-15 | normal | fed_rates | bull | 貝森特對福斯警告聯準會不要進一步收緊貨幣政策 | `fed_rates.hawkish:'tightening' negated_by:'warns Federal Reserve against'` |
| 2026-11-17 | watch | export_control | bull | 美國負責經濟事務的副國務卿赫爾伯格：美國沒有計劃針對愛立信、ASML、三星或SK海力士等供應商，或將其逐出供應鏈——Semafor Event。 | `export_control.tighten:'push them out of its supply chain' negated_by:'no' / export_control.tighten:'target suppliers' negated_by:'no'` |
| 2026-11-17 | normal | export_control | bear | China's commerce ministry, on US chip export curb: Strongly oppose this | `export_control.tighten:'chip export curb'` |
| 2026-11-17 | watch | fed_rates | bear | 聯準會哈馬克：我們可能會看到勞動市場緊縮的跡象。 | `fed_rates.hawkish:'tightening'` |
| 2026-11-17 | watch | fed_rates | bear | 聯準會穆薩利姆：除非聯準會升息，否則最有可能出現的情況是通膨持續走高 | `fed_rates.hike:'raises rates' / fed_rates.hawkish:'inflation remains elevated'` |

## 補充：翻譯快取全量分佈（無日期）

`data/pre-market-title-zh.json` 共 11085 則標題；落在三條已建模路徑者：

| 路徑 | 總數 | 利多 | 利空 | 中性 |
|---|---:|---:|---:|---:|
| fed_rates | 1719 | 23 | 122 | 1574 |
| tariff | 166 | 5 | 9 | 152 |
| export_control | 34 | 2 | 2 | 30 |

中性比例高是刻意的：規則只在有明確動作（降息/升息、加徵/暫緩、收緊/放寬）且通過範圍閘門時才下判斷，否則留 0，不硬猜。Fed 路徑偏空反映 2026 下半年 Fed 處於升息循環的實際語境。
