# 方向模型回放報告（direction-v2）

產生時間：2026-11-19 17:03 台北

資料：`data/pre-market-latest.json` 的 942 個歷史版本（git），去重後 4086 則事件，涵蓋 2026-08-12 ~ 2026-11-19（99 個台北日期）。下表取最近 21 天（2026-10-30 ~ 2026-11-19）。

- 改判前 = direction-v1（#9，只有 Fed / 關稅 / 出口管制三條路徑），從 git 載入原始規則重算。
- 改判後 = direction-v2（#11，全部路徑 + 正向路徑；路徑以目前 geo_focus 重新比對）。
- 大盤 = 加權指數當日漲跌幅（TWSE FMTQIK，`data/market/taiex-daily.json`）。盤前快照裡的類股/國際指數自 8 月起是報價源失敗後沿用的舊值，不能當大盤錨點（#10 已改用官方來源）。

## 每日：改判前後的利多 / 利空欄

| 日期 | 加權指數 | 事件 | 改判前 利多 | 改判前 利空 | 改判後 利多 | 改判後 利空 | 上漲日利多欄 |
|---|---:|---:|---:|---:|---:|---:|---|
| 2026-10-30 | -2.49% | 90 | 0 | 0 | 0 | 1 | — |
| 2026-10-31 | 休市/無資料 | 25 | 0 | 2 | 1 | 5 | — |
| 2026-11-01 | 休市/無資料 | 12 | 0 | 0 | 0 | 2 | — |
| 2026-11-02 | -0.65% | 18 | 0 | 0 | 1 | 1 | — |
| 2026-11-03 | -3.59% | 52 | 0 | 0 | 2 | 2 | — |
| 2026-11-04 | -0.83% | 42 | 0 | 0 | 3 | 3 | — |
| 2026-11-05 | -3.20% | 47 | 0 | 1 | 2 | 4 | — |
| 2026-11-06 | -4.51% | 40 | 0 | 1 | 2 | 4 | — |
| 2026-11-07 | 休市/無資料 | 19 | 0 | 0 | 2 | 1 | — |
| 2026-11-08 | 休市/無資料 | 8 | 0 | 0 | 0 | 1 | — |
| 2026-11-09 | +4.94% | 22 | 1 | 0 | 2 | 1 | 有（2） |
| 2026-11-10 | +2.52% | 56 | 0 | 3 | 4 | 6 | 有（4） |
| 2026-11-11 | +3.62% | 47 | 0 | 2 | 1 | 3 | 有（1） |
| 2026-11-12 | -2.63% | 35 | 1 | 0 | 1 | 1 | — |
| 2026-11-13 | +1.35% | 56 | 0 | 0 | 0 | 4 | 空 |
| 2026-11-14 | 休市/無資料 | 41 | 0 | 5 | 0 | 6 | — |
| 2026-11-15 | 休市/無資料 | 7 | 1 | 0 | 1 | 2 | — |
| 2026-11-16 | -6.03% | 28 | 0 | 0 | 0 | 4 | — |
| 2026-11-17 | -2.31% | 53 | 1 | 3 | 3 | 6 | — |
| 2026-11-18 | +0.26% | 58 | 0 | 0 | 3 | 2 | 有（3） |
| 2026-11-19 | -4.40% | 51 | 2 | 1 | 5 | 4 | — |

**上漲日利多欄為空**：改判前 4/5 天，改判後 1/5 天。近 7 天上漲日仍為空：2026-11-13。

## 各路徑分佈（改判後，回放視窗）

| 路徑 | 利多 | 利空 | 中性 | 中性原因前三 |
|---|---:|---:|---:|---|
| ai_capex | 9 | 0 | 8 | no_rule ×8 |
| china_macro | 2 | 1 | 8 | no_rule ×8 |
| export_control | 1 | 1 | 10 | no_rule ×8, export_control.gate ×2 |
| fed_rates | 3 | 16 | 303 | fed_rates.gate ×200, no_rule ×103 |
| fx_capital | 1 | 0 | 112 | fx_capital.gate ×111, no_rule ×1 |
| hormuz_energy | 12 | 26 | 116 | no_rule ×105, hormuz_energy.small_move ×11 |
| military_conflict | 1 | 3 | 63 | military_conflict.gate ×32, no_rule ×31 |
| shipping_lane | 1 | 15 | 50 | no_rule ×45, shipping_lane.gate ×5 |
| supply_chain | 1 | 0 | 10 | no_rule ×10 |
| taiwan_strait | 0 | 0 | 4 | no_rule ×4 |
| tariff | 2 | 1 | 27 | tariff.gate ×18, no_rule ×9 |

