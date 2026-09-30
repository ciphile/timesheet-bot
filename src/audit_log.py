"""
audit_log.py — Ghi nhật ký kiểm toán (audit log) cho MỌI hành động.

Mỗi dòng trong data\\audit.log có dạng:
    2026-09-14T21:05:33 | SU_KIEN | chi tiết

Mục đích: khi có gì đó chạy sai (hoặc chạy mà người dùng không biết),
mở file này ra là thấy toàn bộ lịch sử: bot nhận note lúc nào,
gọi AI mấy lần, ghi file gì, gửi mail lúc nào, ai lạ nhắn vào bị chặn...
"""

from datetime import datetime

from config_loader import DATA_DIR

AUDIT_FILE = DATA_DIR / "audit.log"


def audit(event: str, detail: str = "") -> None:
    """Ghi 1 dòng audit. Không bao giờ làm sập chương trình chính:
    nếu ghi log thất bại thì chỉ in cảnh báo rồi đi tiếp.

    An toàn injection: `detail` thường chứa NGUYÊN VĂN tin nhắn người dùng
    gõ (vd audit("CMD", text)). Nếu tin nhắn có ký tự xuống dòng, ghi
    thẳng sẽ TÁCH THÀNH NHIỀU DÒNG trông y hệt 1 dòng audit khác —
    giả mạo được nhật ký khi đọc bằng mắt. Thay mọi \n / \r bằng
    khoảng trắng để 1 sự kiện LUÔN LÀ ĐÚNG 1 dòng vật lý trong file.
    """
    safe_detail = str(detail).replace("\r", " ").replace("\n", " ⏎ ")
    safe_event = str(event).replace("\r", " ").replace("\n", " ")
    line = (f"{datetime.now().isoformat(timespec='seconds')} | "
           f"{safe_event} | {safe_detail}")
    try:
        with open(AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as e:
        print(f"[audit_log] Không ghi được audit.log: {e}")
