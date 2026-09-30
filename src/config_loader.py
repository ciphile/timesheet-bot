"""
config_loader.py — Đọc và kiểm tra toàn bộ cấu hình của dự án timesheet.

Vai trò: mọi module khác (bot, excel, mail, AI...) đều gọi load_config()
để lấy cấu hình. Nếu thiếu hay sai bất kỳ thứ gì, module này báo lỗi
tiếng Việt rõ ràng và DỪNG NGAY, không để lỗi lan sang các bước sau.

Chạy thử trực tiếp (self-test):
    python thư mục timesheet\\src\\config_loader.py
"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------
# Đường dẫn gốc: suy ra từ vị trí của chính file này (src\.. = gốc).
# Nhờ vậy KHÔNG hardcode "thư mục timesheet" — sau này chuyển cả thư mục
# sang máy khác hay VPS vẫn chạy nguyên.
# ---------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent

CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
TEMPLATE_DIR = BASE_DIR / "template"
OUTPUT_DIR = BASE_DIR / "output"
BACKUP_DIR = BASE_DIR / "backup"          # bản sao Excel trước khi ghi (*.xlsx)

# ── Backup DỮ LIỆU bot — gom hết vào data\backup\ (24-Sep) ──────────
# ĐỊNH NGHĨA DUY NHẤT: nơi TẠO backup và nơi DỌN backup đều import từ đây
# → không bao giờ lệch đường dẫn.
DATA_BACKUP_DIR     = DATA_DIR / "backup"
NOTES_BAK_DIR       = DATA_BACKUP_DIR / "notes"              # notes.jsonl.bak_*
PARSED_BAK_DIR      = DATA_BACKUP_DIR / "parsed_days"        # parsed_days.json.bak_* (/resetnotes)
PARSED_SNAPSHOT_DIR = DATA_BACKUP_DIR / "parsed_days_daily"  # parsed_days_YYYYMMDD.json
CORRUPT_DIR         = DATA_BACKUP_DIR / "corrupt"            # parsed_days.json.corrupt_*
DATA_BACKUP_SUBDIRS = (NOTES_BAK_DIR, PARSED_BAK_DIR, PARSED_SNAPSHOT_DIR, CORRUPT_DIR)

SECRETS_FILE = CONFIG_DIR / "secrets.env"
SETTINGS_FILE = CONFIG_DIR / "settings.json"

_PERSONAL_CACHE = None


def personal(key: str, default: str = ""):
    """Đọc 1 thông tin CÁ NHÂN (email công ty, tên sếp, chữ ký...) từ
    settings.json — bản chia sẻ không viết cứng thông tin của ai trong code."""
    global _PERSONAL_CACHE
    if _PERSONAL_CACHE is None:
        try:
            _PERSONAL_CACHE = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            _PERSONAL_CACHE = {}
    v = _PERSONAL_CACHE.get(key)
    return default if v in (None, "") else v

# Giá trị placeholder trong secrets.env — còn sót nghĩa là chưa điền
PLACEHOLDER = "chua_co"

# Các key bắt buộc phải có trong settings.json
REQUIRED_SETTINGS = [
    "employee_name", "signature_name", "boss_name", "boss_email",
    "bcc_email", "hours_per_day", "task_names", "leave_task_names",
    "jira_required_task_names", "jira_required_keywords",
    "default_new_product_description", "month_names",
    "file_name_pattern", "email_subject_pattern", "email_body_lines",
    "special_leave_note_pattern", "telegram_success_message",
    "gemini_model", "ai_calls_per_month",
    "smtp_host", "smtp_port", "mom_holidays_url", "bot_stop_time",
]


class ConfigError(Exception):
    """Lỗi cấu hình. Thông báo đã là tiếng Việt, in ra là hiểu."""


class Config:
    """Gói toàn bộ cấu hình (bí mật + settings + đường dẫn) vào 1 chỗ."""

    def __init__(self, secrets: dict, settings: dict):
        # --- Bí mật (từ secrets.env) ---
        self.telegram_bot_token: str = secrets["TELEGRAM_BOT_TOKEN"]
        self.telegram_allowed_chat_id: int = int(secrets["TELEGRAM_ALLOWED_CHAT_ID"])
        self.gmail_address: str = secrets["GMAIL_ADDRESS"]
        self.gmail_app_password: str = secrets["GMAIL_APP_PASSWORD"]
        self.gemini_api_key: str = secrets["GEMINI_API_KEY"]

        # --- Settings (từ settings.json) — gắn nguyên khối ---
        self.settings: dict = settings

        # --- Đường dẫn hay dùng ---
        self.base_dir = BASE_DIR
        self.data_dir = DATA_DIR
        self.template_dir = TEMPLATE_DIR
        self.output_dir = OUTPUT_DIR
        self.backup_dir = BACKUP_DIR

    # Cho phép viết config.get("hours_per_day") thay vì config.settings[...]
    def get(self, key: str):
        if key not in self.settings:
            raise ConfigError(
                f"settings.json thiếu key '{key}'. "
                f"Mở {SETTINGS_FILE} kiểm tra lại."
            )
        return self.settings[key]

    def masked_summary(self) -> str:
        """Tóm tắt cấu hình để in ra màn hình, CHE bớt bí mật."""

        def mask(value: str) -> str:
            value = str(value)
            if len(value) <= 8:
                return value[:2] + "***"
            return value[:4] + "..." + value[-4:]

        lines = [
            f"Thư mục gốc        : {self.base_dir}",
            f"TELEGRAM_BOT_TOKEN : {mask(self.telegram_bot_token)}",
            f"ALLOWED_CHAT_ID    : {mask(self.telegram_allowed_chat_id)}",
            f"GMAIL_ADDRESS      : {self.gmail_address}",
            f"GMAIL_APP_PASSWORD : {mask(self.gmail_app_password)}",
            f"GEMINI_API_KEY     : {mask(self.gemini_api_key)}",
            f"Nhân viên          : {self.get('employee_name')}",
            f"Email sếp          : {self.get('boss_email')}",
            f"Model AI           : {self.get('gemini_model')}",
            f"Giờ chuẩn/ngày     : {self.get('hours_per_day')}",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------
# Các hàm kiểm tra chi tiết
# ---------------------------------------------------------------------

def _check_secret(name: str, value: str) -> str:
    """Kiểm tra 1 biến bí mật: có tồn tại, không còn placeholder."""
    if value is None or value.strip() == "":
        raise ConfigError(
            f"Thiếu {name} trong {SECRETS_FILE}.\n"
            f"Mở file bằng Notepad và điền dòng {name}=..."
        )
    value = value.strip()
    if value == PLACEHOLDER:
        raise ConfigError(
            f"{name} trong {SECRETS_FILE} vẫn còn là '{PLACEHOLDER}' "
            f"(chưa điền giá trị thật)."
        )
    return value


def _load_secrets() -> dict:
    if not SECRETS_FILE.exists():
        raise ConfigError(
            f"Không tìm thấy file bí mật: {SECRETS_FILE}\n"
            f"Kiểm tra lại file secrets.env đã nằm đúng thư mục config chưa."
        )

    load_dotenv(SECRETS_FILE)

    secrets = {}
    for name in [
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_ALLOWED_CHAT_ID",
        "GMAIL_ADDRESS",
        "GMAIL_APP_PASSWORD",
        "GEMINI_API_KEY",
    ]:
        secrets[name] = _check_secret(name, os.environ.get(name))

    # Kiểm tra dạng của từng bí mật — bắt lỗi gõ nhầm ngay từ đầu
    if ":" not in secrets["TELEGRAM_BOT_TOKEN"]:
        raise ConfigError(
            "TELEGRAM_BOT_TOKEN sai dạng (phải có dấu ':' ở giữa, "
            "dạng 1234567890:AAH...). Copy lại token từ BotFather."
        )
    if not secrets["TELEGRAM_ALLOWED_CHAT_ID"].lstrip("-").isdigit():
        raise ConfigError(
            "TELEGRAM_ALLOWED_CHAT_ID phải là con số (lấy từ @userinfobot), "
            f"đang là: {secrets['TELEGRAM_ALLOWED_CHAT_ID']!r}"
        )
    if "@" not in secrets["GMAIL_ADDRESS"]:
        raise ConfigError(
            f"GMAIL_ADDRESS không giống địa chỉ email: "
            f"{secrets['GMAIL_ADDRESS']!r}"
        )
    password = secrets["GMAIL_APP_PASSWORD"].replace(" ", "")
    if len(password) != 16:
        raise ConfigError(
            f"GMAIL_APP_PASSWORD phải đúng 16 ký tự (hiện {len(password)}). "
            "Copy lại App Password từ Google, bỏ hết khoảng trắng."
        )
    secrets["GMAIL_APP_PASSWORD"] = password
    # Google có 2 định dạng key: "AIza..." (cũ) và "AQ...." (mới,
    # phát hành từ giữa 2026). Cả hai đều hợp lệ.
    api_key = secrets["GEMINI_API_KEY"]
    if not (api_key.startswith("AIza") or api_key.startswith("AQ.")):
        raise ConfigError(
            "GEMINI_API_KEY phải bắt đầu bằng 'AIza' (định dạng cũ) "
            "hoặc 'AQ.' (định dạng mới). "
            "Kiểm tra lại key copy từ aistudio.google.com/apikey."
        )
    if len(api_key) < 20 or " " in api_key:
        raise ConfigError(
            "GEMINI_API_KEY trông không đầy đủ (quá ngắn hoặc dính "
            "khoảng trắng). Copy lại nguyên chuỗi key."
        )

    return secrets


def _load_settings() -> dict:
    if not SETTINGS_FILE.exists():
        raise ConfigError(
            f"Không tìm thấy file cấu hình: {SETTINGS_FILE}\n"
            f"Kiểm tra settings.json đã nằm đúng thư mục config chưa."
        )
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            settings = json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(
            f"settings.json bị sai cú pháp JSON (dòng {e.lineno}): {e.msg}\n"
            "Thường do thiếu/thừa dấu phẩy hoặc dấu ngoặc kép."
        )

    missing = [k for k in REQUIRED_SETTINGS if k not in settings]
    if missing:
        raise ConfigError(
            "settings.json thiếu các key sau: " + ", ".join(missing)
        )

    if not isinstance(settings["hours_per_day"], int) or settings["hours_per_day"] <= 0:
        raise ConfigError("hours_per_day phải là số nguyên dương (thường là 8).")
    if len(settings["month_names"]) != 12:
        raise ConfigError(
            f"month_names phải có đúng 12 tháng, hiện có {len(settings['month_names'])}."
        )
    if not settings["task_names"]:
        raise ConfigError("task_names không được rỗng.")

    # gemini_model: "auto" = tự dò model mới nhất từ API Google (KHUYÊN
    # DÙNG — Google đổi tên model thì hệ thống vẫn chạy). Điền tên cụ
    # thể vẫn được, nhưng khi tên đó chết thì code tự chuyển model khác.
    model = str(settings.get("gemini_model", "")).strip()
    if not model:
        raise ConfigError(
            'gemini_model không được rỗng. Dùng "auto" để hệ thống tự '
            'chọn model mới nhất (khuyên dùng).')

    # bot_stop_time: "HH:MM" (giờ bot tự tắt mỗi ngày) hoặc "" = không tự tắt
    stop = settings["bot_stop_time"]
    if stop != "":
        parts = stop.split(":")
        ok = (len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit()
              and 0 <= int(parts[0]) <= 23 and 0 <= int(parts[1]) <= 59)
        if not ok:
            raise ConfigError(
                f"bot_stop_time phải dạng HH:MM (vd \"22:50\") hoặc \"\" "
                f"để tắt tính năng, đang là: {stop!r}"
            )
    # Sick Leave thêm 24-Sep: tự bổ sung vào settings đang có trên máy
    # (không bắt người dùng sửa settings.json bằng tay).
    for _lst in ("task_names", "leave_task_names"):
        if "Sick Leave" not in settings[_lst]:
            settings[_lst] = list(settings[_lst]) + ["Sick Leave"]
    for leave in settings["leave_task_names"]:
        if leave not in settings["task_names"]:
            raise ConfigError(
                f"'{leave}' có trong leave_task_names nhưng thiếu trong task_names."
            )

    return settings


def _ensure_dirs() -> None:
    """Tạo các thư mục dữ liệu nếu chưa có (an toàn khi chạy lại)."""
    for d in [DATA_DIR, TEMPLATE_DIR, OUTPUT_DIR, BACKUP_DIR, *DATA_BACKUP_SUBDIRS]:
        d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------
# Hàm chính — các module khác chỉ cần gọi hàm này
# ---------------------------------------------------------------------

def load_config() -> Config:
    _ensure_dirs()
    secrets = _load_secrets()
    settings = _load_settings()
    return Config(secrets, settings)


# ---------------------------------------------------------------------
# Self-test: chạy trực tiếp file này để kiểm tra cấu hình
# ---------------------------------------------------------------------
if __name__ == "__main__":
    print("Đang kiểm tra cấu hình...")
    print("-" * 50)
    try:
        config = load_config()
    except ConfigError as e:
        print("LỖI CẤU HÌNH:")
        print(str(e))
        sys.exit(1)

    print(config.masked_summary())
    print("-" * 50)
    print("CONFIG OK — mọi thứ đầy đủ và đúng dạng.")
    sys.exit(0)
