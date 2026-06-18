# Query Vehicles

一個用來批次查詢車牌資訊的 Python 專案。

此工具會讀取 CSV / Excel / TXT 的車牌資料，透過 Playwright 自動查詢 `vehicleinfo.app`，解析車型後判斷是否為二/三輪車，並輸出包含原始欄位的結果檔。

## 功能特色

- 支援輸入格式：`.txt`、`.csv`、`.xlsx`、`.xls`
- 保留原始資料欄位，並新增：`vehicle_model`、`is_target`
- 車牌去重查詢，避免重複請求加速處理
- 多執行緒平行查詢（可設定 `THREADS`）
- checkpoint 斷點續跑（中斷後可接續）
- 執行完成後輸出分類統計與耗時
- CSV 輸出使用 `QUOTE_ALL`，避免車型名稱含逗號造成欄位錯位

## 專案目錄

```text
Query_vehicles/
├── src/       # 主程式（query_vehicles.py）
├── input/     # 輸入檔案
├── output/    # 輸出結果
├── temp/      # checkpoint 暫存
├── archive/   # 歷史壓縮檔或封存資料
└── docs/      # 變更紀錄與測試文件
```

## 執行環境

- Python 3.9+
- Windows / macOS / Linux（目前主要在 Windows 使用）

## 安裝步驟

1. 安裝 Python 套件：

```bash
pip install pandas openpyxl playwright playwright-stealth
```

2. 安裝 Playwright 瀏覽器：

```bash
playwright install chromium
```

## 使用方式

1. 將輸入檔放到 `input/` 資料夾。
2. 編輯 `src/query_vehicles.py` 的設定區：

```python
INPUT_FILE = "your_input_file.csv"  # 只填檔名
PLATE_COL  = "Plate_1st_Recong"
DELAY_SEC  = 2.0
THREADS    = 5
```

3. 在專案根目錄執行：

```bash
python src/query_vehicles.py
```

## 輸出說明

程式會在 `output/` 產生：

- `<原始檔名>_result.csv`

新增欄位：

- `vehicle_model`：查詢到的車型名稱
- `is_target`：分類結果
  - `是`：二/三輪車
  - `否`：四輪以上
  - `無資料`：查詢頁面沒有可用車型
  - `車牌無效`：空白、NULL、N/A、全 0 等無效值
  - `查詢失敗`：連線或超時等例外

## 斷點續跑機制

- 進行查詢時，會在 `temp/` 產生 `<原始檔名>_checkpoint.json`。
- 程式中斷後再次執行，會自動讀取 checkpoint，跳過已查詢車牌。
- 全部完成後，checkpoint 會自動刪除。

## 注意事項

- `THREADS` 越高不一定越快，可能提高被目標網站限制的風險。
- 建議 `THREADS = 3~5`、`DELAY_SEC = 1.5~3.0` 依實際情況調整。
- 若更換輸入檔，請確認 `PLATE_COL` 欄位名稱正確。

