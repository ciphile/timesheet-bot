"""
ai_client.py — Cổng duy nhất để gọi Gemini + CÔNG TẮC CHI PHÍ.

Nguyên tắc (PROJECT.md mục 8):
- Hàng rào 1: tài khoản Google KHÔNG bật billing → chi phí cứng 0đ,
  vượt quota chỉ bị từ chối chứ không mất tiền.
- Hàng rào 2 (module này): bộ đếm data\\ai_usage.json với các cap
  trong settings.json:
    ai_calls_per_month   (mặc định 250)
    (quota không block — Google tự enforce qua 429)
  Trần danh nghĩa 500.000 VND/tháng — với free tier thực tế là 0đ.
- purpose: "friday" (phiên tổng hợp thứ 6), "daily" (parse ghi chú
  mỗi khi người dùng nhắn), "chat" (linh tinh). "daily"/"chat" nhường
  vùng dự trữ cho thứ 6:
  khi tháng chỉ còn <= phần dự trữ, "chat" bị chặn, "friday" vẫn chạy.
- Mọi lời gọi đều được đếm TRƯỚC khi gọi (thà đếm dư còn hơn lọt).
- AI chỉ trả dữ liệu; generate_json ép model trả JSON thuần và parse
  an toàn (bóc ```json…```, hỏng thì retry đúng 1 lần).

Chạy thử trực tiếp (1 lời gọi Gemini thật, tính vào bộ đếm):
    python thư mục timesheet\\src\\ai_client.py
"""

import json
import os
import time
from datetime import date, datetime

from config_loader import DATA_DIR, load_config
from log_setup import get_logger
from audit_log import audit

log = get_logger("ai_client")

USAGE_FILE = DATA_DIR / "ai_usage.json"

# ---------------------------------------------------------------------
# CHỌN MODEL — KHÔNG HARDCODE TÊN (người dùng yêu cầu 17-Sep-2026)
# ---------------------------------------------------------------------
# Bài học: mọi danh sách tên model viết cứng đều là ĐIỂM CHẾT ĐỊNH KỲ.
# 17-Sep-2026 Google khai tử gemini-2.0/2.5-flash -> bot tê liệt.
# Nay hệ thống TỰ HỎI Google "còn model nào dùng được" rồi tự chọn,
# nên Google có đổi tên thành gì đi nữa (kể cả "gemeomeo-9-turbo")
# thì vẫn chạy: code chỉ dựa vào DANH SÁCH THẬT từ API, không dựa
# vào bất kỳ tên nào đoán trước.
#
# settings.json: gemini_model = "auto"  -> hoàn toàn tự động (khuyên
# dùng). Điền tên cụ thể -> ưu tiên tên đó, nhưng nếu tên đó chết thì
# vẫn tự chuyển sang model khác chứ KHÔNG đứng chờ người sửa.

MODEL_CACHE_FILE = DATA_DIR / "ai_model.json"
MODEL_CACHE_DAYS = 30         # dò lại mỗi tháng — Google ít khai tử model
                              # hơn 30 ngày/lần, và khi model chết thì code
                              # TỰ CHUYỂN ngay không cần chờ cache hết hạn.
MODEL_CANDIDATES_TRIED = 3    # số model thử trong 1 lượt trước khi bỏ cuộc

# Loại bỏ các model KHÔNG dùng để sinh văn bản (nhận diện theo công
# năng trong tên — vẫn đúng kể cả khi Google đổi hệ tên).
_EXCLUDE_KEYWORDS = ("embedding", "embed", "transcribe", "tts", "speech",
                     "audio", "image", "imagen", "video", "veo", "live",
                     "robotics", "vision", "guard", "rerank")


def _model_version(name: str) -> tuple:
    """Rút các số trong tên model để so 'mới hơn'. 'abc-3.7-flash' ->
    (3, 7). Không có số -> (0,) (xếp sau). Không phụ thuộc chữ
    'gemini' nên đổi tên hãng vẫn chạy."""
    import re
    nums = re.findall(r"\d+", name)
    return tuple(int(n) for n in nums) if nums else (0,)


# ── MODEL PRIORITY ──────────────────────────────────────────────────
# Ưu tiên 1 (mặc định): gemini-flash-lite-latest — nhanh, ổn định,
#   "latest" pointer do Google quản lý, không bao giờ "not found"
# Ưu tiên 2 (dự phòng mức 1): gemini-flash-latest
# Ưu tiên 3+: các flash-lite / flash khác theo rank
# KHÔNG dùng model pro (không cần thiết)

PRIMARY_MODEL   = "gemini-flash-lite-latest"   # luôn gọi đầu tiên
FALLBACK_MODEL  = "gemini-flash-latest"         # dự phòng mức 1

# Danh sách flash-lite thêm (khi PRIMARY bị 429)
FLASH_LITE_EXTRAS: list[str] = [
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash-lite",
]
# Danh sách flash thêm (khi cả lite lẫn fallback đều 429)
FLASH_EXTRAS: list[str] = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
]

# Số retry khi 503/504 (server nghẽn)
_SERVER_RETRY = 3         # số lần retry cho model đầu tiên gặp 503
_SERVER_MAX_MODELS = 1    # sau model đầu tiên 503: thử tối đa 1 model khác rồi dừng

