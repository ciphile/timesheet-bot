"""
pipeline.py — Dây chuyền dựng bản nháp timesheet (dùng chung cho
weekly_run.py chạy thứ 6 VÀ bot.py khi người dùng ra lệnh gởi sớm/sửa).

Luồng "AI hiểu ý, script thi hành":
1. compute_period : xác định kỳ cần đủ dữ liệu (validator, tất định)
2. autofill PH    : lễ Singapore tự thành entry Public Holiday 8h
3. AI parse notes : Gemini đọc ghi chú tiếng Việt -> JSON thô theo ngày
4. postprocess    : code chuẩn hóa (viết hoa ticket, khớp task list,
                    desc mặc định "giống tuần trước", chia giờ) — mọi
                    thứ AI trả đều bị kiểm ở đây, AI không đụng file
5. validator      : checklist; thiếu gì trả câu hỏi cho bot đi hỏi
6. build_draft    : gói entries theo THÁNG (vắt tháng -> nhiều tháng)
7. render_preview : bảng text gửi Telegram cho người dùng duyệt

Ghi file thật + gửi mail KHÔNG nằm ở đây — chỉ xảy ra sau khi người dùng
"ok" (finalize nằm ở đợt B: bot.py/weekly_run.py).
"""

import json
from datetime import date, timedelta

import ai_client
import sg_holidays
import validator
import task_names as _task_names
import task_rules as _task_rules
from log_setup import get_logger

log = get_logger("pipeline")

LEAVE_PROJECTS = ("Public Holiday", "Annual Leave", "Special Leave", "Sick Leave")


# ------------------------------ kỳ báo cáo ---------------------------

def compute_period(send_day: date, state: dict, config) -> dict:
    """Trả {start, end, expected_days, ph_map}. expected_days ĐÃ loại
    các ngày lễ (lễ được autofill, không cần người dùng báo cáo)."""
    from state import last_sent_date
    start, end = validator.period_bounds(send_day, last_sent_date(state))
    workdays = validator.workdays_between(start, end)
    ph_map = sg_holidays.workday_holidays(start, end, config=config)
    expected = [d for d in workdays if d not in ph_map]
    return {"start": start, "end": end,
            "expected_days": expected, "ph_map": ph_map}


def autofill_ph_entries(ph_map: dict, config) -> list:
    """Lễ -> entry: D=E='Public Holiday', F trống, 8h (rule mục 4)."""
    return [
        {"date": d, "project": "Public Holiday", "task": "Public Holiday",
         "description": "", "hours": float(config.get("hours_per_day"))}
        for d in sorted(ph_map)
    ]


# --------------------------- lịch sử tham chiếu ----------------------

def recent_history(period_start: date, config, lookback_workdays: int = 10):
    """Đọc ~10 working day GẦN NHẤT TRƯỚC kỳ này từ các file Excel
    tháng (nguồn sự thật của dữ liệu đã gửi) — làm tài liệu tham chiếu
    cho AI hiểu "giống tuần trước", "giống hôm qua".
    Trả về list entry (date thật), cũ trước mới sau. Không có file
    lịch sử -> list rỗng (AI sẽ phải hỏi thay vì đoán)."""
    import excel_writer
    from datetime import timedelta

    entries = []
    # Gom entry của tháng chứa period_start và tháng liền trước
    months = {period_start.replace(day=1)}
    prev_month_last_day = period_start.replace(day=1) - timedelta(days=1)
    months.add(prev_month_last_day.replace(day=1))
    for m in months:
        try:
            entries.extend(excel_writer.read_month_entries(m, config))
        except Exception as e:  # noqa: BLE001 — lịch sử hỏng không được chặn luồng chính
            log.warning("Không đọc được lịch sử tháng %s: %s", m, e)

    past = sorted((e for e in entries if e["date"] < period_start),
                  key=lambda e: e["date"])
    if not past:
        return []
    keep_days = sorted({e["date"] for e in past})[-lookback_workdays:]
    return [e for e in past if e["date"] in set(keep_days)]


def _history_for_prompt(history: list) -> str:
    if not history:
        return "  (chưa có lịch sử — ai nói 'giống tuần trước/hôm qua' thì PHẢI hỏi lại)"
    lines = []
    for e in history:
        d = e["date"]
        weekday = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][d.weekday()]
        desc = f" | {e['description']}" if e.get("description") else ""
        lines.append(f"  {d.isoformat()} ({weekday}): {e['hours']:g}h "
                     f"{e['task']} — {e['project']}{desc}")
    return "\n".join(lines)


# ------------------------------ AI parse -----------------------------

