"""
state.py — Trí nhớ bền vững của hệ thống (data\\state.json).

Giữ những thứ phải sống qua nhiều lần chạy:
- hold           : người dùng đã nhắn "khoan gởi" (chế độ manual) hay chưa
- draft          : bản nháp đang chờ người dùng duyệt (chưa ghi file thật)
- past_edit      : bản sửa dữ liệu ĐÃ GỬI đang chờ người dùng duyệt
- last_sent      : ngày gửi thành công gần nhất (mốc quét lỗ hổng)
- sent_days      : các ngày đã gửi (chống gửi trùng)
- desc_by_project: description gần nhất theo từng project
                   (phục vụ rule "không nói gì thì giống tuần trước")
- special_leave_links: lễ-thứ-7 nào đã được bù bằng Special Leave ngày nào
- conversation   : trạng thái hội thoại dở dang của bot (hỏi thiếu ngày…)
- last_questions : {"asked_on": ngày, "questions": [...]} — câu bot
  vừa hỏi người dùng. CÓ HẠN DÙNG TRONG NGÀY: sang ngày mới là bỏ (để bot
  không lấy câu hỏi hôm qua ra hiểu nhầm câu trả lời hôm nay), và chỉ
  giữ tối đa MAX_PENDING_QUESTIONS câu gần nhất để state không phình.
  Chi tiết: câu bot vừa hỏi người dùng. Bắt buộc phải nhớ, vì ghi
  chú chỉ lưu tin của NGƯỜI DÙNG — không có cái này thì câu trả lời cụt
  ("ừ đúng rồi") trở thành vô nghĩa với AI ở lần parse sau.

Mọi thao tác đọc-sửa-ghi đi qua load_state()/save_state() để 1 chỗ
duy nhất đụng file. File hỏng -> làm lại từ đầu + log warning (không sập).
"""

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager, contextmanager
from datetime import date, datetime

from config_loader import DATA_DIR
from log_setup import get_logger

log = get_logger("state")

STATE_FILE = DATA_DIR / "state.json"
LOCK_FILE = DATA_DIR / "state.lock"

# bot.py chạy nền cả ngày; weekly_run.py chạy như TIẾN TRÌNH RIÊNG do
# Task Scheduler bật lúc 17:00 thứ 6. Cả hai cùng đọc-sửa-ghi
# state.json — không khóa thì có thể ĐỤNG NHAU: đúng lúc weekly_run
# vừa soạn xong bản nháp và lưu vào state, một tin nhắn tới cùng lúc
# khiến bot.py tải state (bản CHƯA có nháp) rồi ghi đè lại — bản nháp
# vừa gửi người dùng duyệt BIẾN MẤT. state_lock() là khóa liên-tiến-trình
# bằng file, để BẢO ĐẢM 2 tiến trình không xử lý chồng lên nhau.
# NGƯỠNG THỜI GIAN — tính theo thời gian GIỮ KHÓA TỐI ĐA THỰC TẾ:
# 1 lượt xử lý có thể gọi AI qua 3 model, mỗi model 3 lần thử, giữa
# các lần ngủ 12s => 72 GIÂY NGỦ THUẦN, cộng thời gian chờ mạng của 9
# lời gọi API + ghi Excel + gửi Telegram. Ngưỡng cũ 120s là QUÁ SÁT:
# chỉ cần mạng chậm là vượt, khiến tiến trình kia tưởng khóa đã chết
# rồi TỰ CƯỚP KHÓA -> đúng race condition mà khóa sinh ra để ngăn.
LOCK_STALE_SECONDS = 900       # 15 phút — dài hơn MỌI thao tác hợp lệ,
                               # chỉ coi là chết khi tiến trình thật sự crash.
LOCK_ACQUIRE_TIMEOUT = 75      # chờ tối đa; quá thì BÁO BẬN, KHÔNG chạy
                               # tiếp mà bỏ khóa (xem async_state_lock).

_DEFAULT = {
    "schema": 1,
    "hold": False,
    "draft": None,
    "past_edit": None,
    "last_sent": None,
    "sent_days": [],
    "desc_by_project": {},
    "special_leave_links": {},
    "conversation": None,
    "last_questions": None,
}


MAX_PENDING_QUESTIONS = 5     # đủ cho 1 lượt hỏi; không giữ lịch sử