# Cache key để đánh dấu đã fallback sang rule_parser trong ngày
_RULE_PARSER_CACHE_KEY = "rule_parser_mode"


def _rank_model(name: str) -> tuple:
    """Khóa sắp xếp cho danh sách fallback extra:
    0) lite trước full (nhẹ hơn, ít nghẽn hơn)
    1) "latest" pointer trước version cụ thể
    2) Version mới hơn trước
    KHÔNG xếp pro (đã lọc ra trước khi rank)."""
    low = name.lower()
    is_lite  = 0 if "lite" in low else 1
    is_latest= 0 if "latest" in low else 1
    unstable = 1 if any(x in low for x in
                        ("preview", "exp", "beta", "alpha", "test")) else 0
    version  = _model_version(low)
    return (is_lite, is_latest, unstable, tuple(-v for v in version), name)


_client = None  # khởi tạo lười, dùng lại giữa các lời gọi


class AIError(Exception):
    """Lỗi gọi AI. Thông báo là tiếng Việt."""


class BudgetExceeded(AIError):
    """Giữ lại để không break import trong bot.py.
    Không còn được raise — Google tự enforce qua 429."""


# ---------------------------------------------------------------------
# Bộ đếm sử dụng
# ---------------------------------------------------------------------

def _empty_usage(month_key: str) -> dict:
    return {"month": month_key, "month_count": 0, "days": {}, "sessions": {}}


def _load_usage() -> dict:
    month_key = date.today().strftime("%Y-%m")
    if USAGE_FILE.exists():
        try:
            with open(USAGE_FILE, encoding="utf-8") as f:
                usage = json.load(f)
            if usage.get("month") == month_key:
                return usage
            log.info("Sang tháng mới (%s) — reset bộ đếm AI.", month_key)
        except (json.JSONDecodeError, OSError) as e:
            log.warning("ai_usage.json hỏng (%s) — tạo mới.", e)
    return _empty_usage(month_key)


def _save_usage(usage: dict) -> None:
    """Ghi ATOMIC (tmp + os.replace), nhất quán với state.py/daily_store.py."""
    tmp = USAGE_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(usage, f, ensure_ascii=False, indent=2)
    os.replace(tmp, USAGE_FILE)


def usage_summary(config) -> str:
    usage = _load_usage()
    today_key = date.today().isoformat()
    return (f"AI tháng {usage['month']}: {usage['month_count']}/"
            f"{config.get('ai_calls_per_month')} lượt "
            f"(hôm nay {usage['days'].get(today_key, 0)} lượt)")


def _check_budget(usage: dict, purpose: str, session: str, config) -> None:
    """Chỉ tracking — KHÔNG block, KHÔNG raise.
    Google tự enforce quota qua lỗi 429 per-model.
    Bot bắt 429 → mark_quota_exhausted → fallback model khác.
    Hàm này chỉ log để /status có số liệu báo cáo."""
    today_key    = date.today().isoformat()
    today_used   = usage["days"].get(today_key, 0)
    month_used   = usage["month_count"]
    session_used = usage["sessions"].get(session, 0) if session else 0
    log.debug("AI usage: tháng=%d, hôm_nay=%d, phiên=%s(%d)",
              month_used, today_used, session or "-", session_used)


def _record_call(usage: dict, session: str) -> None:
    today_key = date.today().isoformat()
    usage["month_count"] += 1
    usage["days"][today_key] = usage["days"].get(today_key, 0) + 1
    if session:
        usage["sessions"][session] = usage["sessions"].get(session, 0) + 1
    _save_usage(usage)


# ---------------------------------------------------------------------
# Gọi model
# ---------------------------------------------------------------------

def _get_client(config):
    global _client
    if _client is not None:
        return _client
    try:
        from google import genai
    except ImportError:
        raise AIError(
            "Thiếu gói google-genai. Chạy: "
            "pip install -r requirements.txt (trong thư mục timesheet)"
        )
    _client = genai.Client(api_key=config.gemini_api_key)
    return _client


def _explain_api_error(e: Exception) -> str:
    text = f"{type(e).__name__}: {e}"
    code = getattr(e, "code", None) or getattr(e, "status_code", None)
    if code == 429 or "RESOURCE_EXHAUSTED" in str(e).upper():
        import re as _re
        m = _re.search(r"limit[:\s]+(\d+)", str(e), _re.IGNORECASE)
        limit_str = f" (giới hạn {m.group(1)} lần/ngày)" if m else ""
        return (
            f"Chạm giới hạn free tier của Google{limit_str}. "
            "Không mất tiền — chỉ cần chờ (giới hạn ngày reset sau nửa đêm "
            "giờ Mỹ, tức khoảng 11-12h trưa giờ VN). Ghi chú vẫn được lưu, "
            "thứ 6 mình sẽ xử lý lại toàn bộ."
        )
    if code == 503 or "UNAVAILABLE" in str(e).upper():
        return (
            f"Server Gemini đang quá tải tạm thời (503 UNAVAILABLE). "
            "Đây là vấn đề phía Google, không phải lỗi mạng hay code. "
            "Thường tự hết sau vài phút — mình sẽ tự thử lại."
        )
    if code in (401, 403) or "UNAUTHENTICATED" in str(e).upper():
        return (
            f"Gemini từ chối API key ({text}). Key định dạng mới 'AQ.' "
            "cần SDK đủ mới — chạy thử:\n"
            "  pip install --upgrade google-genai\n"
            "rồi test lại. Vẫn lỗi thì tạo key mới ở aistudio.google.com/apikey."
        )
    if code == 429 or "RESOURCE_EXHAUSTED" in str(e).upper():
        return (
            f"Chạm giới hạn free tier của Google ({text}). Không mất "
            "tiền — chỉ cần chờ (giới hạn ngày reset sau nửa đêm giờ Mỹ)."
        )
    return f"Gọi Gemini thất bại ({text}). Kiểm tra mạng rồi thử lại."