def build_parse_prompt(notes: list, expected_days: list, config,
                       known_desc: dict, history: list = None,
                       pending_questions: list = None) -> str:
    """Prompt cho Gemini: đọc ghi chú tiếng Việt, trả JSON thô theo
    ngày. AI KHÔNG chia giờ mặc định, KHÔNG bịa ngày — thiếu thì hỏi."""
    # Task names + column mapping từ task_rules.py
    task_list = (
        _task_names.build_task_name_prompt_section()
        + "\n\n"
        + _task_rules.build_column_mapping_prompt()
    )
    days_list = "\n".join(f"  - {d.isoformat()} ({['Mon','Tue','Wed','Thu','Fri'][d.weekday()]})"
                          for d in expected_days)
    notes_text = "\n".join(
        f"  [{n['note_date']} {(n.get('sent_at') or n.get('saved_at', ''))[11:16]}] "
        f"{n['text']}"
        for n in notes) or "  (không có ghi chú nào)"
    known = json.dumps(known_desc, ensure_ascii=False) if known_desc else "{}"
    history_text = _history_for_prompt(history or [])
    pending_text = "\n".join(f"  - {q}" for q in (pending_questions or [])) \
        or "  (chưa hỏi gì)"
    return f"""Bạn là trợ lý điền timesheet. Đọc GHI CHÚ tiếng Việt của một lập trình viên và trả về JSON mô tả công việc TỪNG NGÀY, dịch nội dung sang tiếng Anh ngắn gọn kiểu báo cáo.

CÁC NGÀY CẦN DỮ LIỆU (kỳ đang mở):
{days_list}

NGÀY CŨ HƠN DANH SÁCH TRÊN: nếu người dùng yêu cầu SỬA/XÓA một ngày cũ hơn
(vd "sửa thứ 3 tuần trước"), VẪN trả ngày đó trong "days"/"delete_days"
— hệ thống có luồng riêng xử lý file đã gửi. Đừng bỏ qua, đừng hỏi lại.

GHI CHÚ (XẾP THEO THỨ TỰ THỜI GIAN GỬI, cũ trước mới sau; mỗi dòng
kèm ngày giờ người dùng nhắn; "hôm qua/thứ X tuần này" hiểu theo ngày nhắn):
{notes_text}

TASK NAME hợp lệ (cột E phải là MỘT trong các giá trị này, giữ nguyên chính tả):
{task_list}

DESCRIPTION mặc định đã biết theo project (dùng khi ghi chú không nói): {known}

LỊCH SỬ TIMESHEET GẦN NHẤT (tham chiếu — KHÔNG phải dữ liệu kỳ này):
{history_text}

CÂU BẠN ĐÃ HỎI NGƯỜI DÙNG LẦN TRƯỚC (ghi chú mới nhất có thể là câu TRẢ
LỜI cho những câu này):
{pending_text}

LUẬT:
- KHÔNG bịa ngày không có trong danh sách; KHÔNG bịa công việc không có trong ghi chú.
- Ngày nào ghi chú không nhắc tới thì đưa vào "unclear_days".
- FORMAT NGÀY — chuẩn hóa trước khi xử lý: người dùng viết ngày theo nhiều
  kiểu, tất cả đều chỉ CÙNG MỘT ngày nếu trùng giá trị:
  * "2026-09-15" = "15/09" = "15/09/2026" = "ngày 15" (trong ngữ cảnh
    tháng 9) = "thứ 3 tuần này" (nếu thứ 3 đó là 15/09) — khi cùng
    xuất hiện trong 1 ghi chú, GOM VÀO CÙNG 1 NGÀY, KHÔNG tách ra.
  * Ví dụ thực tế cần gom: "Ngày 2026-09-15: nghỉ phép. Ngày 15/09:
    project là abc24" -> đây là 2 chỉ dẫn cho CÙNG ngày 15/09 ->
    kết quả: 15/09 = nghỉ phép, project abc24 (1 mục, không phải 2).
- NGÀY TƯƠNG ĐỐI: "hôm qua", "thứ 4 tuần rồi/tuần trước", "cách đây 2
  tuần" -> quy ra ngày cụ thể DỰA VÀO ngày nhắn của chính ghi chú đó.
- TỪ ĐIỂN CỤM NÓI TẮT (bắt buộc hiểu đúng):
  * "làm giống tuần trước" -> với TỪNG ngày trong kỳ, copy các dòng
    của ngày CÙNG THỨ ở tuần trước từ LỊCH SỬ (Mon theo Mon, Tue theo
    Tue...). Lịch sử thiếu ngày tương ứng -> hỏi, không đoán.
  * "làm giống hôm qua / giống thứ X" -> copy các dòng của working
    day đó từ lịch sử hoặc từ kỳ này nếu đã khai.
  * "làm khác tuần trước" (mà không nói khác thế nào) -> MƠ HỒ, phải
    hỏi cụ thể, tuyệt đối không đoán.
  * "nghỉ", "off", "nghỉ phép" -> Annual Leave.
  * "nghỉ lễ" -> Public Holiday (hệ thống thường tự điền lễ Singapore
    rồi; người dùng nói nghỉ lễ vào ngày KHÔNG có trong lịch lễ ->
    hỏi lại).
  * "nghỉ bù" -> Special Leave (bù cho lễ rơi thứ 7).
  * "nghỉ bệnh", "nghỉ ốm", "nghỉ mệt", "sick" -> Annual Leave
    (công ty không có nhãn sick riêng — người dùng chốt 15-Sep-2026).
  * CỤM MƠ HỒ chỉ nói "không làm việc" mà không nói loại nghỉ:
    "không có làm", "không đi làm", "ở nhà", "tắt máy ngủ", "không vô
    cty"... -> hiểu là NGÀY NGHỈ nhưng BẮT BUỘC hỏi lại loại nghỉ
    (nghỉ phép / nghỉ bù / nghỉ bệnh?), tuyệt đối không tự đoán loại.
  * Một câu có thể trộn nhiều vế ("tuần này giống tuần trước và nghỉ
    thứ 6") -> áp vế sau đè lên vế trước cho đúng từng ngày.
- ⚠️ NGÀY TRONG NỘI DUNG THẮNG NGÀY NHẮN (CỰC KỲ QUAN TRỌNG):
  Mỗi ghi chú có dạng "[ngày-nhắn giờ] nội-dung". Ngày-nhắn trong
  ngoặc vuông [...] CHỈ là metadata (lúc người dùng bấm gửi), KHÔNG phải
  ngày của công việc. Nếu NỘI DUNG có ghi ngày cụ thể (vd "sửa ngày
  21/09/2026", "Ngày 15/09:", "21/09/2026 làm..."), thì NGÀY TRONG NỘI
  DUNG mới là ngày cần điền/sửa. TUYỆT ĐỐI KHÔNG dùng ngày trong
  ngoặc vuông làm ngày công việc khi nội dung đã ghi rõ ngày khác.
  Ví dụ: "[2026-09-24 21:34] sửa ngày 21/09/2026: nghỉ phép 2h, 6h SDF"
    -> ngày công việc = 21/09/2026 (KHÔNG phải 24/09).
    -> trả "days": [{{"date": "2026-09-21", ...}}]
- GHI CHÚ NGÀY NÀY SỬA NỘI DUNG NGÀY KHÁC (sửa xuyên ngày): ghi chú
  nhắn vào ngày X (vd thứ 4) có thể sửa nội dung của ngày Y (vd thứ 2
  hoặc thứ 3 trước đó). Dấu hiệu: ghi chú nêu rõ tên ngày/ngày tháng
  khác với ngày nhắn ("Ngày 15/09: ...", "Ngày thứ 2: ...", "2026-09-15:
  ..."). Luật ÁP DỤNG: ghi chú xuyên ngày đó THẮNG, thay thế hoàn toàn
  nội dung cũ của ngày được đề cập, kể cả ghi chú gốc của ngày đó.
  Ví dụ thực tế: ghi chú ngày 15/09 gốc là "ăn vịt quay, hít đất";
  ghi chú ngày 17/09 ghi "Ngày 15/09: nghỉ phép" -> kết quả ngày 15/09
  là nghỉ phép (8h Annual Leave), KHÔNG còn "ăn vịt quay" nữa.
- GHI CHÚ SAU SỬA GHI CHÚ TRƯỚC: các ghi chú được liệt kê theo thứ tự
  thời gian. Nếu một ghi chú SAU nói về CÙNG MỘT NGÀY và mang ý SỬA
  LẠI ("mới đúng", "sửa lại", "à nhầm", "không phải", "thay bằng",
  "bỏ cái trên", "thôi xóa hết", "bỏ hết", "chỉ làm mỗi", "thôi sửa
  lại"), thì ghi chú SAU CÙNG thắng — các ghi chú trước về ngày đó bị
  BỎ HOÀN TOÀN, không cộng dồn. Ví dụ: 4 tin liên tiếp "task ABC" ->
  "ABC328 mới đúng" -> "ABC778 mới đúng" -> "ABC999 mới đúng" thì
  ngày đó CHỈ có ABC999 8h.
- NHIỀU GHI CHÚ CÙNG NGÀY LẶP LẠI (không có từ "sửa"): nếu cùng 1 ngày
  xuất hiện nhiều ghi chú nội dung GẦN GIỐNG nhau (chỉ khác chi tiết
  nhỏ như description), lấy ghi chú CUỐI CÙNG (mới nhất) cho ngày đó,
  KHÔNG cộng dồn thành nhiều lần. Ví dụ 3 tin về 18/09 với description
  hơi khác nhau -> chỉ lấy tin CUỐI.
- DÒNG [DELETED:YYYY-MM-DD]: đây là DẤU VẾT hệ thống ghi lại "ngày này
  ĐÃ TỪNG bị xóa". Ý nghĩa: NẾU sau dòng [DELETED:X] KHÔNG có ghi chú
  thường nào về ngày X -> ngày X đã bị xóa, KHÔNG đưa vào "days" và
  KHÔNG đưa vào "delete_days" (đã xóa xong rồi). NHƯNG nếu SAU dòng
  [DELETED:X] LẠI CÓ ghi chú thường về ngày X (người dùng nhập lại) -> ghi
  chú mới THẮNG, xử lý ngày X BÌNH THƯỜNG như ghi chú mới, BỎ QUA dòng
  [DELETED:X]. TUYỆT ĐỐI không vì thấy [DELETED:X] mà đưa X vào
  delete_days khi đã có ghi chú mới về X.
- NHƯNG nếu nhiều ghi chú cùng ngày mà KHÔNG có dấu hiệu sửa lại
  (chỉ liệt kê thêm việc: "sáng làm X", "chiều làm Y") thì CỘNG DỒN
  thành nhiều task trong ngày. Không chắc là sửa hay thêm -> HỎI,
  đừng đoán.
- MỘT CÂU PHỦ NHIỀU NGÀY: "cả tuần", "2 tuần vừa rồi", "nguyên tuần
  này", "các ngày còn lại làm X", "điền full tuần" -> BUNG RA TỪNG
  NGÀY tương ứng trong danh sách, mỗi ngày một mục trong "days".
  Ngày lễ đã bị loại khỏi danh sách nên không cần điền.
- XÓA NGÀY: "xóa task ngày thứ 2", "bỏ ngày X", "xóa dữ liệu ngày X",
  "xóa hết ngày X đi" -> đưa ngày đó vào "delete_days", KHÔNG đưa vào
  "days". Nếu người dùng nhắn cùng lệnh xóa nhiều lần (2-3 lần), chỉ đưa
  ngày đó vào delete_days MỘT LẦN — không nhân đôi.
- NGƯỜI DÙNG TRẢ LỜI CÂU BẠN ĐÃ HỎI: ghi chú cuối có thể là câu trả lời
  cụt cho mục "CÂU BẠN ĐÃ HỎI NGƯỜI DÙNG LẦN TRƯỚC" ở trên.
  * Đồng ý ("ừ", "đúng rồi", "ok", "chuẩn", "phải", "yes", "đúng
    vậy") -> ÁP DỤNG NGUYÊN ĐỀ XUẤT trong câu hỏi đó, điền đầy đủ
    vào đúng ngày đã nêu, KHÔNG hỏi lại lần nữa.
  * Không đồng ý ("không", "sai rồi") kèm thông tin mới -> dùng
    thông tin mới; không kèm gì -> hỏi lại cho rõ.
  * TRẢ LỜI NHIỀU CÂU HỎI TRONG 1 TIN NHẮN: người dùng thường trả lời
    tất cả câu hỏi của bot trong 1 tin nhắn dài, mỗi bullet/dòng là
    câu trả lời cho 1 câu hỏi. GOM TẤT CẢ lại theo đúng ngày.
    Ví dụ: bot hỏi 3 câu (15/09, 16/09, 17/09 thiếu Jira). người dùng
    trả 1 tin: "• 15/09: nghỉ phép • 16/09: pacsnp-7777 • 17/09:
    pacsnp-7777" -> áp dụng ĐỒNG THỜI cho cả 3 ngày, KHÔNG hỏi lại
    bất kỳ câu nào trong đó nữa. Thông tin đã đủ = không hỏi thêm.
- TRẢ LỜI CHO CÂU HỎI CŨ: nếu ghi chú mới nhất là câu đáp ngắn
  ("ừ", "ừ đúng rồi", "đúng rồi", "ok đúng", "phải", "chuẩn") cho
  một câu ở mục CÂU HỎI MÌNH VỪA HỎI, thì ÁP DỤNG LUÔN nội dung đã
  đề xuất trong câu hỏi đó và ĐIỀN ĐẦY ĐỦ ngày liên quan (vd đã hỏi
  "thứ 3 làm tiếp DFU PACS-123 cả ngày, đúng không?" mà người dùng đáp
  "ừ đúng rồi" -> điền thứ 3: 8h Prod support/DFU — PACS-123).
  KHÔNG hỏi lại lần nữa. Nếu đáp phủ định ("không", "không phải",
  "sai rồi") thì BỎ đề xuất và hỏi lại cho rõ.
- TASK KÉO DÀI NHIỀU NGÀY: nếu một task được bắt đầu ngày X và ghi
  chú ngày Z nói đã XONG ("xong rồi", "hoàn thành", "done"), mà các
  ngày GIỮA X và Z không có ghi chú nào khác, thì ĐỪNG tự điền im
  lặng — hãy ĐỀ XUẤT trong "questions" dạng xác nhận, vd: "Thứ 3
  bro không nhắn gì, mình đoán bro làm tiếp <task> cả ngày, đúng
  không?". người dùng xác nhận thì lần parse sau mới điền.
- NGHỈ PHÉP/OFF: task_name "Annual Leave". Nghỉ lễ: "Public Holiday".
  Nghỉ bù (cho lễ rơi thứ 7): "Special Leave". Với các dòng nghỉ:
  project ghi giống task_name, description null.
- NỬA NGÀY ("nửa buổi", "half day", "chỉ làm sáng/chiều") -> hours 4
  cho phần đó; phần còn lại của ngày là task khác (nếu ghi chú nói)
  hoặc không biết thì cứ để ngày đó thiếu giờ, hệ thống sẽ hỏi.
- CHIA GIỜ TỰ ĐỘNG — KHÔNG HỎI LẠI: khi người dùng liệt kê N task cho 1
  ngày MÀ KHÔNG nói số giờ, LUÔN LUÔN đặt hours=null cho mỗi task.
  Hệ thống sẽ TỰ CHIA ĐỀU 8h/N task (vd 2 task -> 4h+4h, 3 task ->
  2.67+2.67+2.66). TUYỆT ĐỐI KHÔNG hỏi "bro muốn ghi mỗi task bao
  nhiêu giờ" — đây là câu hỏi gây phiền nhất và không cần thiết vì
  rule đã rõ. Chỉ được đặt hours khác null khi người dùng TỰ nói số giờ
  cụ thể ("task A 2 tiếng", "task B 3h"). Validation 8h/ngày và
  40h/tuần sẽ tự chạy sau — nếu tổng không đúng thì hệ thống mới báo.
- "CHIA ĐỀU", "CHIA ĐỀU GIỜ", "TỰ TÍNH", "BRO TỰ TÍNH CHIA ĐỀU": đây
  là XÁC NHẬN của người dùng rằng các task ngày đó được chia đều giờ. Giữ
  hours=null cho tất cả task ngày đó (hệ thống sẽ tự chia đều đúng),
  KHÔNG hỏi lại. Ví dụ ghi chú "Ngày 16/09, chia đều giờ" = ngày 16/09
  giữ nguyên danh sách task đã biết, hours=null cho tất cả.
- SỐ GIỜ CỤ THỂ TRONG GHI CHÚ: "2 tiếng", "3h", "4 giờ", "half" -> gán
  hours đúng task đó. Task còn lại trong ngày vẫn hours=null, hệ thống
  chia đều phần dư. Ví dụ: "task A 2 tiếng, task B còn lại" -> A=2,
  B=null (hệ thống điền B=6).
- "hours": chỉ điền khi ghi chú NÓI RÕ hoặc suy ra chắc chắn (nửa
  ngày = 4); còn lại -> null.
- "description": tiếng Anh; không đủ thông tin -> null.
- Không rõ đang assessment hay coding, thiếu Jira ticket cho UAT/DFU,
  hay bất kỳ điều gì mơ hồ -> thêm câu hỏi TIẾNG VIỆT vào "questions".

TRẢ VỀ JSON đúng cấu trúc:
{{"days": [{{"date": "YYYY-MM-DD",
            "tasks": [{{"project": "...", "task_name": "...",
                        "description": "... hoặc null",
                        "hours": số hoặc null}}]}}],
  "delete_days": ["YYYY-MM-DD", ...],
  "unclear_days": ["YYYY-MM-DD", ...],
  "questions": ["câu hỏi tiếng Việt", ...]}}"""


