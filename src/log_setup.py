"""
log_setup.py — Hệ thống log kỹ thuật dùng chung cho MỌI module.

Khác với audit.log (biên bản nghiệp vụ: đã làm gì), log kỹ thuật ở đây
trả lời "chạy như thế nào, lỗi gì, ở đâu" để trace và debug.

- File log nằm ở  data\\logs\\timesheet.log
- Nửa đêm tự xoay: hôm qua thành  timesheet.log.2026-09-14
- Giữ 30 ngày gần nhất, cũ hơn tự xóa.
- Trong FILE ghi mức DEBUG (chi tiết nhất, có traceback đầy đủ).
- Ra MÀN HÌNH chỉ mức INFO trở lên (đỡ ngợp khi chạy tay).

Cách dùng trong mọi module:
    from log_setup import get_logger
    log = get_logger("ten_module")
    log.info("việc gì đó")
    log.exception("lỗi gì đó")   # tự kèm traceback
"""

import logging
import sys
from logging.handlers import TimedRotatingFileHandler

from config_loader import DATA_DIR

LOG_DIR = DATA_DIR / "logs"
LOG_FILE = LOG_DIR / "timesheet.log"

# Các thư viện bên thứ ba log rất ồn ở mức INFO (mỗi request 1 dòng);
# hạ xuống WARNING để log của mình dễ đọc.
NOISY_LIBRARIES = ["httpx", "httpcore", "telegram", "apscheduler", "urllib3"]

_da_setup = False


def setup_logging() -> None:
    """Cấu hình logging 1 lần duy nhất cho cả chương trình."""
    global _da_setup
    if _da_setup:
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 1) Ghi file, xoay lúc nửa đêm, giữ 30 ngày
    file_handler = TimedRotatingFileHandler(
        LOG_FILE, when="midnight", backupCount=30, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    # 2) In màn hình (chỉ khi có màn hình — chạy nền bằng pythonw
    #    thì sys.stdout là None, bỏ qua)
    if sys.stdout is not None:
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(logging.INFO)
        console.setFormatter(fmt)
        root.addHandler(console)

    for lib in NOISY_LIBRARIES:
        logging.getLogger(lib).setLevel(logging.WARNING)

    _da_setup = True


def get_logger(name: str) -> logging.Logger:
    """Lấy logger cho 1 module. Tự setup nếu chưa setup."""
    setup_logging()
    return logging.getLogger(f"timesheet.{name}")