RETRY_ATTEMPTS = 3
RETRY_WAIT_SECONDS = 5    # rút từ 12s xuống 5s — đỡ chờ lâu khi server thoáng lỗi


def _is_transient(e: Exception) -> bool:
    """503 UNAVAILABLE, timeout, hoặc lỗi mạng thoáng qua."""
    msg = str(e).upper()
    code = getattr(e, "code", None) or getattr(e, "status_code", None)
    return (code == 503
            or "UNAVAILABLE" in msg
            or "DEADLINE_EXCEEDED" in msg
            or "TIMEOUT" in msg)


def list_available_models(client) -> list:
    """Hỏi Google: tài khoản này hiện dùng được model nào để SINH VĂN
    BẢN? Trả list tên (bỏ tiền tố 'models/'), đã lọc bỏ embedding /
    transcribe / image... Lỗi -> list rỗng."""
    names = []
    try:
        for m in client.models.list():
            name = (getattr(m, "name", "") or "").replace("models/", "")
            if not name:
                continue
            actions = getattr(m, "supported_actions", None)
            if actions and "generateContent" not in actions:
                continue
            if any(k in name.lower() for k in _EXCLUDE_KEYWORDS):
                continue
            names.append(name)
    except Exception as e:  # noqa: BLE001 — không được chặn luồng chính
        log.warning("Không liệt kê được model từ Google: %s", e)
        return []
    return names


def rank_candidates(available: list) -> list:
    """Xếp model khả dụng theo thứ tự nên dùng (xem _rank_model)."""
    return sorted(available, key=_rank_model)


# --------------------------- cache model chọn được -------------------

def _load_model_cache() -> dict:
    if not MODEL_CACHE_FILE.exists():
        return {}
    try:
        with open(MODEL_CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.debug("Cache model không đọc được (%s) — coi như chưa có.", e)
        return {}


def _save_model_cache(model: str, candidates: list,
                      quota_exhausted: list | None = None) -> None:
    """Lưu cache model. quota_exhausted: danh sách model đã hết quota
    HÔM NAY (kèm ngày) — để sáng hôm sau không bỏ qua model tốt."""
    cache = _load_model_cache()
    # Giữ lại quota_exhausted từ cache cũ (nếu không truyền mới)
    if quota_exhausted is None:
        quota_exhausted = cache.get("quota_exhausted", [])
    today = datetime.now().date().isoformat()
    # Giữ rule_parser_mode và cache_date từ cache cũ
    old_rp = cache.get(_RULE_PARSER_CACHE_KEY)
    payload = {"model": model,
               "candidates": candidates[:5],
               "resolved_at": datetime.now().isoformat(timespec="seconds"),
               "quota_exhausted": quota_exhausted,
               "cache_date": today,
               _RULE_PARSER_CACHE_KEY: old_rp}
    try:
        tmp = MODEL_CACHE_FILE.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, MODEL_CACHE_FILE)
    except OSError as e:
        log.warning("Không lưu được cache model: %s", e)


def is_rule_parser_mode(cache: dict = None) -> bool:
    """True nếu hôm nay đã fallback sang rule_parser (tất cả model đều hết/lỗi)."""
    if cache is None:
        cache = _load_model_cache()
    today = datetime.now().date().isoformat()
    return cache.get(_RULE_PARSER_CACHE_KEY) == today


def set_rule_parser_mode() -> None:
    """Đánh dấu hôm nay dùng rule_parser. Reset tự động ngày mai."""
    cache = _load_model_cache()
    today = datetime.now().date().isoformat()
    cache[_RULE_PARSER_CACHE_KEY] = today
    cache["cache_date"] = today
    # Ghi thẳng vào file (không qua _save_model_cache vì cần giữ field đặc biệt)
    tmp = MODEL_CACHE_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    os.replace(tmp, MODEL_CACHE_FILE)
    log.warning("Đã set rule_parser mode — hôm nay dùng rule script, "
                "mai reset về %s.", PRIMARY_MODEL)


def clear_rule_parser_mode() -> None:
    """Gỡ cờ rule_parser_mode của hôm nay (thêm 24-Sep) — dùng khi người dùng
    chủ động thử lại (/retrynotes) sau khi mạng có lại. Nếu AI vẫn lỗi thì
    cờ sẽ tự bật lại như bình thường."""
    cache = _load_model_cache()
    if cache.pop(_RULE_PARSER_CACHE_KEY, None) is None:
        return
    tmp = MODEL_CACHE_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    os.replace(tmp, MODEL_CACHE_FILE)
    log.info("Đã gỡ rule_parser_mode — thử lại AI.")


