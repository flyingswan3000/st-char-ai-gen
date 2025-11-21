# SillyTavern 角色卡產生器

一個將雜訊/舊版 SillyTavern 資料轉換為可匯入 JSON 的小型網站。前端為純 HTML + Tailwind，後端採 FastAPI，呼叫 OpenAI 或 Grok(xAI) 的 LLM 生成關鍵欄位，再依 SillyTavern 角色卡格式組裝完整卡片。

## 功能概要

- 貼上或上傳文字/JSON 後，一鍵產生可直接匯入 SillyTavern 的角色卡。
- 前端可選擇 OpenAI 或 Grok；後端可透過環境變數設定模型、API Base URL。
- LLM 僅輸出關鍵欄位，伺服器端再組裝 JSON，避免 LLM 出現多餘 markdown。
- Streaming 模式，可在 console 看到 LLM 即時回傳內容（亦可透過環境變數關閉）。
- 送出請求後會建立背景任務並跳轉至任務頁面，透過 SSE 串流顯示 LLM 回傳內容，完成後可直接下載結果。
- 支援 CCv3 PNG/APNG 內嵌：可上傳含 `ccv3` chunk 的圖片作為輸入（會自動解析），輸出時也能下載內嵌角色卡的 PNG，若原始圖片不存在則套用預設圖片。

## 環境變數

請參考 `.env.example`，主要包含：

```text
OPENAI_API_KEY / OPENAI_MODEL / OPENAI_BASE_URL
XAI_API_KEY / XAI_MODEL / XAI_BASE_URL        # xAI Grok
LLM_TIMEOUT                                    # 預設 300 秒
STREAM_CONSOLE_ENABLED / STREAM_BUFFER_CHARS   # console streaming 開關
```

## 開發模式（本機）

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 填入實際 API key
uvicorn app.main:app --reload
```

瀏覽 `http://localhost:8000` 即可。

## Docker

### 建置映像

```bash
docker build -t tavern-card:latest .
```

### 執行容器

```bash
docker run -it --rm \
  -p 8000:8000 \
  --env-file .env \
  tavern-card:latest
```

### 使用 docker compose

```bash
cp .env.example .env
docker compose up --build
```

如需修改外部對應 port，可在 `docker-compose.yml` 的 `ports` 區塊調整，例如 `- "8001:8000"`。

## 跨平台建置 (x86_64 / amd64)

若在 Apple Silicon（arm64）上需要建置 x86_64 版映像，可使用 Buildx：

```bash
docker buildx build --platform linux/amd64 -t tavern-card:latest --output type=docker,dest=- . | gzip > tavern-card-amd64.tar.gz

```

## 注意事項

- 目前 Grok (xAI) 走官方 API 流程，預設模型為 `grok-3`；若 API 尚未開通請改用 OpenAI。
- Streaming console 可透過 `.env` 的 `STREAM_CONSOLE_ENABLED=false` 關閉，以避免佔用部署日誌。
- 產生的 JSON 會附帶 `spec: "chara_card_v3"`、`spec_version: "3.0"`，並套用標準的外層欄位結構，可直接拖入 SillyTavern。

## 背景任務流程與 API

- 前端改為呼叫 `POST /api/jobs` 建立任務，伺服器會回傳唯一 `job_id` 並立刻啟動背景任務呼叫 LLM，接著導向 `/job.html?id=...` 觀察狀態。
- 任務頁面會定期取得 `/api/jobs/{job_id}` 的詳細資訊，並透過 `GET /api/jobs/{job_id}/stream`（Server-Sent Events）即時顯示 LLM 輸出，完成時可下載 `/api/jobs/{job_id}/download`。
- `GET /api/jobs` 會列出所有進行中與已完成的任務；首頁亦提供快速列表檢視。
- 伺服器會在 `./tmp/jobs` 建立暫存資料夾，包含原始輸入、串流輸出、meta 與結果檔案，僅保留最近 10 筆已完成任務（進行中任務不會刪除），以節省儲存空間。
- 若上傳 PNG/APNG，會同步在暫存資料夾保存底圖，成功產生角色卡後即可使用 `/api/jobs/{job_id}/download.png` 下載已嵌入 `ccv3` chunk 的 PNG；若未提供圖片則使用 `app/assets/default_card.png`。
