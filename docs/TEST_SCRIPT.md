# 測試腳本紀錄

## 環境前置

```powershell
# 啟用 conda sv 環境
conda activate sv
Set-Location "C:\Users\harry\Project\Query_vehicles"
```

---

## 測試 1：確認所有模組是否已安裝

```powershell
python -c "import playwright; import playwright_stealth; import pandas; import openpyxl; print('全部模組已安裝')"
```

**結果**：`playwright_stealth` 未安裝 → 執行安裝

```powershell
pip install playwright-stealth
```

安裝後再次確認，全部模組正常。

---

## 測試 2：預覽 CSV 有效車牌

```python
import pandas as pd
df = pd.read_csv('20260510-0610_G-S-P_AVC8 list.csv', dtype=str).fillna('')
plates = [str(r.get('Plate_1st_Recong','')).strip().upper().replace(' ','') for r in df.to_dict(orient='records')]
valid = [p for p in plates if p and p not in ('0','000000','NULL')][:5]
print('測試車牌：', valid)
```

**結果**：
```
測試車牌： ['HR67E6594', 'DL3CCV2603', 'HR06AP1964', 'DL13CA3479', 'HR51AV8597']
```

---

## 測試 3：單筆查詢（單一瀏覽器）

對 `HR67E6594`、`DL3CCV2603` 發出實際查詢：

```python
import re
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

plates = ['HR67E6594', 'DL3CCV2603']

def extract_model(content, plate):
    lines = [l.strip() for l in content.split('\n') if l.strip()]
    count = 0
    for j, line in enumerate(lines):
        if line.upper() == plate.upper():
            count += 1
            if count == 2 and j + 1 < len(lines):
                c = lines[j+1]
                if not re.match(r'^[A-Z\*\s]{1,5}$', c):
                    return c
    for j, line in enumerate(lines):
        if line.upper() == plate.upper():
            for k in range(j+1, min(j+5, len(lines))):
                if lines[k].upper() not in ('CHANGE', plate.upper()) and re.search(r'[A-Z]{2,}', lines[k]):
                    return lines[k]
            break
    return ''

stealth = Stealth()
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        viewport={'width':1280,'height':800}, locale='en-IN')
    page = ctx.new_page()
    stealth.apply_stealth_sync(page)
    for plate in plates:
        try:
            page.goto(f'https://vehicleinfo.app/rc-details/{plate}?rc_no={plate}',
                      wait_until='networkidle', timeout=30000)
            page.wait_for_timeout(2000)
            model = extract_model(page.inner_text('body'), plate)
            print(f'{plate} => [{model}]')
        except Exception as e:
            print(f'{plate} => ERROR: {e}')
    browser.close()
```

**結果**：
```
HR67E6594 => [BAJAJ, BAJAJ RE CNG 4S FI]
```

---

## 測試 4：統計檔案筆數與預估時間

```python
import pandas as pd
df = pd.read_csv('20260510-0610_G-S-P_AVC8 list.csv', dtype=str).fillna('')
total = len(df)
valid = df['Plate_1st_Recong'].str.strip().replace('', None).dropna()
valid = valid[~valid.isin(['0','000000','NULL'])]
print(f'總筆數：{total}')
print(f'有效車牌：{len(valid)}')
print(f'預估時間（3秒/筆）：{len(valid)*3/60:.1f} 分鐘')
print(f'預估時間（5秒/筆）：{len(valid)*5/60:.1f} 分鐘（含網路延遲）')
```

**結果**：
```
總筆數：14047
有效車牌：10992
預估時間（3秒/筆）：549.6 分鐘
預估時間（5秒/筆）：916.0 分鐘（含網路延遲）
```

---

## 測試 5：正式執行主程式（5 threads）

```powershell
& "C:\Users\harry\anaconda3\envs\sv\python.exe" query_vehicles.py
```

**啟動輸出**：
```
讀取檔案：20260510-0610_G_AVC8 list .csv
總筆數：14047  │  無效/跳過：3055  │  不重複車牌：10050
預估查詢時間：約 335 分鐘

啟動 5 個平行查詢 thread...

[  1/10050] PB10DP5667         | OTHERS, WAGON R LXI BS4             | 否
[  2/10050] HR589563           | KERALA AUTOMOBILES LTD, KAL AUTO 325 | 否
[  3/10050] HR01AW0909         | KIA INDIA PRIVATE LIMITED, SELTOS D1.5 6AT X LINE | 否
[  4/10050] PB01D8903          | TOYOTA KIRLOSKAR MOTOR PVT LTD, INNOVA HYCROSS HYBRID VX(8S) | 否
[  5/10050] HR67E6594          | BAJAJ, BAJAJ RE CNG 4S FI           | 是 ✅
```

**結論**：5 threads 正常平行啟動，查詢結果正確，無 bug。

---

## 注意事項

| 項目 | 說明 |
|------|------|
| Python 路徑 | 需使用 `conda activate sv` 或完整路徑 `C:\Users\harry\anaconda3\envs\sv\python.exe` |
| `python` 指令 | 在 PowerShell 中若顯示找不到，改用完整路徑執行 |
| 被封偵測 | 大量 `查詢失敗` 出現時，降低 `THREADS` 至 3，並增加 `DELAY_SEC` |