def ai_parse_notes(notes: list, expected_days: list, config, state: dict,
                   session: str) -> dict:
    history = recent_history(expected_days[0], config) if expected_days else []
    log.info("Nạp %d dòng lịch sử tham chiếu cho AI.", len(history))
    prompt = build_parse_prompt(notes, expected_days, config,
                                state.get("desc_by_project", {}),
                                history=history)
    return ai_client.generate_json(prompt, purpose="friday",
                                   config=config, session=session)


# --------------------------- hậu xử lý (code) ------------------------

def _clean_day_tasks(d: date, raw_tasks: list, config, state: dict,
                     leave_names: set, problems: list,
                     notes_text: str = "") -> list:
    """Làm sạch danh sách task THÔ của 1 ngày -> list entry chuẩn.
    Dùng chung cho ngày trong kỳ lẫn ngày quá khứ (luồng sửa file đã
    gửi), nên mọi luật chuẩn hóa chỉ nằm ở MỘT chỗ duy nhất."""
    tasks = []
    for t in raw_tasks:
        project = validator.uppercase_tickets(str(t.get("project") or "").strip())
        raw_task = str(t.get("task_name") or "").strip()
        # Thử rule-based trước (nhanh, 0 AI call), rồi mới validate
        task_name = _task_names.normalize_task_name(raw_task)
        if task_name is None:
            for tn in _task_names.TASK_NAMES:
                if raw_task.lower() == tn.lower():
                    task_name = tn
                    break
        if task_name is None:
            task_name = validator.normalize_task_name(raw_task, config)

        # Áp dụng project_const và desc_const từ task_rules
        # (ghi đè nếu AI chưa điền đúng)
        if task_name:
            proj_const = _task_rules.get_project_const(task_name)
            desc_const = _task_rules.get_desc_const(task_name)
            # project_const: Production Support, Annual Leave...
            if proj_const and not t.get("project"):
                t["project"] = proj_const
            # desc_const: "New product day 2 items" cho NP
            if desc_const and not t.get("description"):
                t["description"] = desc_const
        if not project:
            problems.append(f"Ngày {d.strftime('%d/%m')}: 1 task thiếu tên project")
            continue
        if task_name is None:
            problems.append(
                f"Ngày {d.strftime('%d/%m')}: task name {raw_task!r} "
                "không có trong danh sách chuẩn — chọn lại giúp mình")
            continue

        # Dòng NGHỈ (Annual/Public/Special Leave): ép đúng khuôn
        # rule mục 4 — D = E, F rỗng, bất kể AI trả gì.
        if task_name in leave_names:
            tasks.append({"project": task_name, "task": task_name,
                          "description": "",
                          "hours": float(t["hours"])
                          if t.get("hours") is not None else None})
            continue

        desc = t.get("description")
        desc = validator.uppercase_tickets(str(desc).strip()) if desc else ""
        if not desc and task_name not in LEAVE_PROJECTS:
            remembered = state.get("desc_by_project", {}).get(project)
            if remembered:
                desc = remembered           # "giống tuần trước"
            elif project.upper().startswith("PACSNP"):
                desc = config.get("default_new_product_description")
        # NP task: nếu desc đã là constant "New product day 2 items"
        # thì KHÔNG cần hỏi ticket (NP Coding/UT + Investigation/Assessment
        # dùng constant, không cần Jira trong description)
        import task_rules as _tr_fill
        np_desc_const = _tr_fill.get_desc_const(task_name)
        is_np_with_const = (
            np_desc_const and desc == np_desc_const
            and project.upper().startswith("PACSNP"))

        if (validator.needs_jira(task_name, config)
                and not validator.TICKET_RE.search(desc or "")
                and not is_np_with_const):
            # Auto-fill: tìm ticket trong ghi chú gốc, phân biệt
            # project ticket (cột D) vs description ticket (cột F)
            all_tickets = _tr_fill.extract_tickets_from_note(notes_text)
            picked = _tr_fill.pick_description_ticket(
                all_tickets, project, task_name)
            if picked:
                desc = picked
                log.debug("Auto-fill desc ticket: %s|%s → '%s'",
                          task_name, project, desc)
            elif is_np_with_const:
                pass  # NP constant → không hỏi
            else:
                problems.append(
                    f"Ngày {d.strftime('%d/%m')}: {task_name} cho {project} "
                    "— cho mình số Jira ticket để điền description")
                continue

        hours = t.get("hours")
        tasks.append({"project": project, "task": task_name,
                      "description": desc,
                      "hours": float(hours) if hours is not None else None})

    if not tasks:
        return []
    tasks, err = validator.split_hours(tasks, config.get("hours_per_day"))
    if err:
        problems.append(f"Ngày {d.strftime('%d/%m')}: {err} — chỉnh lại giúp mình")
        return []
    return [{"date": d, **t} for t in tasks]