def _quota_exhausted_today(cache: dict) -> list:
    """Trả danh sách model đã hết quota HÔM NAY (lọc bỏ ngày cũ)."""
    today = datetime.now().date().isoformat()
    return [
        entry["model"] for entry in cache.get("quota_exhausted", [])
        if entry.get("date") == today
    ]


def _mark_quota_exhausted(model: str) -> None:
    """Ghi nhận model này đã hết quota hôm nay vào cache."""
    cache = _load_model_cache()
    today = datetime.now().date().isoformat()
    existing = [e for e in cache.get("quota_exhausted", [])
                if e.get("date") == today]  # chỉ giữ ngày hôm nay
    if not any(e["model"] == model for e in existing):
        existing.append({"model": model, "date": today})
    log.info("Đánh dấu model %s hết quota ngày %s — "
             "sáng mai quota reset, sẽ dùng lại bình thường.", model, today)
    _save_model_cache(
        cache.get("model", model),
        cache.get("candidates", [model]),
        quota_exhausted=existing)


def _cache_is_fresh(cache: dict) -> bool:
    try:
        age = datetime.now() - datetime.fromisoformat(cache["resolved_at"])
        return age.days < MODEL_CACHE_DAYS
    except (KeyError, ValueError, TypeError) as e:
        log.debug("Cache model thiếu trường resolved_at (%s) — coi như hết hạn.", e)
        return False


def resolve_candidates(client, config, force_refresh: bool = False) -> list:
    """Trả DANH SÁCH model nên thử, theo thứ tự ưu tiên.

    LUỒNG CHÍNH (99% số lần gọi):
    1. Đọc cache (data\ai_model.json) — trả về ngay trong vài ms.
       Cache giữ 30 ngày. Khi model cache bị khai tử, _call_model
       phát hiện 404 và gọi resolve_candidates(force_refresh=True)
       để dò lại NGAY — vậy nên cache hết hạn KHÔNG phải điều kiện
       quan trọng, model chết mới kích hoạt dò lại.
    2. Nếu settings ghi tên cụ thể (không phải "auto") -> đặt lên đầu
       danh sách, vẫn kèm model cache phía sau để có đường lui.

    CHỈ GỌI API (khi cache rỗng / hết hạn / force_refresh):
    - Liệt kê 30 model từ Google, lọc, xếp hạng, lưu cache lại.
    - force_refresh=True: do model cache vừa bị 404 -> cần model mới.
    - Gọi API hỏng (mạng) -> dùng cache dù cũ, không chết.
    """
    preferred = str(config.get("gemini_model") or "").strip()
    if preferred.lower() in ("auto", "", "latest"):
        preferred = ""

    cache = _load_model_cache()

    # NHÁNH NHANH: cache còn tươi và không bị ép dò lại -> trả ngay
    if not force_refresh and _cache_is_fresh(cache) and cache.get("candidates"):
        candidates = list(cache["candidates"])
        # Bỏ qua model đã hết quota HÔM NAY — nhưng vẫn giữ trong
        # danh sách cuối (phòng khi tất cả đều hết). Sáng mai quota
        # reset, danh sách "quota_exhausted" chứa ngày hôm qua sẽ
        # bị bỏ qua tự động (chỉ lọc đúng ngày hôm nay).
        exhausted_today = _quota_exhausted_today(cache)
        had_exhausted_yesterday = (
            cache.get("quota_exhausted") and not exhausted_today)
        if had_exhausted_yesterday:
            # Quota hôm qua đã reset — sort lại theo rank để model tốt
            # nhất đứng đầu (khi bị 429, model kế được lưu lên đầu cache,
            # nên phải re-rank để trả về đúng thứ tự ưu tiên ban đầu).
            candidates = rank_candidates(candidates)
            log.info("Quota ngày cũ đã reset — dùng lại model tốt nhất: %s",
                     candidates[0])
            _save_model_cache(candidates[0], candidates, quota_exhausted=[])
        elif exhausted_today:
            fresh = [m for m in candidates if m not in exhausted_today]
            stale = [m for m in candidates if m in exhausted_today]
            candidates = fresh + stale  # model hết quota xuống cuối
            if fresh:
                log.debug("Dùng model từ cache: %s (bỏ qua %s đã hết "
                         "quota hôm nay).", fresh[0], exhausted_today)
            else:
                log.warning("Tất cả model trong cache đã hết quota hôm nay "
                            "— thử lại với danh sách đầy đủ, hy vọng "
                            "có model dự phòng chưa hết.")
        else:
            log.debug("Dùng model từ cache: %s (còn hạn).", candidates[0])
        if preferred:
            candidates = [preferred] + [m for m in candidates if m != preferred]
        return candidates

    # NHÁNH CHẬM: dò từ API (xảy ra <= 1 lần/30 ngày hoặc khi model chết)
    if force_refresh:
        log.info("Dò lại model từ Google (model cũ vừa bị khai tử)...")
    else:
        log.info("Cache model hết hạn hoặc chưa có — dò từ Google lần đầu...")

    available = list_available_models(client)
    if available:
        # Lấy danh sách đã hết quota HÔM NAY từ cache cũ (nếu có)
        exhausted_now = _quota_exhausted_today(cache) if cache else []
        # Ưu tiên model chưa hết quota; model đã hết quota xuống cuối
        fresh_avail = [m for m in available if m not in exhausted_now]
        stale_avail = [m for m in available if m in exhausted_now]
        ranked = rank_candidates(fresh_avail) + rank_candidates(stale_avail)
        candidates = ranked
        best = candidates[0] if candidates else available[0]
        log.info("Dò model từ Google: %d model dùng được, chọn %s "
                 "(đã lưu cache, dùng lại 30 ngày).",
                 len(available), best)
        if exhausted_now:
            log.info("Bỏ qua %d model đã hết quota hôm nay: %s",
                     len(exhausted_now), exhausted_now)
        _save_model_cache(best, candidates)
        audit("AI_MODELS_RESOLVED",
              f"top={best}; {len(available)} available; "
              f"exhausted_today={exhausted_now}")
    elif cache.get("candidates"):
        candidates = list(cache["candidates"])
        log.warning("Không dò được model từ Google (mạng?) — "
                    "dùng lại cache cũ: %s.", candidates[0])
    else:
        candidates = []
        log.error("Không có cache và không dò được model — "
                  "kiểm tra mạng và API key.")

    if preferred:
        candidates = [preferred] + [m for m in candidates if m != preferred]
    return candidates


