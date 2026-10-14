# 116 學年度臺大／東吳法研所考試入學監測

每天 **臺灣時間 09:00** 使用 GitHub Actions 執行。只監測「碩士班考試入學／一般入學考試」，**不含甄試入學**。有新公告或連結變動才寄 Gmail 通知；失敗亦通知。GitHub Actions 的 schedule 可能延後執行，不是精確秒級排程。

## 監測清單
- 臺大碩士班一般入學考試：https://www.aca.ntu.edu.tw/w/aca/LocalAdmissionClass_21072014071675661
- 臺大碩士班考試系統：https://exam.aca.ntu.edu.tw/grab/
- 臺大共同簡章：https://exam.aca.ntu.edu.tw/grab/Brochure/main
- 臺大法律學系各組：https://exam.aca.ntu.edu.tw/grab/Brochure/detail.aspx
- 東吳碩士班考試公告：https://entrance.exam.scu.edu.tw/news/碩博士學位招生/碩士班考試

## GitHub 雲端部署（建議）
1. 建立 **Private** GitHub repository，例如 `law-admissions-monitor`。
2. 把專案所有檔案、包含 `.github/workflows/daily.yml` 上傳到儲存庫**根目錄**；注意 `.github` 是隱藏資料夾。
3. Google 帳號開啟兩步驟驗證，在 Google Account → Security → App passwords 產生專用的 16 字元應用程式密碼。某些 Workspace/安全限制帳號無法使用 App passwords，須改用支援的 SMTP 方案。不要使用一般 Gmail 登入密碼。
4. GitHub repository → Settings → Secrets and variables → Actions → New repository secret，新增：
   - `SMTP_USER`：寄件 Gmail 地址
   - `SMTP_APP_PASSWORD`：Gmail 應用程式密碼（可直接貼 16 字元）
   - `EMAIL_TO`：收件 Email；多人用逗號分隔
5. repository → Settings → Actions → General → Workflow permissions → 選取 **Read and write permissions**（若選項不可用請管理員調整）。
6. Actions → `Daily law admissions monitor` → `Run workflow` → `test_email=true` → Run，應收到測試信。
7. 再手動執行一次 `test_email=false`，這會建立初始基準，不會把現有舊公告全部寄出；如有網站讀取錯誤，會發警示信。
8. 確認 `state.json` 有自動提交的新內容。之後每天 09:00（台灣時間）自動執行。

> GitHub 排程通常只在 default branch 生效。repository 休眠、平台尖峰或 GitHub 政策可能延後/停止排程；可定期在 Actions 查看執行紀錄。

## 本機測試
```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python monitor.py --dry-run
```

寄信測試（環境變數請先自行設定，不要寫入 Git）：
```bash
export SMTP_USER='sender@gmail.com'
export SMTP_APP_PASSWORD='16characterapppassword'
export EMAIL_TO='recipient@example.com'
python monitor.py --test-email
```

## 通知與狀態規則
- 第一次成功讀取的來源只建立 baseline，不發歷史公告通知。
- 新公告、新 PDF 連結、公告摘要文字異動會通知；不監測 PDF 檔案內容位元變化（同 URL 覆蓋檔案可能無法察覺）。
- 網站抓取失敗會寄異常通知並讓 Action 顯示失敗，下一天繼續嘗試；SMTP 發送失敗時不覆寫狀態。
- 網站改版、反爬蟲、JS 動態渲染時可能漏檢，務必以官方頁面確認報名截止時間。
- 轉換監測年度：改 workflow 中的 `ADMISSION_YEAR`，清空 `state.json` 為 `{}` 後重新建立 baseline。

## 安全
- 只使用公開官網頁面，不涉及帳號登入或自動報名。
- SMTP 密碼只保存在 GitHub Secrets；絕不可提交到 repository 或截圖分享。
