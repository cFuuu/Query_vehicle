#!/usr/bin/env python3
# =============================================================================
#  設定區（修改這裡即可）
# =============================================================================
INPUT_FILE  = "G_06-03~06-17_V2.csv"  # 只填檔名，檔案需放在 input/ 資料夾
# OUTPUT_FILE 會自動命名為「原檔名_result.csv」，不需手動設定
PLATE_COL   = "Final_License_Plate_Number"      # Excel/CSV 中車牌所在欄位名稱（txt 模式忽略）
DELAY_SEC   = 2.0                      # 每筆查詢間隔秒數（每個 thread 各自等待）
THREADS     = 5                        # 平行查詢數量（建議 3~5，過高有被封風險）
# =============================================================================

import csv, time, re, math, threading, json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

# 專案根目錄（src/ 的上層）
BASE_DIR   = Path(__file__).parent.parent
INPUT_DIR  = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
TEMP_DIR   = BASE_DIR / "temp"


# ---------------------------------------------------------------------------
# 1. 檔案讀取器
# ---------------------------------------------------------------------------
class FileReader:
    """自動依副檔名讀取 txt / csv / xlsx / xls，統一回傳 (records, original_cols)"""

    def __init__(self, filepath: str, plate_col: str):
        self.path      = Path(filepath)
        self.plate_col = plate_col

    def read(self) -> tuple:
        suffix = self.path.suffix.lower()
        if suffix == ".txt":
            return self._read_txt()
        elif suffix == ".csv":
            return self._read_csv()
        elif suffix in (".xlsx", ".xls"):
            return self._read_excel()
        else:
            raise ValueError(f"不支援的檔案格式：{suffix}（支援 .txt / .csv / .xlsx / .xls）")

    def _read_txt(self) -> tuple:
        plates = []
        for enc in ("utf-8-sig", "utf-16", "utf-8", "cp950"):
            try:
                with open(self.path, encoding=enc) as f:
                    plates = [l.strip() for l in f if l.strip() and not l.startswith("#")]
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        records = [{self.plate_col: p} for p in plates]
        return records, [self.plate_col]

    def _read_csv(self) -> tuple:
        df = pd.read_csv(self.path, dtype=str, keep_default_na=False).fillna("")
        return df.to_dict(orient="records"), list(df.columns)

    def _read_excel(self) -> tuple:
        df = pd.read_excel(self.path, dtype=str, keep_default_na=False).fillna("")
        return df.to_dict(orient="records"), list(df.columns)


# ---------------------------------------------------------------------------
# 2. 車型分類器
# ---------------------------------------------------------------------------
class VehicleClassifier:
    """根據車型名稱判斷是否為二/三輪車"""

    FOUR_WHEEL_KEYWORDS = [
        "bus", "truck", "lorry", "tractor", "tanker", "tipper",
        "ambulance", "suv", "sedan", "hatchback", "mpv", "muv",
        "minivan", "minibus", "tempo traveller",
        "maruti", "hyundai", "tata indica", "tata nexon", "tata safari",
        "mahindra xuv", "mahindra bolero", "mahindra scorpio", "mahindra thar",
        "toyota", "honda city", "honda jazz", "honda amaze", "honda wrv",
        "ford", "renault", "nissan", "volkswagen", "skoda", "kia",
        "jeep", "mg ", "bmw", "mercedes", "audi", "volvo", "scania",
        "ashok leyland", "eicher", "bharatbenz", "isuzu",
        "force traveller", "force gurkha",
        "lmv", "hmv", "hgmv", "hpmv",
    ]

    # 需要 word-boundary 比對（避免 car 誤中 cargo/carrier）
    FOUR_WHEEL_EXACT_WORDS = [r"\bcar\b", r"\bvan\b"]

    TWO_THREE_WHEEL_KEYWORDS = [
        "bajaj", "tvs", "royal enfield", "piaggio", "ape",
        "hero", "honda activa", "honda dio", "honda shine", "honda cb",
        "honda sp", "honda unicorn", "honda hornet", "honda livo",
        "yamaha", "suzuki access", "suzuki gixxer", "suzuki burgman",
        "atul", "mahindra treo", "mahindra e-alfa", "mahindra alfa",
        "kranti automobiles", "mahindra last mile",
        "yatri", "hiload", "gmw", "euler", "lohia", "saarthi",
        "e-trio", "etrio", "omega seiki", "terra motors",
        "kinetic green", "jitendra ev", "dilli electric", "wardwizard",
        "maxima cargo", "maxima c2c",
        "re cargo", "re compact",
        "passenger carrier", "goods carrier", "cargo carrier",
        "e loader", "e-loader", "e cargo", "e-cargo",
        "electric loader", "electric cargo", "electric rickshaw",
        "last mile",
        "scooter", "moped", "motorcycle", "motor cycle",
        "three wheeler", "3 wheeler", "threewheeler",
        "two wheeler", "2 wheeler", "twowheeler",
        "e-rickshaw", "erickshaw", "auto rickshaw", "autorickshaw",
        "rickshaw", "tuk",
    ]

    def classify(self, model_text: str) -> str:
        if not model_text:
            return "無資料"
        t = model_text.lower()

        # 先判二/三輪（優先），避免 "bajaj cargo" 被 "car" 誤攔
        for kw in self.TWO_THREE_WHEEL_KEYWORDS:
            if kw in t:
                return "是"

        for kw in self.FOUR_WHEEL_KEYWORDS:
            if kw in t:
                return "否"

        for pattern in self.FOUR_WHEEL_EXACT_WORDS:
            if re.search(pattern, t):
                return "否"

        return "否"