## 改判明細（回放視窗內方向有變的事件）

| 日期 | 層級 | 路徑 | 改判前 | 改判後 | 標題 | 命中規則 |
|---|---|---|---|---|---|---|
| 2026-10-30 | normal | shipping_lane | neutral | bear | UKMTO: Company security officer has informed UKMTO that their tanker has been struck by unknown projectile whilst completing outbound transit of Strait of Hormuz. | `shipping_lane.disrupt:'tanker has been struck'` |
| 2026-10-31 | normal | hormuz_energy | neutral | bear | NYMEX WTI 原油 12 月期貨結算價為每桶 104.12 美元，上漲 2.12 美元，漲幅 2.08%。 | `hormuz_energy.supply_shock:'WTI Crude December futures settle at $104.12 a barrel, up $2.12'` |
| 2026-10-31 | normal | hormuz_energy | neutral | bear | UKMTO：收到關於霍爾木茲海峽事件的遲到報告。穿越霍爾木茲海峽的原油油輪被彈丸擊中 | `hormuz_energy.supply_shock:'tanker hit'` |
| 2026-10-31 | normal | hormuz_energy | neutral | bear | 布蘭特原油期貨結算價為 117.64 美元/桶，上漲 2.76 美元，漲幅 2.4%。 | `hormuz_energy.supply_shock:'Brent Crude futures settle at $117.64/bbl, up $2.76'` |
| 2026-10-31 | normal | hormuz_energy | neutral | bull | 伊朗外長向半島電視台表示：伊朗計畫只是目前提出的重新開放霍爾木茲海峽的唯一提議 | `hormuz_energy.supply_relief:'reopen Strait'` |
| 2026-11-01 | normal | hormuz_energy | neutral | bear | 伊朗安全負責人雷扎伊：霍爾木茲海峽將保持關閉，直到德黑蘭的條件得到滿足 | `hormuz_energy.supply_shock:'Hormuz to stay closed'` |
| 2026-11-01 | normal | hormuz_energy | neutral | bear | 伊朗海軍：油輪在霍爾木茲海峽觸雷後起火 - 官方媒體 | `hormuz_energy.supply_shock:'tanker ignites'` |
| 2026-11-02 | normal | china_macro | neutral | bull | 10 月中國一般製造業 PMI 為 52.0，預期為 51.6 | `china_macro.print_beat:52 vs 51.6` |
| 2026-11-02 | watch | military_conflict | neutral | bear | 美國的海灣盟友準備對伊朗進行新一輪打擊及其反擊 - 華爾街日報 | `military_conflict.escalate:'prepare for new round of strikes' / military_conflict.escalate:'strikes on Iran'` |
| 2026-11-03 | normal | hormuz_energy | neutral | bull | 布蘭特原油期貨結算價104.77美元/桶，下跌8.66美元，跌幅7.63% | `hormuz_energy.supply_relief:'Brent Crude futures settle at $104.77/bbl, down $8.66' / hormuz_energy.supply_relief:'Crude futures settle at $104.77/bbl, down'` |
| 2026-11-03 | normal | hormuz_energy | neutral | bull | NYMEX WTI 原油 12 月期貨結算價每桶 96.46 美元，下跌 7.66 美元，下跌 7.36% | `hormuz_energy.supply_relief:'WTI Crude Dec. futures settle at $96.46 a barrel down $7.66'` |
| 2026-11-03 | normal | shipping_lane | neutral | bear | UKMTO：11 月 1 日，一艘船在阿曼附近被砲彈擊中 | `shipping_lane.disrupt:'vessel was struck'` |
| 2026-11-03 | watch | shipping_lane | neutral | bear | UKMTO: Attack on a vessel in the waters of the Strait of Hormuz and the rescue of its crew by Oman. | `shipping_lane.disrupt:'Attack on a vessel in the waters of the Strait of Hormuz'` |
| 2026-11-04 | normal | ai_capex | neutral | bull | 谷歌將投資 150 億美元擴建馬來西亞資料中心。 | `ai_capex.demand_up:'invest $15 billion'` |
| 2026-11-04 | normal | china_macro | neutral | bear | 10 月中國一般服務業 PMI 為 50.8，低於 9 月的 51.6 | `china_macro.downside:'PMI at 50.8 in October, down from'` |
| 2026-11-04 | normal | hormuz_energy | neutral | bull | 布蘭特原油期貨結算價103.60美元/桶，下跌1.17美元，跌幅1.12% | `hormuz_energy.supply_relief:'Brent Crude futures settle at $103.60/bbl, down $1.17' / hormuz_energy.supply_relief:'Crude futures settle at $103.60/bbl, down'` |
| 2026-11-04 | watch | military_conflict | neutral | bull | 川普告訴英國《金融時報》，美國沒有立即計劃攻擊伊朗 | `military_conflict.escalate:'plan to attack' negated_by:'no'` |
| 2026-11-04 | normal | shipping_lane | neutral | bear | 英國海軍：收到報告稱船隻在阿曼利馬東北 9 海裡處被不明彈丸擊中；船舶和船員安全 | `shipping_lane.disrupt:'vessel struck'` |
| 2026-11-04 | normal | shipping_lane | neutral | bear | Iran's IRGC: four tankers destroyed after hitting mines south of Strait of Hormuz, two other ships seized - statement | `shipping_lane.disrupt:'ships seized'` |
| 2026-11-05 | normal | fx_capital | neutral | bull | 美元指數下跌0.26%至101.2100 | `fx_capital.inflow:'dollar index drops'` |
| 2026-11-05 | normal | hormuz_energy | neutral | bull | NYMEX WTI 原油 12 月期貨結算價每桶 88.12 美元，下跌 7.97 美元，下跌 8.29% | `hormuz_energy.supply_relief:'WTI crude Dec. futures settle at $88.12 a barrel, down $7.97'` |
| 2026-11-05 | normal | hormuz_energy | neutral | bear | 日本央行會議紀錄：多位委員一致認為原油價格上漲導致物價上行風險較高 | `hormuz_energy.supply_shock:'oil price rise'` |
| 2026-11-05 | normal | hormuz_energy | neutral | bear | 伊朗伊斯蘭革命衛隊：油輪在未經授權的霍爾木茲海峽航行時觸雷 | `hormuz_energy.supply_shock:'tanker hit'` |
| 2026-11-05 | normal | hormuz_energy | neutral | bear | 今天中午，另外兩艘違規油輪在霍爾木茲海峽以東的不安全地區與水雷相撞並起火 - IRIB | `hormuz_energy.supply_shock:'tankers collided with sea mines and caught fire'` |
| 2026-11-06 | normal | ai_capex | neutral | bull | Google 將投資 170 億美元興建懷俄明州第一個資料中心。 $GOOGL | `ai_capex.demand_up:'invest $17b'` |
| 2026-11-06 | normal | ai_capex | neutral | bull | 聯準會穆薩利姆：資料中心擴建有助於強勁需求 | `ai_capex.demand_up:'strong demand'` |
| 2026-11-06 | normal | hormuz_energy | neutral | bear | 布蘭特原油期貨結算價98.29美元/桶，上漲3.67美元，漲幅3.88% | `hormuz_energy.supply_shock:'Brent Crude futures settle at $98.29/bbl, up $3.67'` |
| 2026-11-06 | normal | hormuz_energy | neutral | bear | NYMEX WTI 原油 12 月期貨結算價每桶 90.52 美元，上漲 2.40 美元，漲幅 2.72% | `hormuz_energy.supply_shock:'WTI Crude Dec. futures settle at $90.52 a barrel up $2.40'` |
| 2026-11-06 | normal | shipping_lane | neutral | bear | 11月5日，希臘營運的一艘成品油輪在海灣發生爆炸，造成一名海員死亡，油輪很可能是被不明飛彈擊中－希臘運營商 | `shipping_lane.disrupt:'tanker in the Gulf, tanker was likely struck'` |
| 2026-11-07 | normal | ai_capex | neutral | bull | Google收購 Crusoe 懷俄明州資料中心站點 $GOOGL | `ai_capex.demand_up:'buys Crusoe’s Wyoming data center'` |
| 2026-11-07 | normal | hormuz_energy | neutral | bear | 伊朗海軍：油輪在霍爾木茲海峽東部起火 - 伊朗媒體 | `hormuz_energy.supply_shock:'tanker ignites'` |
| 2026-11-07 | normal | shipping_lane | neutral | bull | 此舉旨在降低運費和油價 | `shipping_lane.restore:'easing freight rates'` |
| 2026-11-08 | normal | shipping_lane | neutral | bear | 伊朗伊斯蘭革命衛隊海軍：兩艘油輪在霍爾木茲海峽附近觸雷 - 伊朗國家電視台 | `shipping_lane.disrupt:'tankers struck'` |
| 2026-11-09 | normal | china_macro | neutral | bull | 中國將延長暫停針對美國企業的出口管制。 | `china_macro.upside:'extend suspension of exports controls'` |
| 2026-11-09 | normal | hormuz_energy | neutral | bear | 伊朗海軍：油輪在霍爾木茲海峽以東觸雷後起火－伊朗媒體 | `hormuz_energy.supply_shock:'tanker ignites'` |
| 2026-11-10 | normal | ai_capex | neutral | bull | 人為：Google、英偉達、AMD、博通、美光、微軟、台積電將以 IPO 價格透過私募投資 260 億美元 | `ai_capex.demand_up:'invest $26 billion'` |
| 2026-11-10 | normal | ai_capex | neutral | bull | AMD、博通、Google等公司將向 Anthropic 投資 260 億美元。 | `ai_capex.demand_up:'invest $26b'` |
| 2026-11-10 | normal | hormuz_energy | neutral | bull | Brent Crude futures settle at $92.57/bbl, down $5.75, 5.85%. | `hormuz_energy.supply_relief:'Brent Crude futures settle at $92.57/bbl, down $5.75' / hormuz_energy.supply_relief:'Crude futures settle at $92.57/bbl, down'` |
| 2026-11-10 | normal | hormuz_energy | neutral | bull | NYMEX WTI Crude December futures settle at $86.85 a barrel, down $3.98, 4.38%. | `hormuz_energy.supply_relief:'WTI Crude December futures settle at $86.85 a barrel, down $3.98'` |
| 2026-11-10 | normal | hormuz_energy | neutral | bear | 伊朗伊斯蘭革命衛隊海軍在過去24小時內禁用了4艘試圖通過非法路線通過霍爾木茲海峽的大型油輪的導航系統，導致它們無法繼續航行 - Press TV | `hormuz_energy.supply_shock:'disabled the navigation systems of 4 large oil tankers'` |
| 2026-11-10 | normal | hormuz_energy | neutral | bear | 伊朗伊斯蘭革命衛隊海軍：兩艘油輪在霍爾木茲海峽觸雷後起火 - 國家媒體。 | `hormuz_energy.supply_shock:'tankers caught fire'` |
| 2026-11-10 | normal | shipping_lane | neutral | bear | UKMTO：油輪被不明彈丸擊中。 | `shipping_lane.disrupt:'Tanker struck'` |
| 2026-11-11 | normal | hormuz_energy | neutral | bull | 布蘭特原油期貨結算價為 91.49 美元/桶，下跌 1.08 美元，跌幅 1.17%。 | `hormuz_energy.supply_relief:'Brent crude futures settle at $91.49/bbl, down $1.08' / hormuz_energy.supply_relief:'crude futures settle at $91.49/bbl, down'` |
| 2026-11-11 | normal | hormuz_energy | neutral | bear | 德國經濟專家委員會主席：從伊朗戰爭引發的油價飆升中恢復速度快於預期 | `hormuz_energy.supply_shock:'oil price surge'` |
| 2026-11-12 | normal | hormuz_energy | neutral | bear | 布蘭特原油期貨結算價92.76美元/桶，上漲1.27美元，漲幅1.39% | `hormuz_energy.supply_shock:'Brent crude futures settle at $92.76/bbl, up $1.27'` |
| 2026-11-13 | normal | hormuz_energy | neutral | bear | 布蘭特原油期貨結算價為 95.82 美元/桶，上漲 3.06 美元，漲幅 3.3%。 | `hormuz_energy.supply_shock:'Brent Crude futures settle at $95.82/bbl, up $3.06'` |
| 2026-11-13 | normal | hormuz_energy | neutral | bear | NYMEX WTI 原油 12 月期貨結算價每桶 88.74 美元，上漲 2.21 美元，漲幅 2.55%。 | `hormuz_energy.supply_shock:'WTI Crude December futures settle at $88.74 a barrel, up $2.21'` |
| 2026-11-13 | watch | military_conflict | neutral | bear | 伊朗通訊社：伊朗南部的錫里克遭受攻擊。 | `military_conflict.escalate:'Attack on southern Iran'` |
| 2026-11-13 | normal | shipping_lane | neutral | bear | 伊朗革命衛隊海軍：運載液化氣的油輪撞上水雷，導致霍爾木茲海峽爆炸 | `shipping_lane.disrupt:'Tanker carrying liquefied gas struck'` |
| 2026-11-14 | normal | hormuz_energy | neutral | bear | 伊朗伊斯蘭革命衛隊海軍：兩艘油輪在試圖通過霍爾木茲海峽時觸雷後爆炸並起火 - 國家媒體 | `hormuz_energy.supply_shock:'tankers exploded and caught fire'` |
| 2026-11-15 | normal | hormuz_energy | neutral | bear | 伊朗伊斯蘭革命衛隊海軍：兩艘油輪在霍爾木茲海峽觸雷後起火 - 官方媒體 | `hormuz_energy.supply_shock:'tankers ignite'` |
| 2026-11-15 | normal | military_conflict | neutral | bear | 伊朗法爾斯通訊社：伊朗伊斯蘭革命衛隊對美國駐巴林基地發動攻擊，以報復美國的「敵對」行動 | `military_conflict.escalate:'launched strikes on' / military_conflict.escalate:'strikes on US'` |
| 2026-11-16 | normal | hormuz_energy | neutral | bear | 伊朗海軍：油輪在霍爾木茲海峽以東觸雷後起火 - 官方媒體 | `hormuz_energy.supply_shock:'tanker ignites'` |
| 2026-11-16 | normal | hormuz_energy | neutral | bear | Iran's army: oil tanker ignites after striking naval mine in eastern Strait of Hormuz - state media | `hormuz_energy.supply_shock:'tanker ignites'` |
| 2026-11-16 | normal | shipping_lane | neutral | bear | 伊朗伊斯蘭革命衛隊：兩艘油輪在霍爾木茲海峽觸雷導致爆炸 - 官方媒體 | `shipping_lane.disrupt:'tankers struck'` |
| 2026-11-16 | normal | shipping_lane | neutral | bear | UKMTO gets report of vessel struck by projectile in Hormuz | `shipping_lane.disrupt:'vessel struck'` |
| 2026-11-17 | normal | hormuz_energy | neutral | bull | 布蘭特原油期貨結算價92.44美元/桶，下跌3.40美元，跌幅3.55% | `hormuz_energy.supply_relief:'Brent Crude futures settle at $92.44/bbl, down $3.40' / hormuz_energy.supply_relief:'Crude futures settle at $92.44/bbl, down'` |
| 2026-11-17 | normal | hormuz_energy | neutral | bull | NYMEX WTI 12 月原油期貨結算價每桶 85.72 美元，下跌 2.84 美元，下跌 3.21% | `hormuz_energy.supply_relief:'WTI crude Dec. futures settle at $85.72 a barrel, down $2.84'` |
| 2026-11-17 | normal | hormuz_energy | neutral | bear | 伊朗海軍：第三艘油輪在霍爾木茲海峽以東觸雷後起火 - 國家媒體 | `hormuz_energy.supply_shock:'tanker caught fire'` |
| 2026-11-17 | normal | shipping_lane | neutral | bear | UKMTO：第三方報告油輪在穿越霍爾木茲海峽時遭到襲擊，導致該船癱瘓並導致機艙起火 | `shipping_lane.disrupt:'attack involving tanker transiting Strait of Hormuz' / shipping_lane.disrupt:'attack involving tanker transiting'` |
| 2026-11-17 | normal | shipping_lane | neutral | bear | UKMTO：11月13日油輪被彈丸擊中 | `shipping_lane.disrupt:'Tanker was struck'` |
| 2026-11-18 | normal | ai_capex | neutral | bull | 富士康擴大與 Nvidia 的下一代 GPU 和網路平台合作夥伴關係 | `ai_capex.demand_up:'expands partnership with Nvidia for next-gen GPU'` |
| 2026-11-18 | normal | ai_capex | neutral | bull | Nvidia 3Q營收$115.8B，季增20.3%，較去年同期成長103.1%。 $NVDA | `ai_capex.demand_up:'revenue $115.8B, up 20.3% QoQ, up 103.1%'` |
| 2026-11-18 | watch | shipping_lane | neutral | bear | Adnoc：11 月 17 日，一艘船在經過霍爾木茲海峽時遭到攻擊。 | `shipping_lane.disrupt:'vessel attacked'` |
| 2026-11-18 | normal | shipping_lane | neutral | bear | UKMTO 收到有關阿曼海塞卜以北 13 海裡事件的最新報告。油輪在霍爾木茲海峽被砲彈擊中。 | `shipping_lane.disrupt:'Tanker struck'` |
| 2026-11-18 | normal | supply_chain | neutral | bull | 英偉達擴大了與供應鏈合作夥伴的承諾，以支援人工智慧基礎設施的擴張 | `supply_chain.restore:'broadens commitments with supply chain'` |
| 2026-11-19 | normal | ai_capex | neutral | bull | 日本央行行長上田：強勁的全球需求促進了日本的出口和資本支出，提高了多種商品的價格 | `ai_capex.demand_up:'boosting Japan’s exports, capex' / ai_capex.demand_up:'robust global al demand'` |
| 2026-11-19 | normal | hormuz_energy | neutral | bear | 3艘違規油輪在霍爾木茲海峽東部起火 - IRIB News | `hormuz_energy.supply_shock:'tankers caught fire'` |
| 2026-11-19 | normal | hormuz_energy | neutral | bear | UKMTO：油輪在通過霍爾木茲海峽出境時在機艙內被不明彈丸擊中 | `hormuz_energy.supply_shock:'tanker hit'` |
| 2026-11-19 | normal | hormuz_energy | neutral | bear | IRIB新聞：三艘油輪無視海軍警告，在霍爾木茲海峽以東觸雷後起火併停止——伊朗陸軍 | `hormuz_energy.supply_shock:'tankers caught fire'` |
| 2026-11-19 | normal | hormuz_energy | neutral | bull | Brent Crude futures settle at $91.95/bbl, down $1.19, 1.28% | `hormuz_energy.supply_relief:'Brent Crude futures settle at $91.95/bbl, down $1.19' / hormuz_energy.supply_relief:'Crude futures settle at $91.95/bbl, down'` |
| 2026-11-19 | normal | hormuz_energy | neutral | bull | NYMEX WTI 12 月原油期貨結算價每桶 83.26 美元，下跌 2.75 美元，下跌 3.20% | `hormuz_energy.supply_relief:'WTI crude Dec. futures settle at $83.26 a barrel, down $2.75'` |

