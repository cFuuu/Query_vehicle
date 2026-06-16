# query_vehicles.py 變更紀錄

## v1.0 — 初始版本

**功能**：
- 從 `Manual_VC.txt` 讀取車牌號碼（支援多種編碼）
- 使用 Playwright + stealth 查詢 `vehicleinfo.app`
- 判斷車型為二/三輪車（`是`）或四輪以上（`否`）
- 輸出至 `Manual_VC.csv`，欄位：`plate`、`vehicle_model`、`is_target`

**分類關鍵字邏輯**：
- 先比對二/三輪關鍵字（優先），避免 `bajaj cargo` 被 `car` 誤攔
- `\bcar\b`、`\bvan\b` 使用 word-boundary 正規表示式比對，防止誤中 `cargo`、`carrier`

---

## v1.1 — 改為讀取 Excel，保留原始欄位

**變更原因**：使用者輸入資料為 Excel，包含多個原始欄位需保留。

**變更內容**：
- 輸入改為 `Manual_VC.xlsx`（使用 `pandas.read_excel`）
- 新增 `PLATE_COL = "Plate_1st_Recong"` 設定車牌欄位名稱
- 輸出保留所有原始欄位，`vehicle_model`、`is_target` 附加在最後
- 空車牌回傳 `無車牌` 而非查詢失敗

---

## v1.2 — 物件導向重構 + 自動識別檔案格式

**變更原因**：使用者要求物件導向架構，並支援 txt、csv、xlsx 多種格式。

**新增類別**：

| 類別 | 職責 |
|------|------|
| `FileReader` | 自動依副檔名讀取 `.txt` / `.csv` / `.xlsx` / `.xls` |
| `VehicleClassifier` | 判斷車型（關鍵字清單移入類別屬性） |
| `PageParser` | 解析 vehicleinfo.app 頁面文字取出車型名稱 |
| `VehicleQueryRunner` | 主控制器，整合讀檔、查詢、分類、寫出 |

**設定區移至程式頂端**：
```python
INPUT_FILE  = "..."   # 只需改這裡
OUTPUT_FILE = "..."
PLATE_COL   = "Plate_1st_Recong"
DELAY_SEC   = 3.0
```

---

## v1.3 — 輸出欄位插入位置調整 + 自動命名輸出檔

**變更原因**：使用者要求 `vehicle_model`、`is_target` 插入在 `Plate_1st_Recong` 欄位正後方。

**變更內容**：
- 移除硬編碼 `OUTPUT_FILE`，改為自動產生：`原檔名_result.csv`
- 輸出欄位順序：`...原始欄位...Plate_1st_Recong | vehicle_model | is_target | 後續欄位...`
- 原始輸入檔完全不動

---

## v1.4 — 去重查詢（方案 C）+ 無效車牌防呆

**變更原因**：14,047 筆資料含大量重複車牌，逐筆查詢耗時過長（~9 小時）。

**變更內容**：
- 先掃描所有記錄，收集**不重複的有效車牌**
- 只對唯一車牌發出查詢，結果存入 `cache`
- 查詢完成後一次性回填所有記錄
- 新增無效車牌判斷（`INVALID_PLATES`），以下內容自動標記為 `跳過`：
  - 空白、`0`、`00`、`000000`、`NULL`、`None`、`N/A`、`-`

**效果**：10,992 有效車牌 → 去重後約 10,050 唯一車牌，節省重複查詢時間。

---

## v1.5 — 多執行緒平行查詢（5 threads）

**變更原因**：使用者要求進一步加速，單一執行緒預估約 7 小時。

**變更內容**：
- 新增 `THREADS = 5` 設定
- 引入 `threading`、`concurrent.futures.ThreadPoolExecutor`
- 唯一車牌清單平均分配給 5 個 thread
- 每個 thread **獨立啟動自己的瀏覽器**（Playwright 不支援跨 thread 共用）
- 使用 `threading.Lock` 保護 `cache` 寫入與進度計數

**速度對比**：

| 設定 | 預估時間 |
|------|---------|
| v1.4（1 thread，3秒） | ~8.5 小時 |
| v1.5（5 threads，2秒） | ~55 分鐘 |

---

## 設定區參數說明（目前版本）

| 參數 | 說明 | 預設值 |
|------|------|-------|
| `INPUT_FILE` | 輸入檔名（只填檔名，檔案需放在 input/ 資料夾） | 依使用者修改 |
| `PLATE_COL` | 車牌欄位名稱（txt 模式忽略） | `Plate_1st_Recong` |
| `DELAY_SEC` | 每筆查詢間隔秒數（每個 thread 各自等待） | `2.0` |
| `THREADS` | 平行查詢 thread 數量（建議 3~5） | `3` |

---

## v1.6 — 專案目錄結構重整

**變更原因**：所有檔案堆在根目錄，難以管理。

**變更內容**：
- 建立正式目錄結構：
  ```
  Query_vehicles/
  ├── src/          ← 主程式（query_vehicles.py）
  ├── input/        ← 放置輸入 CSV/Excel 檔案
  ├── output/       ← 自動輸出 _result.csv
  ├── temp/         ← checkpoint JSON 暫存
  ├── archive/      ← 歸檔舊資料
  └── docs/         ← 文件（CHANGELOG、TEST_SCRIPT）
  ```
- `BASE_DIR` 以 `__file__` 自動推算專案根目錄，不依賴工作目錄
- `INPUT_FILE` 只需填檔名，系統自動對應 `input/` 資料夾
- `OUTPUT_DIR.mkdir` / `TEMP_DIR.mkdir` 確保目錄不存在時自動建立
- 移除舊版相對路徑邏輯（`src.parent / ...`）

---

## 輸出欄位

| 欄位 | 說明 |
|------|------|
| `vehicle_model` | 從網站查到的車型名稱 |
| `is_target` | `是`（二/三輪）/ `否`（四輪以上）/ `無資料` / `車牌無效` / `查詢失敗` |
