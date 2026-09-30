"""
kiem_tra_truoc_khi_upload.py — KIỂM TRA AN TOÀN trước khi đưa code lên Git.

Chạy trong thư mục bản chia sẻ:   python kiem_tra_truoc_khi_upload.py
Kết quả "AN TOÀN" mới được upload. Có "❌" → sửa xong chạy lại.

Kiểm tra:
  1. Không có file riêng tư: config/settings.json, config/secrets.env, data/,
     output/, backup/, file log, notes, parsed_days, state, file Excel đã gửi.
  2. Không có token Telegram / API key Gemini / mật khẩu thật trong mọi file.
  3. Không có tên, email, số riêng của chủ dự án + tính năng RIÊNG của chủ dự án
     (email khẩn cấp, quy đổi phép…) (lưu dạng MÃ BĂM — file này
     không làm lộ chính những thông tin nó đang canh).
  4. File Excel mẫu: không còn tên / thông tin tác giả ẩn.
  5. Đủ 28 file .py.
"""
import hashlib, re, sys, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SALT = "ts-share-v1:"
CAM_BAM = set(['f771839297bf8a1ab519a6c4', '57f226cb0540d04586472425', '1fae8ceed820ce18a32e7a22', 'b2926bd5083ab34929845d21', '3d04da12ebe2712ccba5ba2b', 'bcd54753814775b5a518e11d', '33de9a858b05b4c9833cb321', '199b591c98289b6617b82390', '14104d9feb47f49f3405569c', 'c5f804a0b81d6d644e324dcb', 'ab8635447282337a22bef4f6', 'ebcbe4f4da541fe79d124ec4', '6a03b5f4d3523b2b8cecca33', '9cd60b88ec11a9aa8287bcf4'])
FILE_CAM = ["config/settings.json", "config/secrets.env"]
THU_MUC_CAM = ["data", "output", "backup", ".venv", "venv"]
MAU_BI_MAT = [
    (re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b"), "token bot Telegram"),
    (re.compile(r"AIza[0-9A-Za-z_\-]{30,}"), "API key Gemini"),
    (re.compile(r"\bAQ\.[A-Za-z0-9_\-]{20,}"), "API key Gemini (dạng mới)"),
]
# Dòng dạng secrets.env (KEY=giá trị) — CHỈ dò ở file KHÔNG phải code (.env, .txt,
# .json, .md…): trong code .py các dòng "password = ..." là biến, không phải bí mật.
DONG_BI_MAT = re.compile(r"(?m)^\s*(?:[A-Z_]*PASSWORD|[A-Z_]*TOKEN|[A-Z_]*API_KEY|"
                         r"TELEGRAM_ALLOWED_CHAT_ID|GMAIL_ADDRESS)\s*=\s*(?!(?:chua_co|123456789)\s*$)\S+")
EMAIL_MAU = {"ten.ban@congty.com", "email.rieng@gmail.com", "email.rieng.cua.ban@gmail.com", "sep@congty.com",
             "minh.rieng@gmail.com"}          # email VÍ DỤ trong README
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _bam(w: str) -> str:
    return hashlib.sha256((SALT + w).encode()).hexdigest()[:24]


def main() -> int:
    loi, can_xem = [], []
    for f in FILE_CAM:
        if (ROOT / f).exists():
            loi.append(f"File riêng tư KHÔNG được upload: {f}")
    for d in THU_MUC_CAM:
        if (ROOT / d).exists():
            loi.append(f"Thư mục dữ liệu KHÔNG được upload: {d}/")
    files = [p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts]
    for p in files:
        rel = p.relative_to(ROOT).as_posix()
        if p.suffix in (".log", ".jsonl") or p.name in ("state.json", "parsed_days.json"):
            loi.append(f"File dữ liệu cá nhân: {rel}")
        if p.suffix == ".xlsx" and rel != "template/master_template.xlsx":
            loi.append(f"File Excel không phải file mẫu (có thể là timesheet đã gửi): {rel}")
        if p.name == Path(__file__).name:
            continue
        if p.suffix == ".xlsx":
            text = ""
            with zipfile.ZipFile(p) as z:
                for n in z.namelist():
                    if n.endswith(".xml"):
                        text += z.read(n).decode("utf-8", "ignore") + "\n"
        else:
            try:
                text = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
        for rx, ten in MAU_BI_MAT:
            for m in rx.finditer(text):
                loi.append(f"{rel}: có {ten}: {m.group(0)[:12]}…")
        if p.suffix != ".py":
            for m in DONG_BI_MAT.finditer(text):
                loi.append(f"{rel}: dòng bí mật có GIÁ TRỊ THẬT: {m.group(0).split('=')[0].strip()}=…")
        for w in set(re.findall(r"[a-z0-9]+", text.lower())):
            if _bam(w) in CAM_BAM:
                loi.append(f"{rel}: có TÊN / EMAIL / SỐ RIÊNG của chủ dự án (từ '{w[:2]}…')")
        for e in set(EMAIL_RE.findall(text)):
            if e.lower() not in EMAIL_MAU and not e.lower().endswith(("@example.com", "@congty.com")):
                can_xem.append(f"{rel}: email '{e}' — xem lại có phải email thật không")
    n_py = len(list((ROOT / "src").glob("*.py")))
    if n_py != 28:
        loi.append(f"Thư mục src có {n_py} file .py (phải đúng 28)")
    print("=" * 60)
    for x in can_xem:
        print("⚠️ ", x)
    for x in loi:
        print("❌ ", x)
    if loi:
        print(f"\nKHÔNG AN TOÀN — {len(loi)} vấn đề. Sửa xong chạy lại, CHƯA được upload.")
        return 1
    print(f"✅ AN TOÀN — {len(files)} file, đủ 28 file .py, không thấy thông tin riêng tư."
          + (" (xem lại các dòng ⚠️ ở trên)" if can_xem else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