def postprocess_ai_days(parsed: dict, expected_days: list, config,
                        state: dict, ph_map=None,
                        collect_outside: bool = False,
                        notes: list = None) -> tuple:
    """Biến JSON thô của AI thành entries sạch. Trả (entries, problems).
    problems: list câu tiếng Việt cần hỏi lại (gộp cả questions AI nêu).
    Code làm: lọc ngày lạ, viết hoa ticket, khớp task list, desc mặc
    định theo project ("giống tuần trước"), chia giờ tất định."""
    expected_set = set(expected_days)
    ph_map = ph_map or {}
    leave_names = set(config.get("leave_task_names"))
    problems = [str(q) for q in parsed.get("questions", [])]
    entries = []
    outside = []          # entries của ngày NGOÀI kỳ (luồng sửa quá khứ)

    for day_block in parsed.get("days", []):
        try:
            d = date.fromisoformat(str(day_block.get("date")))
        except ValueError as e:
            log.debug("AI trả ngày không parse được %r (%s).", day_block.get("date"), e)
            problems.append(f"AI trả ngày không hiểu được: {day_block.get('date')!r}")
            continue
        if d not in expected_set:
            if collect_outside and d not in ph_map:
                # Ngày ngoài kỳ: gom lại cho luồng sửa quá khứ xử lý,
                # KHÔNG vứt đi và cũng không hỏi lại vô ích.
                day_rows = _clean_day_tasks(
                    d, day_block.get("tasks", []), config, state,
                    leave_names, problems)
                outside.extend(day_rows)
                continue
            if d in ph_map:
                # Báo cáo công việc rơi trúng ngày lễ đã autofill
                problems.append(
                    f"Ngày {d.strftime('%d/%m')} là {ph_map[d]} (mình đã "
                    "tự điền Public Holiday 8h) — bro có THẬT SỰ làm việc "
                    "ngày lễ đó không, hay nhầm ngày?")
            else:
                # Ngày ngoài kỳ (thường là quá khứ đã gửi) — không được
                # nuốt im lặng, phải nói cho người dùng biết
                problems.append(
                    f"Ghi chú nhắc tới ngày {d.strftime('%d/%m/%Y')} nằm "
                    "NGOÀI kỳ báo cáo hiện tại (đã gửi rồi hoặc chưa tới). "
                    "Muốn sửa dữ liệu quá khứ, dùng lệnh sửa riêng nhé.")
            log.warning("AI trả ngày ngoài kỳ (%s) — chuyển thành câu hỏi.", d)
            continue

        _notes_list = notes or []
        day_notes_text = " ".join(
            n.get("text", "") for n in _notes_list
            if d.strftime("%d/%m/%Y") in n.get("text", "")
            or n.get("note_date", "") == d.isoformat())
        entries.extend(_clean_day_tasks(
            d, day_block.get("tasks", []), config, state,
            leave_names, problems, notes_text=day_notes_text))

    if collect_outside:
        return entries, problems, outside
    return entries, problems