# ---------------------------------------------------------------------------
# 3. 頁面解析器
# ---------------------------------------------------------------------------
class PageParser:
    """從 vehicleinfo.app 頁面文字中解析車型名稱"""

    def extract_model(self, content: str, plate: str) -> str:
        lines = [l.strip() for l in content.split("\n") if l.strip()]

        # 找第二次出現車號的位置，下一行即車型
        count = 0
        for j, line in enumerate(lines):
            if line.upper() == plate.upper():
                count += 1
                if count == 2:
                    if j + 1 < len(lines):
                        candidate = lines[j + 1]
                        if not re.match(r'^[A-Z\*\s]{1,5}$', candidate):
                            return candidate

        # 備用：第一次出現後跳過 "Change" 那行
        for j, line in enumerate(lines):
            if line.upper() == plate.upper():
                for k in range(j + 1, min(j + 5, len(lines))):
                    if lines[k].upper() not in ("CHANGE", plate.upper()):
                        if re.search(r'[A-Z]{2,}', lines[k]):
                            return lines[k]
                break
        return ""


# ---------------------------------------------------------------------------
# 4. 查詢主程式
# ---------------------------------------------------------------------------
class VehicleQueryRunner:
    """整合讀檔、查詢、分類、寫出的主控制器"""

    def __init__(self, input_file: str, plate_col: str, delay_sec: float, threads: int = 3):
        self.input_file  = input_file
        self.plate_col   = plate_col
        self.delay_sec   = delay_sec
        self.threads     = threads
        self.classifier  = VehicleClassifier()
        self.parser      = PageParser()
        # 自動產生輸出檔名：原檔名_result.csv
        src = Path(input_file)
        self.input_path      = INPUT_DIR  / src.name
        self.output_file     = str(OUTPUT_DIR / (src.stem + "_result.csv"))
        self.checkpoint_file = str(TEMP_DIR   / (src.stem + "_checkpoint.json"))
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        TEMP_DIR.mkdir(parents=True, exist_ok=True)

    # 無效車牌判斷（防呆）
    INVALID_PLATES = {"", "0", "00", "000", "0000", "00000", "000000", "null", "none", "nan", "n/a", "-"}

    def _is_invalid_plate(self, plate: str) -> bool:
        return plate.lower() in self.INVALID_PLATES or not re.search(r'[A-Z0-9]', plate, re.I)

    def run(self):
        start_time = time.time()
        reader = FileReader(str(self.input_path), self.plate_col)
        records, original_cols = reader.read()

        # 將 vehicle_model、is_target 插入 PLATE_COL 欄位正後方
        plate_idx   = original_cols.index(self.plate_col) if self.plate_col in original_cols else len(original_cols) - 1
        output_cols = original_cols[:plate_idx+1] + ["vehicle_model", "is_target"] + original_cols[plate_idx+1:]

        total = len(records)
        plate_keys = [str(r.get(self.plate_col, "")).strip().upper().replace(" ", "") for r in records]
        plate_to_record_indexes = {}
        for idx, plate in enumerate(plate_keys):
            if not self._is_invalid_plate(plate):
                plate_to_record_indexes.setdefault(plate, []).append(idx)

        # ── 方案 C：先對有效車牌去重，只查不重複的 ──
        unique_plates = []
        seen = set()
        for r in records:
            p = str(r.get(self.plate_col, "")).strip().upper().replace(" ", "")
            if not self._is_invalid_plate(p) and p not in seen:
                seen.add(p)
                unique_plates.append(p)

        valid_count = sum(
            1 for r in records
            if not self._is_invalid_plate(str(r.get(self.plate_col, "")).strip().upper().replace(" ", ""))
        )
        skipped    = total - valid_count
        duplicates = valid_count - len(unique_plates)
        print(f"讀取檔案：{self.input_path}")
        print(f"總筆數：{total}  │  無效/跳過：{skipped}  │  重複車牌：{duplicates}  │  不重複車牌：{len(unique_plates)}")
        print(f"預估查詢時間：約 {len(unique_plates) * self.delay_sec / 60:.0f} 分鐘\n")

        # 查詢唯一車牌，結果存入 cache（多 thread 平行）
        cache: dict[str, tuple[str, str]] = {}  # plate -> (vehicle_model, is_target)
        lock    = threading.Lock()
        write_lock = threading.Lock()
        counter = [0]  # 用 list 讓 thread 可以共享計數
        written_indexes = set()

        # 若有進度記錄，載入並過濾已查詢的車牌
        if Path(self.checkpoint_file).exists():
            try:
                with open(self.checkpoint_file, encoding="utf-8") as f:
                    saved = json.load(f)
                cache.update({k: tuple(v) for k, v in saved.items()})
                resumed = len(cache)
                unique_plates = [p for p in unique_plates if p not in cache]
                print(f"找到進度記錄，已恢復 {resumed} 筆，剩餘 {len(unique_plates)} 筆待查詢。\n")
            except Exception as e:
                print(f"進度記錄讀取失敗（{e}），從頭開始查詢。\n")

        # 初始化結果檔（先寫表頭），並先寫出「目前可確定」的資料
        self._init_output_file(output_cols)
        initial_rows = []
        for idx, record in enumerate(records):
            plate = plate_keys[idx]
            if self._is_invalid_plate(plate):
                row = {**record, "vehicle_model": "", "is_target": "車牌無效"}
            elif plate in cache:
                model, result = cache[plate]
                row = {**record, "vehicle_model": model, "is_target": result}
            else:
                continue
            initial_rows.append(row)
            written_indexes.add(idx)
        if initial_rows:
            self._append_rows(initial_rows, output_cols)

        # 將車牌平均分配給各 thread
        n = self.threads
        if unique_plates:
            chunk_size = math.ceil(len(unique_plates) / n)
            chunks = [unique_plates[i:i+chunk_size] for i in range(0, len(unique_plates), chunk_size)]
            print(f"啟動 {len(chunks)} 個平行查詢 thread...\n")
            with ThreadPoolExecutor(max_workers=len(chunks)) as executor:
                futures = [
                    executor.submit(
                        self._worker,
                        chunk,
                        records,
                        output_cols,
                        plate_to_record_indexes,
                        written_indexes,
                        cache,
                        lock,
                        write_lock,
                        counter,
                        len(unique_plates),
                    )
                    for chunk in chunks
                ]
                for f in futures:
                    f.result()  # 等待所有 thread 完成，並傳遞例外
        else:
            print("所有車牌均已從進度記錄恢復，跳過查詢階段。\n")

        # 補寫尚未落盤的列（理論上不多，保險補齊）
        final_rows = []
        for idx, record in enumerate(records):
            if idx in written_indexes:
                continue
            plate = plate_keys[idx]
            if self._is_invalid_plate(plate):
                model, result = "", "車牌無效"
            else:
                model, result = cache.get(plate, ("", "查詢失敗"))
            final_rows.append({**record, "vehicle_model": model, "is_target": result})
            written_indexes.add(idx)
        if final_rows:
            self._append_rows(final_rows, output_cols)

        self._print_summary(start_time)

        # 全部完成，清除進度記錄
        if Path(self.checkpoint_file).exists():
            Path(self.checkpoint_file).unlink()
            print("進度記錄已清除。")

    def _worker(self, plates_chunk: list, records: list, output_cols: list,
                plate_to_record_indexes: dict, written_indexes: set,
                cache: dict, lock: threading.Lock, write_lock: threading.Lock,
                counter: list, total_unique: int):
        """每個 thread 獨立啟動自己的瀏覽器，處理分配到的車牌清單"""
        stealth = Stealth()
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"]
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
                locale="en-IN",
            )
            page = context.new_page()
            stealth.apply_stealth_sync(page)

            for plate in plates_chunk:
                model, result = self._query_plate(page, plate)
                # 先在鎖內更新共享狀態，再複製快照供 checkpoint 寫入
                with lock:
                    cache[plate] = (model, result)
                    counter[0] += 1
                    flag = "✅" if result == "是" else ""
                    print(f"[{counter[0]:3}/{total_unique}] {plate:<18} | {model:<35} | {result} {flag}")

                    rows_to_write = []
                    for idx in plate_to_record_indexes.get(plate, []):
                        if idx in written_indexes:
                            continue
                        record = records[idx]
                        rows_to_write.append({**record, "vehicle_model": model, "is_target": result})
                        written_indexes.add(idx)

                    checkpoint_snapshot = dict(cache)

                if rows_to_write:
                    with write_lock:
                        self._append_rows(rows_to_write, output_cols)

                try:
                    self._save_checkpoint(checkpoint_snapshot)
                except Exception as e:
                    # checkpoint 失敗不應中斷查詢；下次成功時仍會覆蓋成最新進度
                    print(f"⚠️ checkpoint 寫入失敗：{str(e)[:80]}")
                time.sleep(self.delay_sec)

            browser.close()

    def _save_checkpoint(self, cache_snapshot: dict):
        """將目前 cache 寫入進度記錄檔（每筆查詢後呼叫）"""
        import threading as _threading
        tmp_file = self.checkpoint_file + f".{_threading.get_ident()}.tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(cache_snapshot, f, ensure_ascii=False)
        Path(tmp_file).replace(self.checkpoint_file)

    def _init_output_file(self, fieldnames: list):
        """初始化結果檔並寫入表頭。"""
        with open(self.output_file, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
            w.writeheader()

    def _append_rows(self, rows: list, fieldnames: list):
        """將多筆結果追加到結果檔。"""
        with open(self.output_file, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
            w.writerows(rows)

    def _query_plate(self, page, plate: str) -> tuple:
        """查詢單一車牌，回傳 (vehicle_model, is_target)"""
        try:
            page.goto(
                f"https://vehicleinfo.app/rc-details/{plate}?rc_no={plate}",
                wait_until="networkidle", timeout=25000
            )
            page.wait_for_timeout(2000)
            content = page.inner_text("body")
            model = self.parser.extract_model(content, plate)
            return model, self.classifier.classify(model)
        except Exception as e:
            return str(e)[:50], "查詢失敗"

    def _print_summary(self, start_time: float):
        elapsed = int(time.time() - start_time)
        h, rem  = divmod(elapsed, 3600)
        m, s    = divmod(rem, 60)
        with open(self.output_file, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        print(f"\n{'='*50}")
        print(f"✅ Tutu車：          {sum(1 for r in rows if r['is_target']=='是')} 筆")
        print(f"❌ 其他車種：        {sum(1 for r in rows if r['is_target']=='否')} 筆")
        print(f"❌ 車牌無效：        {sum(1 for r in rows if r['is_target']=='車牌無效')} 筆")
        print(f"❌ 無資料：          {sum(1 for r in rows if r['is_target']=='無資料')} 筆")
        print(f"⚠️  查詢失敗：        {sum(1 for r in rows if r['is_target']=='查詢失敗')} 筆 (需再次複查)")
        print(f"\n執行設定：Threads={self.threads}, Delay_Sec={self.delay_sec}")
        print(f"總耗時：{h:02d} 時 {m:02d} 分 {s:02d} 秒")
        print(f"結果存至：{self.output_file}")


# ---------------------------------------------------------------------------
# 5. 入口
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    runner = VehicleQueryRunner(
        input_file  = INPUT_FILE,
        plate_col   = PLATE_COL,
        delay_sec   = DELAY_SEC,
        threads     = THREADS,
    )
    runner.run()