def refresh_model_cache_if_needed(config) -> dict:
    """Kiểm tra cache model còn mới không, dò lại nếu cần.
    Gọi bởi housekeeping mỗi lần bot khởi động — ĐỘC LẬP với việc
    có tin nhắn hay không. Nhờ vậy cache CHẮC CHẮN được dò lại đúng
    hạn dù người dùng không nhắn gì cả tuần/tháng.

    Trả {"refreshed": bool, "model": str, "reason": str}.
    KHÔNG raise — lỗi mạng chỉ log cảnh báo, không block bot.
    """
    cache = _load_model_cache()

    # Trường hợp 1: cache còn tươi -> không làm gì
    if _cache_is_fresh(cache) and cache.get("model"):
        days_left = MODEL_CACHE_DAYS - max(0,
            int((datetime.now() -
                 datetime.fromisoformat(cache["resolved_at"])).days))
        return {"refreshed": False,
                "model": cache["model"],
                "reason": f"cache còn hạn {days_left} ngày"}

    # Trường hợp 2: hết hạn hoặc chưa có -> dò lại
    reason = "chưa có cache" if not cache.get("model") else "cache hết hạn"
    log.info("Dò lại model AI (%s)...", reason)
    try:
        client = _get_client(config)
        available = list_available_models(client)
        if not available:
            log.warning("Dò model: Google không trả về model nào — "
                        "giữ nguyên cache cũ%s.",
                        f" ({cache['model']})" if cache.get("model") else "")
            return {"refreshed": False,
                    "model": cache.get("model", ""),
                    "reason": "dò không ra model, giữ cache cũ"}

        candidates = rank_candidates(available)
        _save_model_cache(candidates[0], candidates)
        audit("AI_MODEL_CACHE_REFRESHED",
              f"{reason} -> {candidates[0]} "
              f"({len(available)} model khả dụng)")
        log.info("Đã dò và lưu model mới: %s (%d model khả dụng).",
                 candidates[0], len(available))
        return {"refreshed": True,
                "model": candidates[0],
                "reason": reason}

    except Exception as e:  # noqa: BLE001 — KHÔNG được block bot khởi động
        log.warning("Dò lại model thất bại (%s: %s) — "
                    "giữ cache cũ%s.", type(e).__name__, e,
                    f" ({cache['model']})" if cache.get("model") else "")
        return {"refreshed": False,
                "model": cache.get("model", ""),
                "reason": f"lỗi khi dò: {type(e).__name__}"}