def remember_questions(state: dict, questions: list, today: date) -> None:
    """Lưu câu bot vừa hỏi (kèm ngày hỏi). Rỗng -> xóa hẳn."""
    if questions:
        state["last_questions"] = {
            "asked_on": today.isoformat(),
            "questions": [str(q) for q in questions][:MAX_PENDING_QUESTIONS],
        }
    else:
        state["last_questions"] = None
    save_state(state)


def pending_questions(state: dict, today: date) -> list:
    """Câu hỏi còn hiệu lực (chỉ trong NGÀY hỏi). Quá hạn -> dọn luôn.

    Vì sao phải hết hạn: hôm qua bot hỏi "thứ 3 làm tiếp DFU đúng
    không?", người dùng không trả lời. Hôm nay người dùng nhắn "ừ" cho chuyện
    KHÁC — nếu câu hỏi cũ còn nằm đó, AI sẽ tưởng người dùng đang gật cho
    câu hỏi hôm qua và điền bậy.
    """
    record = state.get("last_questions")
    if not isinstance(record, dict):
        if record:                      # bản cũ lưu dạng list -> bỏ
            state["last_questions"] = None
            save_state(state)
        return []
    if record.get("asked_on") != today.isoformat():
        state["last_questions"] = None
        save_state(state)
        return []
    return record.get("questions", [])


def _try_acquire_lock() -> bool:
    """1 lần thử tạo file khóa (tạo độc quyền — atomic ở cấp hệ điều
    hành: 2 tiến trình cùng gọi thì chỉ 1 tạo thành công)."""
    try:
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, f"{os.getpid()}|{datetime.now().isoformat()}"
                 .encode("utf-8"))
        os.close(fd)
        return True
    except FileExistsError:
        try:
            age = time.time() - LOCK_FILE.stat().st_mtime
            if age > LOCK_STALE_SECONDS:
                log.warning(
                    "state.lock tồn tại quá %ds — coi như tiến trình "
                    "giữ khóa đã chết, tự dọn để không kẹt mãi.",
                    LOCK_STALE_SECONDS)
                LOCK_FILE.unlink(missing_ok=True)
        except OSError as e:
            log.debug("Không đọc được mtime của state.lock (%s).", e)
        return False


def _acquire_lock_blocking() -> bool:
    """Vòng lặp chờ tới khi lấy được khóa hoặc hết giờ. Dùng time.sleep
    (CHẶN đồng bộ) — chỉ an toàn gọi trực tiếp trong script đồng bộ
    (weekly_run.py) hoặc qua asyncio.to_thread (bot.py)."""
    deadline = time.time() + LOCK_ACQUIRE_TIMEOUT
    while time.time() < deadline:
        if _try_acquire_lock():
            return True
        time.sleep(0.2)
    log.error(
        "Không lấy được khóa state.json sau %ds — tiến trình khác đang "
        "giữ rất lâu. Trả về False: nơi gọi sẽ BÁO BẬN và bỏ lượt này, "
        "KHÔNG chạy tiếp mà bỏ qua khóa.", LOCK_ACQUIRE_TIMEOUT)
    return False


def _release_lock(acquired: bool) -> None:
    if acquired:
        try:
            LOCK_FILE.unlink(missing_ok=True)
        except OSError as e:
            log.warning("Không xóa được state.lock: %s", e)


def clear_stale_lock_at_startup() -> bool:
    """Gọi 1 lần lúc bot khởi động: nếu còn file khóa sót lại từ lần
    chạy trước bị crash/tắt máy đột ngột, dọn luôn. Lúc khởi động chắc
    chắn chưa có thao tác nào của chính mình đang giữ khóa, nên dọn ở
    đây là an toàn tuyệt đối và tránh phải chờ hết 15 phút."""
    if LOCK_FILE.exists():
        try:
            LOCK_FILE.unlink()
            log.warning("Dọn state.lock sót lại từ lần chạy trước "
                       "(bot/máy tắt đột ngột lúc đang giữ khóa).")
            return True
        except OSError as e:
            log.warning("Không dọn được state.lock lúc khởi động: %s", e)
    return False