# --------------------- parse theo NGÀY (chạy mỗi tin nhắn) -----------

def open_window(today: date, state: dict, config) -> dict:
    """Cửa sổ ngày mà 1 tin nhắn được phép nói tới:
    từ ĐẦU KỲ ĐANG MỞ (sau lần gửi cuối) tới THỨ 6 của tuần hiện tại.

    - Mở tới đầu kỳ: câu "sửa thứ 3 tuần này", "cả 2 tuần vừa rồi"
      mới có ngày để gắn vào (trước đây chỉ nhìn đúng 1 ngày nên
      mọi câu kiểu đó đều rớt ra ngoài).
    - Mở tới thứ 6: cho phép điền trước ("điền full tuần này dùm")
      — chỉ điền ngày người dùng nói rõ, không tự bịa.
    """
    from state import last_sent_date
    start, _ = validator.period_bounds(today, last_sent_date(state))
    end_of_week = today + timedelta(days=4 - today.weekday()) \
        if today.weekday() <= 4 else today
    workdays = validator.workdays_between(start, end_of_week)
    ph_map = sg_holidays.workday_holidays(start, end_of_week, config=config)
    return {"start": start, "end": end_of_week, "ph_map": ph_map,
            "days": [d for d in workdays if d not in ph_map]}


def parse_period(today: date, config, state: dict) -> dict:
    """[KHÔNG CÒN DÙNG TRONG LUỒNG CHÍNH — GIỮ LÀM DỰ PHÒNG]

    ⚠️ LỊCH SỬ & LÝ DO THAY ĐỔI (22-Sep-2026):

    HÀM NÀY TỪNG LÀ TRÁI TIM của bot — mỗi tin nhắn ghi chú đều gọi nó
    để parse LẠI TOÀN BỘ ghi chú của cả kỳ (đọc hết notes.jsonl từ đầu
    kỳ tới hôm nay, gửi cả đống cho AI).

    Vì sao ban đầu thiết kế parse-lại-cả-kỳ:
      - "thêm task" → tự chia lại giờ (AI thấy mọi task của ngày)
      - "câu sửa đè tin cũ" → AI thấy cả câu cũ lẫn câu sửa
      - "cả 2 tuần vừa rồi làm X" → AI thấy toàn bộ để xử câu đa ngày

    VẤN ĐỀ khiến phải thay:
      - Đọc cả đống notes cũ mỗi lần → prompt DÀI → AI (nhất là bản
        lite) DỄ LÚ / LẪN LỘN / NGÁO: hiểu nhầm ngày, tái phát lệnh
        xóa cũ, đọc nhầm tombstone... (xem các sự cố trong PROJECT.md)
      - notes.jsonl phình to → càng ngày prompt càng nặng
      - Phụ thuộc notes: không clean được notes giữa kỳ

    THAY BẰNG (từ 22-Sep-2026): module note_action.py
      - Mỗi tin → AI bóc thành ACTION rõ ràng (ADD/REPLACE/DELETE...)
        CHỈ đọc 1 TIN, không đọc lịch sử notes → prompt ngắn, ít ngáo
      - Thao tác thẳng parsed_days (CRUD), có validate chặt + xác nhận
      - Chia giờ bằng validator.split_hours (rule rõ ràng)
      - notes.jsonl giờ chỉ là LOG THÔ, không dùng để quyết định action

    HÀM NÀY GIỮ LẠI để:
      - Dự phòng nếu cần rollback về cách cũ
      - Tham chiếu logic build_parse_prompt / recent_history (còn dùng
        bởi finalize_and_send khi backfill missing_days lúc gửi thứ 6)
    KHÔNG XÓA để không phá selfcheck và các hàm phụ thuộc chung.

    ---
    (Docstring gốc)
    Parse LẠI toàn bộ ghi chú của kỳ đang mở. Trả dict:
      window/entries/outside/delete_in/delete_out/problems.
    """
    import notes_store
    import state as state_mod

    window = open_window(today, state, config)
    # Dọn dấu vết xóa lỗi thời TRƯỚC khi đọc notes cho AI:
    # ngày nào đã có ghi chú thật mới hơn tombstone/lệnh xóa → dọn đi
    # để AI không hiểu nhầm là muốn xóa.
    try:
        notes_store.cleanup_stale_delete_traces()
    except Exception as _e:  # noqa: BLE001 — dọn hỏng không được chặn parse
        log.debug("cleanup_stale_delete_traces lỗi: %s", _e)
    notes = notes_store.read_notes_between(window["start"], today)
    if not notes:
        return {"window": window, "entries": [], "outside": [],
                "delete_in": [], "delete_out": [], "problems": []}

    history = recent_history(window["start"], config)
    prompt = build_parse_prompt(notes, window["days"], config,
                               state.get("desc_by_project", {}),
                               history=history,
                               pending_questions=state_mod.pending_questions(
                                   state, today))
    parsed = ai_client.generate_json(prompt, purpose="daily",
                                     config=config,
                                     session=f"win_{today.isoformat()}")
    entries, problems, outside = postprocess_ai_days(
        parsed, window["days"], config, state,
        ph_map=window["ph_map"], collect_outside=True,
        notes=notes)

    in_set = set(window["days"])
    delete_in, delete_out = [], []

    # GUARD chống AI tự suy diễn lệnh xóa: chỉ chấp nhận delete_days khi
    # ghi chú MỚI NHẤT của người dùng thực sự có TỪ KHÓA XÓA. AI đôi khi tự
    # đưa ngày vào delete_days do hiểu nhầm ngữ cảnh (vd 2 ngày cùng
    # project) — điều này gây xóa nhầm dữ liệu.
    DELETE_KEYWORDS = ("xóa", "xoá", "bỏ ngày", "bỏ task", "xoá ngày",
                       "xóa ngày", "delete", "bỏ dữ liệu", "xóa dữ liệu",
                       "bỏ hết", "xóa hết", "thôi xóa")
    latest_note = notes_store.get_latest_note() if notes else None
    latest_text = (latest_note or {}).get("text", "").lower()
    has_delete_intent = any(kw in latest_text for kw in DELETE_KEYWORDS)

    raw_deletes = parsed.get("delete_days", [])
    if raw_deletes and not has_delete_intent:
        log.warning("AI trả delete_days=%s nhưng ghi chú mới nhất KHÔNG có "
                    "từ khóa xóa — BỎ QUA để tránh xóa nhầm.", raw_deletes)
        raw_deletes = []

    for iso in raw_deletes:
        try:
            d = date.fromisoformat(str(iso))
        except (ValueError, TypeError) as e:
            log.debug("AI trả ngày xóa không parse được %r (%s).", iso, e)
            problems.append(f"AI trả ngày xóa không hiểu được: {iso!r}")
            continue
        (delete_in if d in in_set else delete_out).append(d)

    # NHỚ câu vừa hỏi (chỉ có hiệu lực trong ngày hôm nay)
    state_mod.remember_questions(state, problems, today)

    return {"window": window, "entries": entries, "outside": outside,
            "delete_in": delete_in, "delete_out": delete_out,
            "problems": problems}