def _call_model(client, prompt: str, config) -> tuple:
    """Gọi model theo priority mới:

    Ưu tiên 1 (default): PRIMARY_MODEL = gemini-flash-lite-latest
    Ưu tiên 2 (dự phòng): FALLBACK_MODEL = gemini-flash-latest

    Khi gặp 429 (quota hết):
      → chuyển model kế tiếp trong danh sách flash-lite rồi flash
      → lần lượt cho đến hết tất cả → fallback rule_parser

    Khi gặp 503/504 (server nghẽn):
      → retry _SERVER_RETRY lần cho model hiện tại
      → thử tối đa _SERVER_MAX_MODELS model khác (1 cái)
      → nếu vẫn lỗi → fallback rule_parser
      (cùng thế hệ server thường cùng nghẽn, thử nhiều vô ích)

    Khi gặp 404 (model bị khai tử):
      → chuyển model kế ngay, không retry

    Cache: lưu model vừa thành công để dùng lại.
    Reset: ngày mới luôn bắt đầu lại từ PRIMARY_MODEL.
    """
    cache = _load_model_cache()
    today = datetime.now().date().isoformat()

    # Reset ngày mới: xóa rule_parser mode và quota cũ
    if cache.get("cache_date") != today:
        log.info("Ngày mới — reset về %s.", PRIMARY_MODEL)
        cache = {"cache_date": today, "model": PRIMARY_MODEL,
                 "candidates": [], "quota_exhausted": [],
                 _RULE_PARSER_CACHE_KEY: None}
        _save_model_cache(PRIMARY_MODEL, [], quota_exhausted=[])

    # Nếu hôm nay đã fallback sang rule_parser → raise ngay để caller dùng rule_parser
    if cache.get(_RULE_PARSER_CACHE_KEY) == today:
        raise AIError("rule_parser_mode: hôm nay đã fallback sang rule script")

    # Xây danh sách quota candidates theo thứ tự ưu tiên
    exhausted = {e["model"] for e in cache.get("quota_exhausted", [])
                 if e.get("date") == today}

    def _quota_candidates() -> list[str]:
        """Danh sách model để thử khi gặp 429 (quota), theo thứ tự ưu tiên.
        Lite trước (nhẹ, nhanh, phù hợp timesheet), flash full sau."""
        order = (
            [PRIMARY_MODEL]       # flash-lite-latest (primary)
            + FLASH_LITE_EXTRAS   # flash-lite extras trước
            + [FALLBACK_MODEL]    # flash-latest (nặng hơn, dùng sau)
            + FLASH_EXTRAS        # flash extras cuối
        )
        # Model đã dùng thành công gần nhất lên đầu (từ cache)
        cached = cache.get("model", PRIMARY_MODEL)
        if cached and cached not in order:
            order.insert(0, cached)
        # Đưa model đã hết quota xuống cuối
        fresh = [m for m in order if m not in exhausted]
        stale = [m for m in order if m in exhausted]
        return fresh + stale

    # Model bắt đầu: dùng model từ cache nếu chưa hết quota, không thì PRIMARY
    cached_model = cache.get("model", PRIMARY_MODEL)
    start_model = (cached_model if cached_model not in exhausted
                   else PRIMARY_MODEL)

    tried_quota: list[str] = []   # model đã thử vì quota
    tried_503:   list[str] = []   # model đã thử vì 503
    last_error = None

    def _try_model(model: str, max_retries: int) -> tuple | None:
        """Thử 1 model, retry khi 503. Trả (text, model) khi OK, None khi fail."""
        nonlocal last_error
        for attempt in range(1, max_retries + 1):
            try:
                response = client.models.generate_content(
                    model=model, contents=prompt)
                _check_truncated(response, model)
                text = (response.text or "").strip()
                if not text:
                    raise AIError(f"Model {model} trả về rỗng.")
                if attempt > 1 or model != start_model:
                    log.info("Gemini OK với model %s (lần thử %d).", model, attempt)
                # Lưu cache: model thành công, dùng lại lần sau
                _save_model_cache(model, _quota_candidates(),
                                  quota_exhausted=list(cache.get("quota_exhausted", [])))
                return text, model
            except AIError:
                raise
            except Exception as e:  # noqa: BLE001
                last_error = e
                msg = str(e).upper()
                code = getattr(e, "code", None)

                if "NOT_FOUND" in msg or code == 404:
                    log.warning("Model %s không còn (khai tử) — bỏ qua.", model)
                    return None

                if "RESOURCE_EXHAUSTED" in msg or code == 429:
                    log.warning("Model %s hết quota (429) — thử model kế.", model)
                    _mark_quota_exhausted(model)
                    exhausted.add(model)
                    return None   # caller xử lý quota fallback

                if _is_transient(e):
                    if attempt < max_retries:
                        log.warning("Gemini thoáng lỗi (%s lần %d/%d) — "
                                    "chờ %ds rồi thử lại.", model, attempt,
                                    max_retries, RETRY_WAIT_SECONDS)
                        time.sleep(RETRY_WAIT_SECONDS)
                        continue
                    log.warning("Model %s vẫn lỗi sau %d lần (503/504).",
                                model, max_retries)
                    return None   # caller xử lý 503 fallback

                # Lỗi LẠ (không 404/429/503): coi như server có vấn đề,
                # return None để caller đưa vào luồng fallback → rule_parser
                # (thay vì raise thẳng, bỏ qua set_rule_parser_mode)
                log.warning("Model %s lỗi lạ (%s) — coi như server lỗi, "
                            "fallback.", model, type(e).__name__)
                return None
        return None

    # ── BƯỚC 1: thử model bắt đầu (PRIMARY hoặc model cache) ──────────
    tried_quota.append(start_model)
    tried_503.append(start_model)
    result = _try_model(start_model, _SERVER_RETRY)
    if result:
        return result

    # Phân loại lỗi: quota hay server?
    last_msg = str(last_error).upper() if last_error else ""
    last_code = getattr(last_error, "code", None)
    is_quota = ("RESOURCE_EXHAUSTED" in last_msg or last_code == 429
                or start_model in exhausted)
    is_transient_err = _is_transient(last_error) if last_error else False
    # is_server: 503/timeout thật. Lỗi lạ (không quota, không transient)
    # xử lý riêng ở nhánh cuối (cũng set_rule_parser_mode).
    is_server = (not is_quota) and is_transient_err

    # ── BƯỚC 2: 503/504 server nghẽn → thử theo hệ rồi dừng ──
    # Mỗi hệ model (lite / flash) dùng server riêng:
    #   flash-lite-latest  → server cụm lite
    #   gemini-flash-latest → server cụm flash full
    # Nếu cụm lite nghẽn → thử cụm flash (server khác). Nếu vẫn 503 → rule_parser.
    if is_server and not is_quota:
        start_is_lite = "lite" in start_model.lower()
        # Thử model hệ khác: nếu đang lite → thử flash, nếu đang flash → thử lite
        cross_system = FALLBACK_MODEL if start_is_lite else PRIMARY_MODEL
        if cross_system not in tried_503 and cross_system not in exhausted:
            log.warning("Server 503 (cụm %s) — thử hệ khác: %s",
                        "lite" if start_is_lite else "flash", cross_system)
            tried_503.append(cross_system)
            tried_quota.append(cross_system)
            result = _try_model(cross_system, _SERVER_RETRY)
            if result:
                return result
            # Kiểm tra lỗi của model hệ khác
            cross_msg = str(last_error).upper() if last_error else ""
            cross_code = getattr(last_error, "code", None)
            cross_is_quota = ("RESOURCE_EXHAUSTED" in cross_msg or cross_code == 429)
            if cross_is_quota:
                # Hệ khác hết quota → chuyển sang xử lý quota fallback bên dưới
                is_quota = True
            else:
                # Cả 2 hệ đều 503 → rule_parser
                log.warning("Cả 2 hệ server đều 503 (%s, %s) "
                            "— chuyển rule_parser hôm nay.", tried_503[0], cross_system)
                set_rule_parser_mode()
                raise AIError("rule_parser_mode: server nghẽn cả 2 hệ")
        else:
            # Cross-system đã thử hoặc hết quota → rule_parser
            log.warning("Không còn model hệ khác để thử (503) — rule_parser.")
            set_rule_parser_mode()
            raise AIError("rule_parser_mode: server nghẽn, dùng rule script")

    # ── BƯỚC 3: quota hết → lần lượt thử tất cả flash-lite, rồi flash ──
    if is_quota:
        quota_list = _quota_candidates()
        for model in quota_list:
            if model in tried_quota:
                continue
            if model in exhausted:
                continue
            tried_quota.append(model)
            tried_503.append(model)
            log.info("Model trước hết quota — thử tiếp: %s", model)
            result = _try_model(model, _SERVER_RETRY)
            if result:
                return result
            # Phân loại lỗi của model này
            m_msg = str(last_error).upper() if last_error else ""
            m_code = getattr(last_error, "code", None)
            if _is_transient(last_error):
                # 503 trong khi đang fallback quota → thử 1 model nữa rồi dừng hẳn
                fallback_for_503 = next(
                    (m for m in quota_list
                     if m not in tried_quota and m not in exhausted), None)
                if fallback_for_503:
                    tried_quota.append(fallback_for_503)
                    tried_503.append(fallback_for_503)
                    log.warning("503 trong quota fallback — thử thêm: %s",
                                fallback_for_503)
                    result = _try_model(fallback_for_503, _SERVER_RETRY)
                    if result:
                        return result
                break  # đã thử 1 model thêm, vẫn 503 → dừng

        # Hết tất cả → rule_parser
        log.warning("Tất cả %d model đã thử đều hết quota hoặc lỗi "
                    "— chuyển rule_parser hôm nay.", len(tried_quota))
        set_rule_parser_mode()
        raise AIError("rule_parser_mode: tất cả model hết quota, dùng rule script")

    # Không rơi vào nhánh nào (lỗi khác) → rule_parser
    set_rule_parser_mode()
    raise AIError(f"rule_parser_mode: lỗi không xác định ({last_error})")


