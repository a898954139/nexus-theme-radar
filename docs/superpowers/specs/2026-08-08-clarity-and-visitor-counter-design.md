# Clarity 分析 + 訪客計數器

日期:2026-08-08
狀態:待實作

## 目標

兩個獨立的功能,共用一個顯示位置:

1. **Microsoft Clarity** — 錄製使用者行為(session recording、heatmap),資料在 Clarity 後台看。
2. **訪客計數器** — 在 StatusBar 顯示「總瀏覽數」與「目前線上人數」,資料自己存 Supabase。

兩者之間沒有任何程式相依,可以分開實作、分開回退。

## 背景與限制

站台是純靜態 SPA(Vite + React),部署在 GitHub Pages,**沒有後端伺服器**。這個限制決定了計數器的整個架構:瀏覽器不能直接寫 Supabase,因為 anon key 必然公開在前端 JS 裡,任何人都能無限灌數字。

路由是 hash-based(`#page=momentum`),Clarity 不會自動把 hash 變化視為新的 page view,需要手動回報。

現有的 `theme_radar` schema 建立了本專案的資料庫慣例:私有 schema、專屬最小權限角色、大量 CHECK constraint、明確 REVOKE。計數器沿用同一套做法。

---

## 一、Microsoft Clarity

### 設定

- Project ID:`xz7wk63q2s`
- 安裝方式:手動貼 snippet 進 `index.html` 的 `<head>`

Project ID 不是密鑰,本來就會出現在前端原始碼,可以直接進版控。

### 範圍

只有 `index.html`。`flows.html` / `stock.html` / `theme-momentum.html` 是舊的多頁版本,沒有列在 `vite.config.ts` 的 build input 裡,現行 SPA 不走它們,因此不處理。

### Hash 路由回報

`src/lib/clarity.ts` 監聽 `hashchange`,在路由變化時呼叫 Clarity 的 API 標記目前頁面,讓後台能分辨「題材雷達 / 題材動能 / 資金流向 / 個股 / 源狀態」。沒有這一段,所有流量會被記成同一頁。

### 隱私

站台無登入、無表單,PII 風險趨近於零。Clarity 預設遮罩輸入欄位。資料會送給微軟,README 加一行說明。

---

## 二、訪客計數器

### 資料流

```
瀏覽器(僅 index 頁)
   │  POST /functions/v1/pageview   { visitorId }
   ▼
Edge Function  ── 驗證 origin、依 IP 限流、伺服器端決定時間戳
   │
   ▼
site_metrics schema(私有,anon 零權限)
   │
   ▼
Edge Function GET → { total, online }
```

瀏覽器全程不持有任何資料庫憑證。Edge Function 是唯一的讀寫者。

**Function 以一般 Postgres 連線存取資料庫,不走 supabase-js。** 實作時先用了
supabase-js,結果每一次寫入都回 429:`site_metrics` 刻意不在 PostgREST 的
exposed schemas 裡,而 supabase-js 正是透過 PostgREST 溝通,查詢因此永遠失敗,
再被限流器的 fail-closed 分支變成「已達上限」。修法有兩條 —— 把 schema 公開給
PostgREST,或改用直連 —— 選後者,因為前者會把刻意關上的 REST 表面重新打開。

### 名詞定義

**總瀏覽數(total)**
`page_view` 表的資料列總數。一次「造訪」寫一列,以 `localStorage` 中的 `visitor_id` 加上 **30 分鐘視窗**去重 — 同一訪客 30 分鐘內重新整理不會產生新列。這一條是實務上最主要的防灌水機制,因為最可能的灌水來源是維護者自己反覆整理頁面。

**目前線上(online)**
最近 **2 分鐘**內有心跳的不重複 `visitor_id` 數量。頁面在分頁可見時(`document.visibilityState === 'visible'`)每 **45 秒**送一次心跳;背景分頁停止心跳,因此開著整夜的分頁會正確地退出「線上」。

心跳寫入獨立的表,不寫 `page_view`,否則心跳會灌爆總數。

心跳表以 `visitor_id` 為主鍵、每次心跳 upsert 更新時間戳,因此每個訪客最多佔一列,不會無限成長。`rate_limit` 表同理,在 Edge Function 每次寫入時順手刪除超過視窗的舊列。兩者都不需要額外的排程清理工作。