def describe_day(entries: list) -> str:
    """Tóm tắt 1 ngày cho bot nhắn lại người dùng xác nhận."""
    lines = []
    for e in sorted(entries, key=lambda x: x["task"]):
        desc = f" | {e['description']}" if e.get("description") else ""
        lines.append(f"  • {e['hours']:g}h {e['task']} — {e['project']}{desc}")
    total = sum(float(e["hours"]) for e in entries)
    lines.append(f"  (tổng {total:g}h)")
    return "\n".join(lines)


# ------------------------------ draft --------------------------------

def split_by_month(entries: list) -> dict:
    """{'YYYY-MM': [entries]} — mỗi dòng theo tháng CỦA CHÍNH NÓ."""
    result = {}
    for e in sorted(entries, key=lambda x: x["date"]):
        key = e["date"].strftime("%Y-%m")
        result.setdefault(key, []).append(e)
    return result


def build_draft(send_day: date, period: dict, entries: list) -> dict:
    """Đóng gói draft (JSON-hóa được để cất vào state)."""
    return {
        "send_day": send_day.isoformat(),
        "period_start": period["start"].isoformat(),
        "period_end": period["end"].isoformat(),
        "months": {
            month: [
                {**e, "date": e["date"].isoformat()} for e in rows
            ] for month, rows in split_by_month(entries).items()
        },
        "created_at": date.today().isoformat(),
    }