def _call_model_DEPRECATED(client, prompt: str, config) -> tuple:
    """Giữ lại để không break gì. Không dùng nữa."""
    candidates = resolve_candidates(client, config)
    if not candidates:
        raise AIError(
            "Không hỏi được danh sách model từ Google và cũng chưa có "
            "cache. Kiểm tra mạng và API key, rồi chạy: "
            "python ai_client.py --models")

    tried, last_error, refreshed = [], None, False
    consecutive_503 = 0
    chain_jumped = False
    while True:
        chain_jumped = False
        for model in candidates[:MODEL_CANDIDATES_TRIED]:
            if model in tried:
                continue
            tried.append(model)
            for attempt in range(1, RETRY_ATTEMPTS + 1):
                try:
                    response = client.models.generate_content(
                        model=model, contents=prompt)
                    _check_truncated(response, model)
                    text = (response.text or "").strip()
                    if not text:
                        raise AIError(f"Model {model} trả về rỗng.")
                    _save_model_cache(model, [model] + [
                        m for m in candidates if m != model])
                    return text, model
                except AIError:
                    raise
                except Exception as e:  # noqa: BLE001
                    last_error = e
                    msg = str(e).upper()
                    code = getattr(e, "code", None)
                    if "NOT_FOUND" in msg or code == 404:
                        break
                    if "RESOURCE_EXHAUSTED" in msg or code == 429:
                        _mark_quota_exhausted(model)
                        break
                    if _is_transient(e) and attempt < RETRY_ATTEMPTS:
                        time.sleep(RETRY_WAIT_SECONDS)
                        continue
                    if _is_transient(e):
                        break
                    raise AIError(_explain_api_error(e))
            if chain_jumped:
                break
        if refreshed:
            break
        refreshed = True
        fresh = resolve_candidates(client, config, force_refresh=True)
        if not [m for m in fresh if m not in tried]:
            break
        candidates = fresh

    available = list_available_models(client)
    exhausted_today = _quota_exhausted_today(_load_model_cache())
    if exhausted_today and available:
        # Tất cả model đã hết quota hôm nay — thông báo gọn, hướng dẫn rõ
        raise AIError(
            f"Hết quota free tier hôm nay cho tất cả model đã thử "
            f"({', '.join(tried)}). "
            f"Quota reset lúc 11-12h trưa giờ VN. "
            f"Ghi chú vẫn được lưu, thứ 6 xử lý lại toàn bộ."
        )
    hint = (f"\nModel tài khoản bro đang dùng được: "
            f"{', '.join(available[:8])}."
            if available else
            "\nKhông hỏi được danh sách model từ Google (mạng hoặc API "
            "key có vấn đề).")
    raise AIError(
        f"Không model nào chạy được (đã thử: {', '.join(tried)}). "
        f"Lỗi cuối: {last_error}{hint}"
    )