## 補充：翻譯快取全量分佈（無日期）

`data/pre-market-title-zh.json` 共 11341 則標題：

| 路徑 | 總數 | 利多 | 利空 | 中性 |
|---|---:|---:|---:|---:|
| ai_capex | 24 | 12 | 0 | 12 |
| china_macro | 33 | 6 | 1 | 26 |
| export_control | 36 | 2 | 2 | 32 |
| fed_rates | 1776 | 25 | 126 | 1625 |
| fx_capital | 298 | 1 | 4 | 293 |
| hormuz_energy | 556 | 30 | 77 | 449 |
| military_conflict | 266 | 1 | 13 | 252 |
| policy_support | 10 | 0 | 0 | 10 |
| shipping_lane | 230 | 2 | 31 | 197 |
| supply_chain | 31 | 2 | 0 | 29 |
| taiwan_strait | 15 | 0 | 0 | 15 |
| tariff | 167 | 5 | 9 | 153 |
| tw_fundamental | 9 | 4 | 0 | 5 |
| us_tech_rally | 15 | 2 | 2 | 11 |

中性比例高是刻意的：規則只在有明確動作且通過範圍閘門時才下判斷，否則留 0，不硬猜。俄烏例行攻擊、紅海以外的黑海航運、非台幣的匯率、1% 以內的油價結算都被閘門擋在中性。