def draft_entries(draft: dict) -> dict:
    """Ngược lại của build_draft: {'YYYY-MM': [entries có date thật]}."""
    return {
        month: [{**e, "date": date.fromisoformat(e["date"])} for e in rows]
        for month, rows in draft.get("months", {}).items()
    }


def render_preview(draft: dict, config) -> str:
    """Bảng text gọn để đọc trên iPhone (cổng review)."""
    lines = [f"BẢN NHÁP TIMESHEET — gửi ngày {draft['send_day']}",
             f"(kỳ {draft['period_start']} → {draft['period_end']})", ""]
    grand = 0.0
    for month, rows in sorted(draft.get("months", {}).items()):
        lines.append(f"— File tháng {month} —")
        current = None
        subtotal = 0.0
        for e in rows:
            if e["date"] != current:
                current = e["date"]
                d = date.fromisoformat(e["date"])
                thu = ["T2", "T3", "T4", "T5", "T6"][d.weekday()] \
                    if d.weekday() <= 4 else "T7/CN"
                lines.append(f"{thu} {d.strftime('%d/%m')}:")
            desc = f" | {e['description']}" if e.get("description") else ""
            lines.append(f"   {e['hours']:g}h  {e['task']} — {e['project']}{desc}")
            subtotal += float(e["hours"])
        lines.append(f"   Tổng tháng {month}: {subtotal:g}h")
        lines.append("")
        grand += subtotal
    lines.append(f"TỔNG KỲ NÀY: {grand:g}h")
    return "\n".join(lines)