def _check_truncated(response, model: str) -> None:
    """AI trả lời bị CẮT vì quá dài (finish_reason MAX_TOKENS) → báo rõ,
    thay vì để JSON nửa chừng gây lỗi khó hiểu / thiếu dữ liệu (thêm 24-Sep)."""
    try:
        fr = str(getattr(response.candidates[0], "finish_reason", "") or "")
    except (AttributeError, IndexError, TypeError):
        return
    if "MAX_TOKENS" in fr.upper():
        raise AIError(
            f"Câu trả lời của AI ({model}) bị CẮT vì quá dài (mô tả dài × nhiều "
            "ngày). Chia nhỏ câu (ít ngày hơn / 1 tuần mỗi lần) rồi gửi lại.")


def generate_text(prompt: str, purpose: str, config, session: str = "") -> str:
    """Gọi Gemini trả văn bản. purpose: 'friday' | 'chat'."""
    usage = _load_usage()
    _check_budget(usage, purpose, session, config)
    _record_call(usage, session)          # đếm TRƯỚC khi gọi

    client = _get_client(config)
    started = datetime.now()
    text, model = _call_model(client, prompt, config)
    seconds = (datetime.now() - started).total_seconds()

    log.info("AI OK (%s, %.1fs, purpose=%s, session=%s) — %s",
             model, seconds, purpose, session or "-",
             usage_summary(config))
    audit("AI_CALL", f"{model}; purpose={purpose}; session={session}")
    return text


def generate_json(prompt: str, purpose: str, config, session: str = ""):
    """Gọi Gemini, ép trả JSON thuần, parse an toàn (retry đúng 1 lần)."""
    strict = (
        prompt
        + "\n\nCHỈ trả về JSON hợp lệ, không markdown, không giải thích."
    )
    raw = generate_text(strict, purpose, config, session)
    for attempt in (1, 2):
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:]
        try:
            return json.loads(cleaned.strip())
        except json.JSONDecodeError as e:
            log.warning("AI trả JSON hỏng (lần %d): %s | 200 ký tự đầu: %r",
                        attempt, e, raw[:200])
            if attempt == 2:
                raise AIError(
                    "AI trả về dữ liệu không phải JSON hợp lệ sau 2 lần "
                    "— thử lại lệnh, hoặc xem log để biết nó trả gì."
                )
            raw = generate_text(
                strict + "\nLần trước bạn trả sai định dạng. CHỈ JSON.",
                purpose, config, session)


# ---------------------------------------------------------------------
# Self-test: 1 lời gọi Gemini thật (tính vào bộ đếm)
# ---------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    cfg = load_config()

    # python ai_client.py --models  -> chỉ liệt kê model, KHÔNG tốn lượt
    if "--models" in sys.argv:
        print("Hỏi Google xem tài khoản này dùng được model nào…")
        names = list_available_models(_get_client(cfg))
        if not names:
            print("Không liệt kê được (kiểm tra mạng / API key).")
            raise SystemExit(1)
        print(f"\nCó {len(names)} model:")
        for n in names:
            mark = "  <-- đang cấu hình" if n == cfg.get("gemini_model") else ""
            print(f"  - {n}{mark}")
        print("\nMuốn đổi: sửa 'gemini_model' trong config\\settings.json")
        raise SystemExit(0)

    print("Trạng thái:", usage_summary(cfg))
    print("Gọi Gemini thật (1 lượt, tính vào bộ đếm)…")
    try:
        data = generate_json(
            'Trả về đúng JSON sau, không thêm gì: {"pong": true}',
            purpose="chat", config=cfg, session="selftest",
        )
    except AIError as e:
        print("LỖI:", e)
        raise SystemExit(1)
    assert data == {"pong": True}, data
    print("GEMINI OK — model trả lời chuẩn JSON.")
    print("Trạng thái:", usage_summary(cfg))