@contextmanager
def state_lock():
    """Khóa liên-tiến-trình quanh TRỌN VẸN 1 lượt đọc-sửa-ghi
    state.json. Dùng ở SCRIPT ĐỒNG BỘ (weekly_run.py) — bọc từ
    load_state() tới save_state() cuối cùng của lượt đó, để tiến
    trình kia phải đợi xong mới được bắt đầu, không đọc phải bản dở.

    Không hề gì nếu quên bọc ở nơi CHỈ ĐỌC (vd /status) — save_state
    ghi nguyên khối (atomic) nên đọc không khóa vẫn luôn thấy bản
    TOÀN VẸN, cũ hoặc mới, không bao giờ thấy bản nửa vời.

    CHÚ Ý: dùng time.sleep khi chờ — TUYỆT ĐỐI không gọi trực tiếp
    trong hàm async của bot.py (sẽ đứng hình cả event loop). Bên đó
    dùng async_state_lock() ở dưới.
    """
    acquired = _acquire_lock_blocking()
    try:
        yield acquired
    finally:
        _release_lock(acquired)


@asynccontextmanager
async def async_state_lock():
    """Bản KHÔNG CHẶN EVENT LOOP của state_lock(), cho bot.py (asyncio).
    Việc chờ khóa (có thể mất vài chục giây nếu weekly_run.py đang
    chạy) được đẩy sang thread riêng qua asyncio.to_thread, nên bot
    vẫn nhận/xử lý việc khác trong lúc chờ, không đứng hình.

    YIELD ra True/False = có lấy được khóa hay không. Nơi gọi PHẢI
    kiểm tra: KHÔNG lấy được thì BÁO BẬN rồi dừng, TUYỆT ĐỐI không
    chạy tiếp mà bỏ qua khóa (chạy không khóa = mở lại đúng race
    condition khóa sinh ra để ngăn)."""
    acquired = await asyncio.to_thread(_acquire_lock_blocking)
    try:
        yield acquired
    finally:
        _release_lock(acquired)


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("schema") == 1:
                merged = dict(_DEFAULT)
                merged.update(data)
                return merged
            log.warning("state.json schema lạ (%s) — tạo mới.",
                        data.get("schema"))
        except (json.JSONDecodeError, OSError) as e:
            log.warning("state.json hỏng (%s) — tạo mới.", e)
    return dict(_DEFAULT)


def save_state(state: dict) -> None:
    """Ghi ATOMIC: ghi ra file tạm rồi đổi tên đè lên file thật.
    os.replace là 1 thao tác nguyên tử của hệ điều hành — không có
    khoảnh khắc nào file state.json ở trạng thái NỬA-GHI, kể cả nếu
    máy tắt đột ngột đúng lúc đó."""
    tmp = STATE_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)


# --------------------- các helper tiện dùng --------------------------

def last_sent_date(state: dict):
    value = state.get("last_sent")
    return date.fromisoformat(value) if value else None


MAX_SENT_DAYS_KEEP = 120   # ~2.5 năm số thứ 6 — đủ chống gửi trùng,
                          # không để list mọc vô hạn qua nhiều năm


def mark_sent(state: dict, send_day: date) -> None:
    state["last_sent"] = send_day.isoformat()
    if send_day.isoformat() not in state["sent_days"]:
        state["sent_days"].append(send_day.isoformat())
    # Giữ MỚI NHẤT — chỉ cắt bớt đầu danh sách (ngày xa xưa nhất),
    # không ảnh hưởng chống-gửi-trùng của những kỳ gần đây.
    if len(state["sent_days"]) > MAX_SENT_DAYS_KEEP:
        state["sent_days"] = sorted(state["sent_days"])[-MAX_SENT_DAYS_KEEP:]
    state["draft"] = None
    state["hold"] = False
    state["conversation"] = None
    save_state(state)


def already_sent(state: dict, send_day: date) -> bool:
    return send_day.isoformat() in state.get("sent_days", [])


def remember_desc(state: dict, project: str, description: str) -> None:
    if project and description:
        state["desc_by_project"][project.strip()] = description.strip()


def desc_for(state: dict, project: str):
    return state.get("desc_by_project", {}).get((project or "").strip())


def link_special_leave(state: dict, sat_ph_iso: str, sl_date_iso: str) -> None:
    state["special_leave_links"][sat_ph_iso] = sl_date_iso
    save_state(state)
