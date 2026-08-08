<div align="center">

# Taiwan Equity Theme Radar

## 台股題材雷達｜Theme → Symbol 靜態雷達

**每小時把公開新聞整理成台股題材熱度與候選股映射，全部產出靜態 JSON，前端直接讀，沒有後端伺服器。**

[![Live](https://img.shields.io/badge/Live-a898954139.github.io-green?style=flat-square)](https://a898954139.github.io/nexus-theme-radar/)
[![Actions](https://img.shields.io/github/actions/workflow/status/a898954139/nexus-theme-radar/update-theme-radar.yml?branch=master&label=radar&style=flat-square)](https://github.com/a898954139/nexus-theme-radar/actions/workflows/update-theme-radar.yml)
[![License](https://img.shields.io/badge/license-MIT-green.svg?style=flat-square)](LICENSE)

**線上站** → [a898954139.github.io/nexus-theme-radar](https://a898954139.github.io/nexus-theme-radar/)

[信息源策略](docs/SOURCE_COVERAGE.md) · [MVP 架構](docs/MVP_ARCHITECTURE.md) · [伯樂 Skill](skills/ai-news-radar/README.md)

</div>

> 本專案 fork 自 [LearnPrompt/ai-news-radar](https://github.com/LearnPrompt/ai-news-radar)，
> 保留它的靜態站、GitHub Actions 與 JSON pipeline 架構，把 AI relevance layer
> 改造成台股題材判定與候選股映射。上游那套 AI 日報功能（persona 銳評、
> 伯樂精選、雙視圖）的說明見上游 repo，本文只描述台股雷達這條線。

---

## 這是什麼

一條每小時跑一次的資料管線，做四件事：

1. **抓公開新聞** → RSS/OPML、官方 feed、公開頁面
2. **判定台股題材** → 用 `config/theme_taxonomy.tw.json` 比對關鍵詞與股票代號
3. **映射候選股** → 產出 theme → symbol 的關聯與熱度／動能分數
4. **發布靜態站** → GitHub Actions 產 JSON、建置前端、部署到 GitHub Pages

不需要 API Key、不需要登入態、不需要伺服器。

### 五個畫面

| 畫面 | 內容 |
|---|---|
| **題材雷達** | 當前題材熱度排行、代表新聞、關聯個股 |
| **題材動能** | 熱度與動能的歷史走勢（24h / 72h / 7d） |
| **資金流向** | 三大法人買賣超排行，雷達題材個股交叉標記 |
| **個股** | 基本面分析 + 三大法人資金流向 |
| **源狀態** | 各來源抓取成功率與健康度 |

---

## 資料產物

前端只讀這些檔案，`deploy-pages.yml` 會把它們複製進 `dist/data/`：

| 檔案 | 內容 |
|---|---|
| `public-theme-ranking-v0.8.json` | 題材熱度排行 |
| `public-theme-momentum-latest-v0.9.json` | 最新一小時的動能快照 |
| `public-theme-momentum-history-v0.9.json` | 動能歷史（保留 720 小時） |
| `theme-events.json` | 題材事件與代表新聞 |
| `theme-symbol-fundamentals.json` | 個股季度財報與解讀 |
| `institutional-flows.json` | 個股逐日三大法人流向 |
| `institutional-rankings.json` | 資金流向排行榜 |
| `source-status.json` | 來源抓取狀態與健康度 |
| `waytoagi-7d.json` | 7 天熱榜池 |

**新增前端要讀的 JSON 時，記得同步加進 `deploy-pages.yml` 的 `Copy runtime data` 步驟**，
否則本機看得到、線上 404。

---

## GitHub Actions

四個 workflow，全部可以在 Actions 頁手動觸發：

| Workflow | 排程 | 做什麼 |
|---|---|---|
| [`update-theme-radar.yml`](.github/workflows/update-theme-radar.yml) | 每小時 `17 * * * *` | 抓新聞、算題材熱度與動能、寫歷史、發布 |
| [`update-institutional-flows.yml`](.github/workflows/update-institutional-flows.yml) | 交易日 `20 9 * * 1-5`（台北 17:20） | 抓三大法人買賣超、更新排行、發布 |
| [`backfill-fundamentals.yml`](.github/workflows/backfill-fundamentals.yml) | 手動 | 每季財報公布後抓全部 symbol 的財報 |
| [`deploy-pages.yml`](.github/workflows/deploy-pages.yml) | `push` / 被呼叫 | 建置 `dist/` 並部署到 GitHub Pages |

### ⚠️ 資料 workflow 必須自己呼叫部署

**用 `GITHUB_TOKEN` 推的 commit 不會觸發 `on: push`** —— 這是 GitHub 防止
workflow 互相觸發的明文設計。兩個資料 workflow 都以 `github-actions[bot]`
身分 commit，所以它們**不能靠 push 事件把資料送上線**。

因此 `deploy-pages.yml` 開放 `workflow_call`，兩個資料 workflow 在 commit 步驟
之後各有一個 `publish` job 直接呼叫它：

```yaml
publish:
  needs: update
  permissions:
    contents: read
    pages: write        # reusable workflow 不繼承權限，每個 caller 要自己給
    id-token: write
  uses: ./.github/workflows/deploy-pages.yml
```

**新增任何會 commit `data/` 的 workflow 時，一定要照這個模式接上部署**，
否則資料會停在 master、網站永遠是舊的 —— 而且三個 Action 全都會顯示綠燈。
`tests/test_update_theme_radar.py` 有測試綁住這條規則。

### 動能歷史需要資料庫

題材動能的歷史走勢存在 Postgres（`theme_radar.hourly_theme_heat`），
由 `THEME_RADAR_DATABASE_URL` secret 提供連線。**沒設就自動降級**：
最新排行照常運作，只有走勢圖顯示「等待歷史資料」。

授權是 opt-in 的，需要同時設定：

| 名稱 | 類型 | 值 |
|---|---|---|
| `THEME_RADAR_DATABASE_URL` | Secret | 直連 Postgres 的連線字串（建議用 Session pooler） |
| `THEME_RADAR_DB_HISTORY_AUTHORIZED_ENVIRONMENT` | Variable | `production` |
| `THEME_RADAR_DB_HISTORY_AUTHORIZED_BRANCH` | Variable | `master` |

三者缺一，憑證就解析為空字串，管線 fail closed 不寫資料庫。
Schema 見 [`supabase/migrations/`](supabase/migrations/)。

建議建一個**最小權限的登入角色**而不是用 postgres 超級使用者 ——
只 grant `theme_radar_writer` 與 `theme_radar_materializer`，
把爆破半徑限制在那一張表。

---

## 本地開發

### 資料管線

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python scripts/update_theme_radar.py \
  --output-dir data --window-hours 72 --max-events 500 --max-candidates 200
```

也可以產 deterministic sample data 供測試：

```bash
python scripts/generate_theme_demo.py --output-dir data --window-hours 48
```

### 前端

Nexus 暗色金融介面，React + TypeScript + Vite：

```bash
npm ci
npm run dev     # http://127.0.0.1:5173/
npm run build   # production build
```

前端不需要額外 backend server，資料一樣從 `data/` 的 JSON 讀。

### 測試

```bash
.venv/bin/python -m pytest tests/ -q
```

---

## 每季要做的事

財報申報截止日（3/31、5/15、8/14、11/14）過後：

1. **Actions → `Backfill Symbol Fundamentals` → Run workflow**
   （季度節流會自動跳過已抓過的，重跑不會重複請求）

2. **補財報解讀**（需要模型，無法在 Action 內完成）：

   ```bash
   .venv/bin/python scripts/generate_fundamental_commentary.py --emit-prompts /tmp/p
   # 逐檔讀 prompt、寫解讀、存成 /tmp/p/<代號>.json
   .venv/bin/python scripts/generate_fundamental_commentary.py --collect /tmp/p
   ```

   解讀的季度與財報季度不符時前端**不會渲染** —— 舊評論配新數字比沒有評論更糟。

---

## Fork 指南

1. **Fork** 本 repo
2. **開 Actions**：fork 後 GitHub 預設暫停 workflow，去 Actions 頁點一下啟用
3. **開 GitHub Pages**：Settings → Pages → Source 選 **GitHub Actions**（不是分支）
4. **改題材設定**：編輯 [`config/theme_taxonomy.tw.json`](config/theme_taxonomy.tw.json)
   換成你關心的題材與關鍵詞，個股代號對照在
   [`config/symbol_aliases.tw.json`](config/symbol_aliases.tw.json)
5. **（可選）接資料庫**：照上面那三個 secret/variable 設定，動能走勢才會累積

想換信源：把訂閱寫進 `feeds/follow.opml`（參考 `feeds/follow.example.opml`，
**不要提交這個檔案**），或用內建的[伯樂 Skill](skills/ai-news-radar/README.md)
幫你判斷與錄入。

---

## 安全

這個 repo 是公開的。**不要提交**私有 OPML、API key、cookies、瀏覽器匯出檔或
`.env` 值。`.gitignore` 已擋掉常見的洩漏路徑（含 `supabase/.temp/`，
`supabase link` 會在那裡寫下 project ref 與 pooler URL）。

資料庫憑證只放 GitHub Secrets。設定時用互動式輸入或 stdin 導入，
**不要用 `gh secret set X -b "<值>"`** —— 那會把密碼留在 shell history。

`tests/` 內有幾個測試專門守這條線，會檢查前端資產與 workflow 裡不出現
`service_role`、連線字串或 DB 密碼。

---

## 疑難排解

**網站資料是舊的，但 Actions 都綠燈？**
先比對 repo 與線上檔案，最快：

```bash
git show origin/master:data/public-theme-momentum-history-v0.9.json | head -20
curl -s "https://<你的站>/data/public-theme-momentum-history-v0.9.json?cb=$(date +%s)" | head -20
```

兩者不同就是部署沒跑到 —— 檢查該 workflow 有沒有接上 `publish` job。

**動能走勢顯示「等待歷史資料」？**
表示 `public-theme-momentum-history-v0.9.json` 的 `observations` 是空的。
折線圖至少要 2 個點才看得出走勢，而歷史只有在資料庫接上後才會累積 ——
先確認上面三個 secret/variable 都設好，再看 workflow log 裡的
`history_rows_upserted` 是不是大於 0。

> 註：`assets/` 下還有一套 pre-Nexus 的原生 JS 頁面（`theme-momentum.js` 等），
> 它有額外的 2 小時新鮮度門檻與 2 筆觀測下限。**這套已不在部署範圍內**
> （`vite.config.ts` 只建置 `src/` 的 React SPA），排查時不要看錯檔案。

---

## 致謝

- [LearnPrompt/ai-news-radar](https://github.com/LearnPrompt/ai-news-radar)：本專案的上游架構
- [superpowers](https://github.com/obra/superpowers)：skill 工程方法論來源

## License

[MIT](LICENSE)