### 計數範圍

**只有 index 頁計數。** 其他路由不寫入。這是使用者明確要求的範圍,也讓寫入點收斂成單一呼叫位置。

### 防灌水

四層,全部在 Edge Function 內:

1. **Origin 允許清單** — 拒絕 `Origin` 不是 Pages 網域的請求。腳本可偽造,但能擋掉其他站台嵌入這個端點。
2. **依 IP 限流** — 每 IP 每分鐘最多 20 次寫入(含 page view 與心跳),以伺服器端時間戳記錄在小表中。超過即回 429。**這是真正有效的一層**,因為 Function 看得到真實 IP,而客戶端無法偽造。
3. **伺服器端時間戳** — 客戶端從不送時間。無法回填過去或偽造未來。
4. **Payload 驗證** — `visitor_id` 必須符合嚴格 UUID 格式,其餘一律拒絕。沒有自由文字欄位,無注入面。

讀取只回傳彙總值 `{ total, online }` 兩個整數,永不暴露原始資料列,因此端點雖然公開也不洩漏訪客資訊。

### 誠實的限制

`localStorage` 可清除,`visitor_id` 由客戶端產生,決心足夠的人可以輪替 ID、搭配輪替 IP 來灌水。本設計的目標上限是**擋掉隨手灌水**(開 devtools 迴圈 fetch、狂按重新整理),不是防禦協同攻擊。這是與使用者確認過的取捨。

### 已接受的風險

- **Supabase project ref 會公開**。Edge Function 網址包含 project ref,而該網址必然出現在公開前端 JS。repo 的 `.gitignore` 原先刻意讓含此 ref 的文件不進版控。此設計推翻該選擇。技術上 ref 不是憑證 — 沒有 key 時知道 ref 什麼也做不了,且資料表對 anon 零權限。使用者已明確同意。
- **既有 preview 專案將承接公開流量**。計數器使用獨立 schema 與獨立角色,計數器的錯誤無法影響動能歷史資料。使用者已確認沿用現有專案。

---

## 三、元件

| 檔案 | 職責 |
|---|---|
| `supabase/migrations/<ts>_create_site_metrics.sql` | `site_metrics` schema、`page_view` / `heartbeat` / `rate_limit` 三表、角色、授權、CHECK constraint |
| `supabase/functions/pageview/index.ts` | 唯一讀寫者;驗證與限流 |
| `src/services/metricsService.ts` | `recordPageView()` / `sendHeartbeat()` / `fetchCounts()`,純 fetch 包裝,不含 React |
| `src/hooks/useSiteMetrics.ts` | 心跳計時器、分頁可見性處理、輪詢、清理 |
| `src/components/common/StatusBar.tsx` | (修改)顯示兩個數字 |
| `src/lib/clarity.ts` | Clarity 初始化與 hash 路由回報 |
| `index.html` | (修改)Clarity snippet |

### 邊界

`metricsService` 不知道 React 的存在,只負責 HTTP。`useSiteMetrics` 不知道 HTTP 細節,只負責生命週期。`StatusBar` 只負責畫面。三者可以各自替換而不影響彼此。

---

## 四、錯誤處理

**分析功能絕不能弄壞雷達本身。**

端點無回應、逾時或回傳錯誤時,計數器顯示 `—`,頁面其餘部分完全不受影響。不拋出未捕捉的錯誤,不在 render 路徑上阻塞 await。Clarity snippet 載入失敗同理 — 站台照常運作。

## 五、測試

依這個功能的實際份量調整深度:

- **SQL constraint** — 由 migration 套用驗證,沿用既有 migration 的重 constraint 風格。
- **Edge Function** — 對驗證與限流邏輯寫單元測試(拒絕格式錯誤的 UUID、拒絕超過限流、拒絕錯誤 origin)。這是錯了會安靜失敗且代價高的部分,值得真正的測試。
- **`metricsService`** — 以 mock `fetch` 測試,包含失敗路徑。
- **不寫 E2E** — 這是訪客計數器,不是交易路徑。

## 六、實作前置

1. Clarity project ID — 已取得(`xz7wk63q2s`)
2. `supabase login` — 待使用者於本機執行,token 不進對話紀錄
