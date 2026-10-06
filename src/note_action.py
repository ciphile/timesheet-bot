"""
note_action.py — Lõi CRUD cho sửa timesheet (dùng chung 2 luồng).

Thay parse_period (parse cả kỳ, phụ thuộc notes) bằng CRUD per-message:
mỗi tin → AI bóc thành ACTION rõ ràng → validate chặt → thao tác thẳng
parsed_days. AI chỉ đọc 1 tin (không đọc lịch sử) → nhẹ, ít ngáo.

DÙNG CHUNG cho:
  - Ngôn ngữ tự nhiên (ghi chú thường): đích = parsed_days
  - /edittimesheet: đích = parsed_days + Excel (nếu ngày đã gửi)

7 ACTION: ADD_DAY, ADD_TASK, REPLACE_DAY, MODIFY_TASK,
          DELETE_DAY, DELETE_TASK, COPY_FROM (+ NOT_ACTION)

Tái sử dụng:
  - ai_client.generate_json (model chung timesheet)
  - date_normalizer (chuẩn hóa ngày trước khi gửi AI)
  - validator.split_hours (chia giờ)
  - task_rules (validate D/E/F, ticket)

Cập nhật: 22-Sep-2026
"""

from __future__ import annotations

import re as _re_mod

from dataclasses import dataclass, field
from datetime import date

import ai_client
import date_normalizer
import validator
import task_rules as _tr
from log_setup import get_logger

log = get_logger("note_action")


# ===========================================================================
# ACTION TYPES
# ===========================================================================
ADD_DAY      = "ADD_DAY"       # ngày chưa có → insert
ADD_TASK     = "ADD_TASK"      # ngày đã có → thêm task, chia lại giờ
REPLACE_DAY  = "REPLACE_DAY"   # xóa hết ngày, ghi mới
MODIFY_TASK  = "MODIFY_TASK"   # sửa 1 task cụ thể trong ngày
DELETE_DAY   = "DELETE_DAY"    # xóa cả ngày
DELETE_TASK  = "DELETE_TASK"   # xóa 1 task, giữ task khác
COPY_FROM    = "COPY_FROM"     # copy từ ngày khác
NOT_ACTION   = "NOT_ACTION"    # không phải sửa timesheet

ALL_ACTIONS = {ADD_DAY, ADD_TASK, REPLACE_DAY, MODIFY_TASK,
               DELETE_DAY, DELETE_TASK, COPY_FROM}


@dataclass
class Action:
    type: str
    day: date | None = None
    tasks: list = field(default_factory=list)   # [{project,task,description,hours}]
    copy_from: date | None = None
    needs_confirm: bool = False
    confirm_msg: str = ""
    error: str = ""      # lỗi validation → không thực thi được
    warning: str = ""    # cảnh báo hiện trong preview (vd AI bỏ sót ticket)


# ===========================================================================
# PROMPT — bóc 1 tin thành actions (nhẹ, không đọc notes history)
# ===========================================================================
_ACTION_PROMPT = """Đọc 1 tin nhắn của người dùng về timesheet, bóc thành ACTION JSON.
Hôm nay: {today}.

ACTION TYPES:
- ADD_DAY: nhập task cho 1 ngày (mặc định khi người dùng khai việc)
- ADD_TASK: THÊM task, GIỮ task cũ (chia lại giờ). Dấu hiệu:
    "làm thêm", "thêm task", "làm...nữa", "cũng làm", "và làm".
    → KHÁC REPLACE_DAY: ADD_TASK giữ task cũ, REPLACE_DAY bỏ task cũ.
- REPLACE_DAY: GHI ĐÈ cả ngày (xóa hết task cũ, ghi task mới). Dấu hiệu:
    "chỉ...thôi", "đổi lại", "sửa...thành", "thay...thành", "thay thế",
    "mới đúng", "làm lại thành", "đổi thành", "chuyển thành".
    → dùng khi người dùng muốn ngày đó CHỈ CÒN task mới (bỏ task cũ).
- MODIFY_TASK: "task X sửa thành Y" → sửa 1 task cụ thể
- DELETE_DAY: "xóa/bỏ ngày X" → xóa cả ngày
- DELETE_TASK: "bỏ task X thôi (giữ...)" → xóa 1 task
- COPY_FROM: "giống thứ X / giống ngày Y" → copy từ ngày khác
- NOT_ACTION: không phải sửa timesheet (ok/cảm ơn/gởi mail/duyệt...)

QUY TẮC CỘT D/E/F:
{task_rules}

Task name (cột E) CHỈ dùng: Coding/UT, Investigation/Assessment,
Issue Investigation, DFU, UAT Support, SDF, Annual Leave, Public Holiday,
Special Leave, Sick Leave.
(nghỉ bệnh / nghỉ ốm / bị bệnh → Sick Leave, KHÔNG phải Annual Leave)

⚠️ TICKET — GHI ĐỦ 100%, KHÔNG BỎ SÓT:
- Chép ĐỦ mọi mã ticket trong tin, dù CÓ hay KHÔNG dấu gạch:
  INC2799 và INC-2799, PACSDFUM777 và PACSDFUM-4799 đều là ticket.
  GIỮ NGUYÊN dạng người dùng gõ (không tự thêm/bỏ dấu gạch), VIẾT HOA MÃ ticket.
- GIỮ hậu tố phần ngay sau ticket: "pacsdfum-4799 part b" →
  "PACSDFUM-4799 Part B" (KHÔNG được xóa "part b / part A").
- Cột F (mô tả) của DFU / SDF / Issue Investigation / Investigation:
  CHÉP NGUYÊN VĂN phần mô tả người dùng gõ — KHÔNG viết hoa cả câu, KHÔNG
  dịch, KHÔNG tóm tắt, KHÔNG bỏ chữ. CHỈ viết hoa mã ticket.
  Vd: "ticket # inc0045890076: Incorrect claim amount post to LP S (pn 1234567)"
   → "Ticket # INC0045890076: Incorrect claim amount post to LP S (pn 1234567)"
- DFU / SDF / Issue Investigation: mọi ticket (kể cả INC, kể cả PACSNP) → cột F,
  cột D = "Production Support".
  "production check / prod check / prod issue / production issue (check)"
  → task Issue Investigation.
- DỰ ÁN / WR: câu có "dự án X" / "project X" / "WR X" (vd "dự án LA & GA agent
  sync, UAT support, mô tả PACSGASIA-4011 - Agent Sync UAT Support"):
  cột D = X NGUYÊN VĂN (tên dự án, có thể chứa số ticket), cột E theo hành động
  (coding/UT → Coding/UT, UAT → UAT Support, assess → Investigation/Assessment,
  không nói → Coding/UT), cột F = phần sau "mô tả / description" NGUYÊN VĂN.
  KHÔNG đặt "Production Support", KHÔNG áp constant NP.
- PRODUCTION SUPPORT / prod issue / prod check / prod fix / production issue
  (check) → task Issue Investigation, cột D = "Production Support", cột F =
  ticket + mô tả. Có "WR/dự án/project X" (vd "prod issue, WR PACSNP-3083, mô tả
  Ticket# 1234 - …") → cột D = X thay cho "Production Support".
- TASK chọn theo từ khóa ở phần ĐẦU câu (trước "mô tả/description"); chữ nằm
  TRONG mô tả (vd "…existing production issue…") KHÔNG dùng để chọn task.
- NP + hành động ("làm NP assess cho pacsnp-…"): task theo HÀNH ĐỘNG
  (assess → Investigation/Assessment, UAT → UAT Support, code → Coding/UT).
- NP = có ticket PACSNP và task là Coding/UT (code / test / UT / coding),
  Investigation/Assessment (assess / assessment) hoặc UAT Support (UAT):
  cột D = TẤT CẢ ticket PACSNP gom 1 dòng, cột F = "New product day 2 items".

⚠️ KHÔNG TỰ TÁCH 1 TASK THÀNH NHIỀU TASK:
Nếu người dùng nói làm 1 LOẠI task (vd "làm DFU cho A, B, C, D") thì đó là
1 TASK DUY NHẤT với description gộp TẤT CẢ ticket, KHÔNG tách thành
nhiều task. Đừng tự đoán INC → Issue Investigation, PACSDFUM → DFU
để tách ra. người dùng nói task gì thì DÙNG ĐÚNG task đó cho MỌI ticket
trong câu.
Ví dụ: "thứ 3 làm DFU cho INC002435, INC2943, PACSDFUM-4882" →
  1 task: DFU, description = "INC002435, INC2943, PACSDFUM-4882" (8h).
  KHÔNG tách INC ra Issue Investigation.

GIỜ: nếu người dùng nói "X tiếng/X giờ/Xh" → hours = X. Không nói → để null
(script tự chia đều 8h).

TIN NHẮN (ngày đã chuẩn hóa):
"{text}"

Trả JSON (không markdown):
{{"actions": [
  {{"type": "ADD_DAY|ADD_TASK|...",
    "date": "YYYY-MM-DD",
    "tasks": [{{"project": "...", "task": "...", "description": "...", "hours": null}}],
    "copy_from": "YYYY-MM-DD"}}
]}}
Nếu KHÔNG phải sửa timesheet: {{"actions": [], "not_action": true}}
Câu nhiều ngày ("thứ 2 tới thứ 5 nghỉ") → nhiều action, mỗi ngày 1 action."""


# ===========================================================================
# PARSE — bóc tin thành actions
# ===========================================================================
def parse_actions(text: str, config,
                  prev_days: list = None, today=None) -> tuple[list[Action], bool]:
    """Bóc 1 tin thành list Action. GỌI ai_client.generate_json.
    Trả (actions, is_not_action).
    Raise ai_client.AIError nếu AI lỗi.

    Xử CỤM NHIỀU NGÀY (nhóm A "nguyên tuần", nhóm B "thứ X tới thứ Y"):
    bung ra danh sách ngày, thay chỗ cụm bằng "các ngày: d1, d2..." để AI
    hiểu áp CÙNG nội dung cho tất cả ngày → nhiều action cùng task.

    prev_days: khi người dùng ĐÍNH CHÍNH action ("không phải, thay thế các ngày
    này thành..."), truyền danh sách ngày của bản trước để AI hiểu "các
    ngày này" là ngày nào (câu đính chính thường thiếu ngày cụ thể).
    """
    # today = ngày của TIN NHẮN (ghi chú thường truyền vào) → tin gửi 23:59 mà
    # bot xử lý sau nửa đêm / /retrynotes hôm sau vẫn hiểu "hôm nay" đúng
    today = today or date.today()
    raw = date_normalizer.fix_day_typos(text.strip())    # 'thử 2' → 'thứ 2'

    # Bung cụm nhiều ngày (nếu có). CHE cụm lại trước khi chuẩn hóa phần
    # còn lại — nếu không, normalize dịch "thứ 2 tới thứ 4 tuần trước"
    # thành "21/09 tới 16/09" (thứ 2 bị hiểu là tuần này) → AI nhận 2 thông
    # tin mâu thuẫn. Sau đó thay chỗ che bằng danh sách ngày CHÍNH XÁC.
    span_res = date_normalizer.expand_multi_day_span(raw, today)
    multi_days = span_res[0] if span_res else None
    multi_hint = ""
    if span_res:
        s, e = span_res[1]
        token = "XCUMNGAYX"
        masked = raw[:s] + token + raw[e:]
        normalized = date_normalizer.normalize_dates_in_text(masked, today)
        _thu = ["thứ Hai", "thứ Ba", "thứ Tư", "thứ Năm", "thứ Sáu"]
        pretty = ", ".join(f"{d.strftime('%d/%m/%Y')} ({_thu[d.weekday()]})"
                           for d in multi_days)
        normalized = normalized.replace(token, f"các ngày {pretty}")
        days_list = ", ".join(d.isoformat() for d in multi_days)
        multi_hint = (f"\n\nLƯU Ý: NGÀY CẦN GHI/SỬA (ngày đích) là ĐÚNG "
                      f"{len(multi_days)} ngày: {days_list}. Sinh 1 action cho "
                      f"MỖI ngày với CÙNG nội dung task. Ngày khác trong câu "
                      f"(nếu có, vd sau chữ 'giống') chỉ là NGÀY NGUỒN để copy.")
    else:
        normalized = date_normalizer.normalize_dates_in_text(raw, today)

    prev_hint = ""
    if prev_days:
        prev_hint = (f"\n\nĐÂY LÀ CÂU ĐÍNH CHÍNH cho lần sửa trước. Nếu câu "
                     f"nhắc 'các ngày này / những ngày này / các ngày trên' "
                     f"mà không nêu ngày cụ thể, hiểu là các ngày: "
                     f"{', '.join(prev_days)}. Sinh action MỚI cho các ngày "
                     f"đó theo đúng ý đính chính (vd 'thay thế thành X' = "
                     f"REPLACE_DAY).")
    prompt = _ACTION_PROMPT.format(
        today=today.isoformat(),
        task_rules=_tr.build_column_mapping_prompt(),
        text=normalized) + multi_hint + prev_hint
    result = ai_client.generate_json(
        prompt, purpose="chat", config=config, session="note_action")

    if result.get("not_action") or not result.get("actions"):
        return [], True

    actions = []
    for a in result.get("actions", []):
        atype = str(a.get("type", "")).strip().upper()
        if atype not in ALL_ACTIONS:
            continue
        try:
            day = date.fromisoformat(str(a["date"])) if a.get("date") else None
        except (ValueError, TypeError):
            day = None
        copy_from = None
        if a.get("copy_from"):
            try:
                copy_from = date.fromisoformat(str(a["copy_from"]))
            except (ValueError, TypeError):
                pass
        tasks = []
        for t in a.get("tasks", []):
            h = t.get("hours")
            tasks.append({
                "project": str(t.get("project") or "").strip(),
                "task": str(t.get("task") or "").strip(),
                "description": str(t.get("description") or "").strip(),
                "hours": (float(h) if h not in (None, "") else None),
            })
        actions.append(Action(type=atype, day=day, tasks=tasks,
                              copy_from=copy_from))

    if not actions:
        return [], True
    ensure_all_tickets(raw, actions)
    keep_full_description(raw, actions)
    apply_project_marker(raw, actions)            # task DỰ ÁN / WR (25-Sep)
    _task_from_head(raw, actions)                 # chữ trong MÔ TẢ không quyết task
    actions = _guard_explicit_dates(normalized, actions, raw, today)
    _guard_day_count(raw, today, span_res, actions)
    warn_bare_prefixes(raw, actions)
    return actions, False


_FREE_TEXT_TASKS = {"DFU", "SDF", "Issue Investigation", "Investigation/Assessment"}


# Dấu vết của bước chuẩn hóa ngày ("01/09/2026 (thứ Ba)") lọt vào mô tả
_NORM_ARTIFACT_RE = _re_mod.compile(r"\d{1,2}/\d{1,2}/\d{4}\s*\((?:thứ|chủ)[^)]*\)")


def keep_full_description(raw: str, actions: list, force: bool = False) -> None:
    """Chống AI RÚT GỌN mô tả dài (thêm 24-Sep). Cột F có thể 500-600 ký tự;
    AI bản lite hay "tóm tắt cho gọn" → mất chữ âm thầm (ensure_all_tickets
    chỉ bù MÃ ticket, không bù chữ).
    Cách làm: lấy lại đoạn mô tả NGUYÊN VĂN từ câu người dùng gõ (cùng luật
    rule_parser: "description là ..." hoặc từ ticket đầu tới hết câu). Nếu
    bản AI NGẮN hơn đáng kể → dùng bản nguyên văn + cảnh báo.
    CHỈ áp dụng khi cả câu chỉ có 1 LOẠI task (DFU/SDF/Issue/Investigation)
    — câu nhiều task thì không đoán được đoạn nào của task nào → bỏ qua.
    NP (cột F = constant) không đụng."""
    import rule_parser as _rp
    tasks = [t for a in actions for t in (a.tasks or [])]
    kinds = {t.get("task") for t in tasks}
    if not tasks or len(kinds) != 1 or kinds.pop() not in _FREE_TEXT_TASKS:
        return
    if any(_tr.get_desc_const(t.get("task", "")) and "PACSNP" in
           str(t.get("project", "")).upper() for t in tasks):
        return
    tickets = _tr.extract_tickets_from_note(raw)
    has_marker = _re_mod.search(r"(?:description|desc|mô\s*tả)\s*(?:là|:|=)", raw, _re_mod.I)
    if not tickets and not has_marker:
        return
    ref = _rp._description_from_text(raw, tickets)
    if not ref:
        return
    shortened, altered = 0, False
    for t in tasks:
        cur = _tr.normalize_ticket_text(t.get("description") or "")
        if cur == ref:
            continue
        if force:
            # rule_parser: mô tả lấy từ câu ĐÃ chuẩn hóa ngày → luôn thay bằng
            # nguyên văn (vd "between 01/09 and 08/09" không được thành
            # "01/09/2026 (thứ Ba)")
            t["description"] = ref
        elif len(cur) + 15 < len(ref):
            t["description"] = ref
            shortened = max(shortened, len(cur))
        elif _NORM_ARTIFACT_RE.search(cur) and not _NORM_ARTIFACT_RE.search(ref):
            t["description"] = ref
            altered = True
    a0 = actions[0]
    if shortened:
        a0.warning = ((a0.warning + " ") if a0.warning else "") + (
            f"AI đã RÚT GỌN mô tả ({shortened} → {len(ref)} ký tự) — mình dùng lại "
            "NGUYÊN VĂN bro gõ cho cột F.")
        log.warning("keep_full_description: AI rút gọn %d → %d ký tự", shortened, len(ref))
    if altered:
        a0.warning = ((a0.warning + " ") if a0.warning else "") + (
            "AI chép nhầm ngày dạng '01/09/2026 (thứ ...)' vào mô tả — mình dùng "
            "lại NGUYÊN VĂN bro gõ cho cột F.")


# ── Task DỰ ÁN / WR (thêm 25-Sep) ─────────────────────────────────────
# Cú pháp: "<ngày> dự án <TÊN>, <việc>, mô tả <MÔ TẢ>"
#   mốc tên : dự án | project | WR | work request   (tên ghi NGUYÊN VĂN)
#   việc    : coding/UT → Coding/UT · UAT → UAT Support · assess → Investigation/Assessment
#   mốc mô tả: mô tả | description | desc   (có "là"/":" hay không đều được)
#   ngăn bằng dấu phẩy (tên có phẩy → dùng "|")
# CHỈ chạy khi câu có mốc tên + task là Coding/UT / UAT / Assessment + KHÔNG
# có PACSNP (NP để luật NP lo). KHÔNG đụng DFU / SDF / Prod support / NP.
_PROJ_TASKS = (_tr.TASK_CODING_UT, _tr.TASK_UAT_SUPPORT, _tr.TASK_INVESTIGATION_ASSESSMENT,
               _tr.TASK_ISSUE_INVESTIGATION)   # prod issue CHO 1 DỰ ÁN (vd NP PACSNP-3083)
_PROJ_MARK_RE = _re_mod.compile(
    r"(?i)(?:^|[\s,;|])(?:dự\s*án|project|work\s+request|wr)\s*[:=]?\s+")
_PROJ_DESC_RE = _re_mod.compile(
    r"(?i)(?:^|[\s,;|])(?:mô\s*tả|description|desc)\s*(?:là|:|=)?\s*")


def parse_project_marker(raw: str):
    """(tên dự án, mô tả | None, phần còn lại để dò task) hoặc None."""
    m = _PROJ_MARK_RE.search(raw)
    if not m:
        return None
    rest = raw[m.end():]
    dm = _PROJ_DESC_RE.search(rest)
    head = rest[:dm.start()] if dm else rest
    desc = rest[dm.end():].strip().strip('"“”').strip() if dm else None
    cut = _re_mod.search(r"[,;|]", head)
    name = (head[:cut.start()] if cut else head).strip()
    task_part = raw[:m.start()] + " " + (head[cut.end():] if cut else "")
    if not name:
        return None
    return name, (desc or None), task_part


def apply_project_marker(raw: str, actions: list) -> None:
    """Câu có "dự án / project / WR <tên>" → cột D = tên NGUYÊN VĂN (chỉ viết
    hoa mã ticket), cột F = phần sau "mô tả" NGUYÊN VĂN. Áp cho MỌI action của
    câu nếu mỗi action có đúng 1 task thuộc Coding/UT / UAT / Assessment."""
    p = parse_project_marker(raw)
    if not p:
        return
    name, desc, task_part = p
    has_np = bool(_re_mod.search(r"(?i)\bpacsnp-?\d", raw))
    tasks = [t for a in actions for t in (a.tasks or [])]
    if not tasks or any(len(a.tasks or []) != 1 for a in actions if a.tasks):
        return
    rule = _tr.find_rule_by_keyword(task_part.lower())
    task_from_text = rule.task_name if rule and rule.task_name in _PROJ_TASKS else None
    for t in tasks:
        eff = task_from_text or t.get("task")
        if eff not in _PROJ_TASKS:
            continue                              # DFU/SDF/leave → không đụng
        if has_np and eff in _NP_TASKS:
            continue                              # NP Coding/Assess/UAT → luật NP lo
        t["task"] = eff
        t["project"] = _tr.normalize_ticket_text(name)
        t["_explicit_project"] = True             # validate KHÔNG ghi đè project_const
        if desc:
            t["description"] = _tr.normalize_ticket_text(desc)


_PROD_KW_RE = _re_mod.compile(
    r"(?i)\b(?:prod(?:uction)?\s+(?:issue(?:\s+check)?|check|fix)"
    r"|prod(?:uction)?\s+support\s+check)\b")


def _task_from_head(raw: str, actions: list) -> None:
    """Câu có mốc "mô tả / description" → TASK chỉ xét phần TRƯỚC mốc (25-Sep).
    Vd "SDF description là PL1800 - UAT support … production issue with SAR":
    AI có thể bị chữ "production issue" trong mô tả kéo sang Issue Investigation
    → nếu phần đầu có từ khóa task rõ ràng (SDF) mà AI ra task khác → theo phần
    đầu. Không đụng câu NP (PACSNP) hay câu có mốc dự án (đã xử lý riêng)."""
    if _re_mod.search(r"(?i)\bpacsnp-?\d|\bnp\b", raw) or _PROJ_MARK_RE.search(raw):
        return
    m = _PROJ_DESC_RE.search(raw)
    if m:
        rule = _tr.find_rule_by_keyword(raw[:m.start()].lower())
    else:
        # Không có mốc mô tả: CHỈ ép khi câu có từ khóa PRODUCTION rõ ràng
        # ("prod check cho Ticket#…" mà AI chọn Assessment) → Issue Investigation
        if not _PROD_KW_RE.search(raw):
            return
        rule = _tr.find_rule_by_keyword(raw.lower())
        if not rule or rule.task_name != _tr.TASK_ISSUE_INVESTIGATION:
            return
    if not rule or rule.desc_const:
        return
    for a in actions:
        if len(a.tasks or []) != 1:
            return
    for a in actions:
        t = a.tasks[0]
        if t.get("task") != rule.task_name:
            log.warning("AI chọn task %s nhưng đầu câu ghi %s → theo đầu câu",
                        t.get("task"), rule.task_name)
            t["task"] = rule.task_name
            if rule.project_const:
                t["project"] = rule.project_const


def warn_bare_prefixes(raw: str, actions: list) -> None:
    """Câu có tiền tố ticket THIẾU SỐ (vd "pacsdfum part e") → cảnh báo
    trong xem trước (vẫn ghi, đã viết hoa) để người dùng kiểm tra gõ sót số."""
    typos = _tr.find_prefix_typos(raw)
    if typos and actions:                              # (02-Oct) mã gõ đảo chữ PACS
        actions[0].warning = ((actions[0].warning + " ") if actions[0].warning else "") + (
            "✏️ Đã sửa mã gõ nhầm: " + ", ".join(dict.fromkeys(typos))
            + " — đúng thì nhắn ok, sai thì nói lại.")
        actions[0].needs_confirm = True
    bare = _tr.find_bare_prefixes(raw)
    if bare and actions:
        actions[0].warning = ((actions[0].warning + " ") if actions[0].warning else "") + (
            "⚠️ Ticket THIẾU SỐ: " + ", ".join(dict.fromkeys(bare))
            + " — gõ sót số ticket? Nói lại nếu cần sửa.")


_REL_DAY = {"hôm nay": 0, "hôm qua": -1, "hôm kia": -2, "ngày mai": 1, "mai": 1,
            "ngày mốt": 2, "mốt": 2}


def _relative_days(raw: str, today) -> tuple:
    """Ngày suy ra từ từ TƯƠNG ĐỐI trong PHẦN ĐÍCH của câu (mai, hôm qua, thứ X,
    CN...) + cờ 'câu có từ tương đối'. Bước chuẩn hóa KHÔNG đổi hết các từ này
    thành ngày cụ thể (vd 'mai') → phải tự tính, kẻo lớp chặn tưởng AI sai."""
    import re as _r
    from datetime import timedelta as _td
    low = date_normalizer._target_part(raw.lower())
    days, has_rel = set(), False
    for w, off in _REL_DAY.items():
        if _r.search(rf"(?<!\w){w}(?!\w)", low):
            days.add(today + _td(days=off)); has_rel = True
    for m in _r.finditer(r"\bthứ\s*(\w+)|\bchủ\s*nhật\b|\bcn\b", low):
        has_rel = True
        wd = 6 if m.group(1) is None else date_normalizer._THU_MAP.get(m.group(1))
        if wd is not None:
            mon = today - _td(days=today.weekday())
            days.update({mon + _td(days=wd), mon + _td(days=wd - 7), mon + _td(days=wd + 7)})
    return days, has_rel


def _guard_explicit_dates(normalized: str, actions: list, raw: str = "",
                          today=None) -> list:
    """Ngày ĐÍCH của AI phải khớp ngày trong câu (thêm 24-Sep).
    Vd "ngày 10/9 nghỉ bù nửa ngày…" → AI lite trả 24/09 (hôm nay) = SAI NGÀY.
    Ngày HỢP LỆ = ngày ghi rõ (dd/mm) ∪ ngày suy từ từ tương đối (mai, hôm qua,
    thứ X...). AI ra ngày ngoài tập đó:
      - câu có ĐÚNG 1 ngày ghi rõ và KHÔNG có từ tương đối → TỰ SỬA + cảnh báo
      - còn lại → KHÔNG tự sửa (có thể đoán sai): bắt xác nhận + cảnh báo
    (Sửa 24-Sep tối: bản đầu tự sửa cả khi câu có 'mai' → "mai nghỉ phép, 10/9
    làm SDF" bị dồn nghỉ phép ngày mai vào 10/9.)"""
    import rule_parser as _rp
    today = today or date.today()
    # CHỈ ngày ở PHẦN ĐÍCH (trước 'giống'): ngày sau 'giống' là ngày NGUỒN,
    # không được dùng để "sửa" ngày đích (vd "sửa thứ 2 tuần này làm giống
    # thứ 4 tuần trước" → không bao giờ đổi đích thành thứ 4 tuần trước)
    _tp = normalized[:len(date_normalizer._target_part(normalized.lower()))]
    explicit = sorted(set(_rp._extract_date(_tp)))
    if not explicit:
        return actions
    rel_days, has_rel = _relative_days(raw or normalized, today)
    allowed = set(explicit) | rel_days
    only = explicit[0] if (len(explicit) == 1 and not has_rel) else None
    for a in actions:
        if a.day is None or a.day in allowed or a.error:
            continue
        old = a.day
        if only is not None and only != getattr(a, "copy_from", None):
            a.day = only
            a.needs_confirm = True
            a.warning = ((a.warning + " ") if a.warning else "") + (
                f"⚠️ AI ghi nhầm ngày {old:%d/%m} — mình sửa về {only:%d/%m} "
                "đúng như câu bro gõ.")
            log.warning("AI trả ngày %s ngoài câu → sửa về %s", old, only)
        else:
            a.needs_confirm = True
            a.warning = ((a.warning + " ") if a.warning else "") + (
                f"⚠️ AI ra ngày {old:%d/%m} — câu KHÔNG nhắc ngày này. Kiểm tra "
                "kỹ, sai thì nói lại rõ ngày.")
            log.warning("AI trả ngày %s ngoài câu → bắt xác nhận", old)
    merged, by_day = [], {}
    for a in actions:
        key = (a.day, a.type)
        if (a.type in (ADD_DAY, REPLACE_DAY, ADD_TASK) and not a.error
                and key in by_day):
            base = by_day[key]
            base.tasks = list(base.tasks) + list(a.tasks)
            base.needs_confirm = base.needs_confirm or a.needs_confirm
            if a.warning and a.warning not in (base.warning or ""):
                base.warning = ((base.warning + " ") if base.warning else "") + a.warning
            continue
        by_day[key] = a
        merged.append(a)
    return merged


# Kiểu cụm SUY RA (không nói thẳng từng ngày) → LUÔN bắt xác nhận
_INFERRED_KINDS = {"week_bare", "week_all", "month", "month_week", "month_first_n"}


def _guard_day_count(raw: str, today: date, span_res, actions: list) -> None:
    """2 lớp chặn bung ngày quá tay (thêm 24-Sep):
    LỚP 2 — câu KHÔNG có cụm ngày mà AI trả NHIỀU ngày đích hơn số ngày câu
       nhắc tới (vd "thứ 3 tuần này làm SDF" → AI trả 5 ngày) → bắt xác
       nhận + cảnh báo. Ngày NGUỒN (copy_from) không tính.
    LỚP 3 — cụm kiểu SUY RA (tuần đứng một mình, hết tuần, cả tháng, tuần
       đầu tháng) hoặc > 5 ngày → LUÔN bắt xác nhận, kể cả ngày trống."""
    target_days = sorted({a.day for a in actions if a.day})
    if span_res:
        days, _, kind = span_res
        if kind in _INFERRED_KINDS or len(days) > 5:
            for a in actions:
                a.needs_confirm = True
            actions[0].warning = ((actions[0].warning + " ") if actions[0].warning else "") + (
                f"Mình hiểu câu này là {len(days)} ngày ({days[0]:%d/%m} → "
                f"{days[-1]:%d/%m}) — kiểm tra kỹ danh sách ngày trước khi 'ok'.")
        extra = [d for d in target_days if d not in set(days)]
        if extra:
            for a in actions:
                a.needs_confirm = True
            actions[0].warning = ((actions[0].warning + " ") if actions[0].warning else "") + (
                "⚠️ AI thêm ngày NGOÀI cụm bro nói: "
                + ", ".join(f"{d:%d/%m}" for d in extra) + " — kiểm tra lại.")
        return
    low = raw.lower()
    tgt = date_normalizer._target_part(low)
    refs = len(date_normalizer.DAY_REF_RE.findall(tgt))
    if len(target_days) > max(1, refs):
        for a in actions:
            a.needs_confirm = True
        actions[0].warning = ((actions[0].warning + " ") if actions[0].warning else "") + (
            f"⚠️ Câu chỉ nhắc {max(1, refs)} ngày nhưng AI ra {len(target_days)} "
            f"ngày ({', '.join(f'{d:%d/%m}' for d in target_days)}) — kiểm tra "
            "kỹ, nói lại nếu sai.")


def _rule_delete_actions(raw: str, low: str, today: date):
    """Luật dự phòng cho câu XÓA (thêm 24-Sep). CHỈ xóa CẢ NGÀY, cho ngày
    ghi rõ hoặc cụm ngày bung được. Kết quả vẫn qua validate + chặn ngày đã
    gửi + XEM TRƯỚC + 'ok' như mọi action khác — không bao giờ xóa thẳng.
      - xóa 1 TASK trong ngày ("xóa task DFU thứ 3") → để AI (dễ nhầm)
      - không rõ ngày ("xóa cả tháng") → từ chối, không đoán"""
    import re as _re
    import rule_parser as _rp
    rest = _re.sub(r"\b(xóa|xoá|bỏ ngày|delete)\b", " ", low)
    if _re.search(r"\b(task|việc)\b", rest) or _tr.find_rule_by_keyword(rest):
        return [], "câu xóa 1 TASK trong ngày cần AI (luật chỉ xóa được CẢ NGÀY)"
    span = date_normalizer.expand_multi_day_span(raw, today)
    if span:
        days = list(span[0])
    else:
        days = _rp._extract_date(date_normalizer.normalize_dates_in_text(raw, today))
    days = sorted(set(days))
    if not days:
        return [], "không rõ xóa NGÀY nào — ghi rõ ngày (vd: xóa ngày 22/9)"
    return [Action(type=DELETE_DAY, day=d) for d in days], ""


# ── Luật dự phòng hiểu SỐ GIỜ + câu NHIỀU TASK (25-Sep) ─────────────────
_HALF_WORD_RE = _re_mod.compile(r"(?i)\b(sáng|chiều|trưa|tối)\s+(nay|mai|qua)\b")
_RULE_HOURS_RE = _re_mod.compile(r"(?i)\b(\d+(?:[.,]\d+)?)\s*(?:h|giờ|tiếng|hours?)\b")


def _rule_pre_text(text: str):
    """Chuẩn bị câu cho luật dự phòng: 'sáng/chiều nay' → 'hôm nay' (+ gợi ý
    nửa ngày), 'sáng/chiều mai' → 'ngày mai', 'nửa ngày / half day' → '4 tiếng'.
    Trả (câu mới, half_hint)."""
    half = bool(_HALF_WORD_RE.search(text))
    t = _HALF_WORD_RE.sub(lambda m: {"nay": "hôm nay", "mai": "ngày mai",
                                     "qua": "hôm qua"}[m.group(2).lower()], text)
    t2 = _re_mod.sub(r"(?i)\bnửa\s+ngày\b|\bhalf\s*-?\s*day\b", "4 tiếng", t)
    return t2, half and t2 == t      # có "4 tiếng" thật rồi thì không cần gợi ý


_SEG_LEAD_RE = None


def _seg_starts_with_task(low: str) -> bool:
    """Phần câu BẮT ĐẦU bằng từ khóa task (có thể có 'X tiếng làm' / ngày ở trước)."""
    global _SEG_LEAD_RE
    if _SEG_LEAD_RE is None:
        alts = "|".join(sorted({_re_mod.escape(k) for r_ in _tr.TASK_RULES for k in r_.keywords}, key=len, reverse=True))
        _SEG_LEAD_RE = _re_mod.compile(
            r"^\s*(?:\d+(?:[.,]\d+)?\s*(?:h|giờ|tiếng)\s*)?(?:làm|thì|là)?\s*"
            r"(?:hôm nay|hôm qua|ngày mai|ngày \d{1,2}/\d{1,2}(?:/\d{4})?|thứ \w+)?\s*"
            r"(?:làm\s+)?(?:" + alts + r")(?!\w)")
    return bool(_SEG_LEAD_RE.match(low))


def _rule_multi_tasks(raw: str, day, today):
    """Câu NHIỀU TASK có số giờ → list task (project/task/description/hours),
    hoặc None nếu không phải. Tách theo , ; 'và' 'còn (lại)'. Phần có từ khóa
    task Ở ĐẦU phần (hoặc có số giờ + từ khóa) mở task mới; phần còn lại (vd
    ticket nối tiếp 'inc2495', 'Ticket# 479829 - investigate softlock') gộp vào
    task trước → 'DFU pacsdfum-1, inc2495' KHÔNG bị tách. CHỈ chạy khi câu có
    ghi số giờ. Phần không ghi giờ → chia đều số giờ còn lại cho đủ 8."""
    import rule_parser as _rp
    if not _RULE_HOURS_RE.search(raw):
        return None
    parts = [p for p in _re_mod.split(r"\s*(?:[,;]|\bvà\b|\bcòn(?:\s+lại)?\b)\s*", raw) if p.strip()]
    segs = []
    for p in parts:
        low = p.lower()
        rule = _tr.find_rule_by_keyword(low)
        # CHỈ mở task mới khi từ khóa task Ở ĐẦU phần ("4 tiếng làm DFU …",
        # "nghỉ phép 4 tiếng"); từ khóa nằm giữa ("Ticket# 1 - investigate …")
        # là mô tả của task trước → gộp
        opens = bool(rule) and _seg_starts_with_task(low)
        if opens or not segs:
            segs.append(p)
        else:
            segs[-1] = segs[-1] + ", " + p
    if len(segs) < 2:
        return None
    tasks = []
    for sgm in segs:
        sub = date_normalizer.normalize_hours_in_text(
            date_normalizer.normalize_dates_in_text(f"ngày {day:%d/%m/%Y} {sgm}", today))
        r = _rp.parse_note_to_dict(sub)
        if r.get("status") not in (_rp.PARSE_OK, _rp.PARSE_UNSURE) or not r.get("entries"):
            return None
        en = r["entries"][0]
        hm = _RULE_HOURS_RE.search(sgm)
        tk = {"project": en.get("project", ""), "task": en.get("task", ""),
              "description": "" if en.get("task") in _ticketless()
              else en.get("description", ""),
              "hours": float(hm.group(1).replace(",", ".")) if hm else None}
        # phần này là DỰ ÁN / WR ("4 tiếng WR PACSPOSCM-2012 AML screening")
        apply_project_marker(sgm, [Action(type=ADD_DAY, day=day, tasks=[tk])])
        tasks.append(tk)
    known = sum(x["hours"] for x in tasks if x["hours"] is not None)
    unknown = [x for x in tasks if x["hours"] is None]
    for x in unknown:
        x["hours"] = max(0.0, round((8.0 - known) / len(unknown), 2))
    return tasks


def actions_from_rule_parser(text: str, today: date = None):
    """ĐƯỜNG DỰ PHÒNG khi AI lỗi (thêm 24-Sep): bóc bằng rule_parser (0 AI)
    rồi đổi thành Action, để đi qua CÙNG validate / chặn ngày đã gửi /
    preview như đường AI. Trước đây rule_parser ghi THẲNG parsed_days,
    không hỏi, không kiểm tra.
    Trả (actions, lý_do_nếu_không_bóc_được)."""
    text = date_normalizer.fix_day_typos(text)            # 'thử 2' → 'thứ 2'
    import re as _re
    import rule_parser as _rp
    today = today or date.today()
    text, half_hint = _rule_pre_text(text)                # sáng nay → hôm nay, nửa ngày → 4 tiếng
    raw = text.strip()
    low = raw.lower()
    if _re.search(r"\b(xóa|xoá|bỏ ngày|delete)\b", low):
        return _rule_delete_actions(raw, low, today)
    if "giống" in low:
        return [], "câu 'giống ngày khác' cần AI"
    span = date_normalizer.expand_multi_day_span(raw, today)
    if span:
        s, e = span[1]
        raw = raw[:s] + ", ".join(d.strftime("%d/%m/%Y") for d in span[0]) + raw[e:]
    norm = date_normalizer.normalize_hours_in_text(
        date_normalizer.normalize_dates_in_text(raw, today))
    # Câu NHIỀU TASK có số giờ: thử TRƯỚC (rule_parser cả câu sẽ từ chối
    # "nhiều task trong 1 ngày, để AI xử")
    _mdays = sorted(set(_rp._extract_date(norm)))
    _multi = _rule_multi_tasks(raw, _mdays[0], today) if _mdays else None
    if _multi:
        if _re.search(r"\b(thêm|nữa|cũng làm)\b", low):
            _atype = ADD_TASK
        elif _re.search(r"\b(sửa|đổi|thay|chỉ|thành|lại)\b", low):
            _atype = REPLACE_DAY
        else:
            _atype = ADD_DAY
        acts = [Action(type=_atype, day=d, tasks=[dict(x) for x in _multi]) for d in _mdays]
        ensure_all_tickets(norm, acts)
        warn_bare_prefixes(raw, acts)
        for a in acts:
            a.warning = ((a.warning + " ") if a.warning else "") + (
                "⚠️ AI đang lỗi — đây là bóc tách bằng RULE (kém thông minh hơn "
                "AI), kiểm tra KỸ trước khi 'ok'.")
        return acts, ""
    r = _rp.parse_note_to_dict(norm)
    if r.get("status") not in (_rp.PARSE_OK, _rp.PARSE_UNSURE) or not r.get("entries"):
        return [], r.get("fail_reason") or "rule không nhận ra ngày/task"
    explicit_h = bool(_re.search(r"\d+(?:[.,]\d+)?\s*h\b", norm, _re.IGNORECASE))
    if _re.search(r"\b(thêm|nữa|cũng làm)\b", low):
        atype = ADD_TASK
    elif _re.search(r"\b(sửa|đổi|thay|chỉ|thành|lại)\b", low):
        atype = REPLACE_DAY
    else:
        atype = ADD_DAY
    if True:
        by_day = {}
        h_val = _rp._extract_hours(norm) if explicit_h else (4.0 if half_hint else None)
        for en in r["entries"]:
            by_day.setdefault(en["date"], []).append({
                "project": en.get("project", ""), "task": en.get("task", ""),
                "description": en.get("description", ""),
                # số giờ người dùng ghi → dùng ĐÚNG, kể cả ngày nghỉ (rule_parser
                # tự ép nghỉ = 8h → "nghỉ phép 4 tiếng" từng thành 8h)
                "hours": h_val})
        acts = [Action(type=atype, day=d, tasks=ts) for d, ts in sorted(by_day.items())]
        ensure_all_tickets(norm, acts)
        keep_full_description(text.strip(), acts, force=True)   # cột F = nguyên văn
        apply_project_marker(text.strip(), acts)                # task DỰ ÁN / WR
    warn_bare_prefixes(raw, acts)
    for a in acts:
        a.warning = ((a.warning + " ") if a.warning else "") + (
            "⚠️ AI đang lỗi — đây là bóc tách bằng RULE (kém thông minh hơn "
            "AI), kiểm tra KỸ trước khi 'ok'.")
    return acts, ""


_TICKETLESS_TASKS = None


def _ticketless() -> set:
    global _TICKETLESS_TASKS
    if _TICKETLESS_TASKS is None:
        _TICKETLESS_TASKS = {_tr.TASK_ANNUAL_LEAVE, _tr.TASK_PUBLIC_HOLIDAY,
                             _tr.TASK_SPECIAL_LEAVE, _tr.TASK_SICK_LEAVE}
    return _TICKETLESS_TASKS


def _put_ticket(field: str, tk: str) -> str:
    """Thêm ticket `tk` vào 1 ô. Nếu ô đã có bản THIẾU 'PART X' của nó
    (AI làm rơi 'part b') → thay bằng bản đủ, không thêm trùng."""
    import re as _re
    base = tk.split(" PART ")[0]
    if tk != base:
        pat = _re.compile(r"\b" + _re.escape(base) + r"\b(?!\s+PART\b)",
                          _re.IGNORECASE)
        if pat.search(field or ""):
            return pat.sub(tk, field, count=1)
    return f"{field}, {tk}" if (field or "").strip() else tk


def _tkey(tk: str) -> str:
    """Khóa so sánh ticket: bỏ dấu gạch + khoảng trắng, viết hoa
    (PACSNP-3892 ≡ PACSNP3892 ≡ pacsnp 3892; 'Part B' vẫn tính)."""
    return _re_mod.sub(r"[\s\-]", "", (tk or "").upper())


def restore_ticket_forms(want: list, actions: list) -> None:
    """AI viết lại mã khác dạng người dùng gõ (bỏ/thêm dấu gạch, viết thường…) →
    đổi về ĐÚNG dạng người dùng gõ (đã viết hoa). Chỉ đổi mã TRÙNG khóa với mã
    trong câu gốc; mã khác giữ nguyên (thêm 25-Sep)."""
    forms = {_tkey(w): w for w in want}

    def fix(s: str) -> str:
        if not s:
            return s
        return _tr.TICKET_PART_RE.sub(
            lambda m: forms.get(_tkey(_tr.canon_ticket(m.group(0))), m.group(0)), s)
    for a in actions:
        for t in a.tasks or []:
            for k in ("project", "description"):
                if t.get(k):
                    t[k] = fix(t[k])


def ensure_all_tickets(text: str, actions: list) -> None:
    """LƯỚI AN TOÀN (thêm 24-Sep): AI (nhất là bản lite) có thể bỏ sót
    ticket hoặc làm rơi 'part b'. So ticket trong câu GỐC với TOÀN BỘ kết
    quả (mọi ngày gộp lại — câu nhiều ngày mỗi ngày 1 ticket là bình
    thường, không được coi là thiếu). Ticket thiếu:
      - biết chắc chỗ đặt (chỉ 1 ngày, hoặc cụm nhiều ngày CÙNG nội dung;
        và mỗi ngày ĐÚNG 1 task nhận ticket) → tự bổ sung (NP → cột D,
        còn lại → cột F) + cảnh báo trong preview
      - không chắc → KHÔNG đoán, bắt người dùng xác nhận
    Sửa `actions` tại chỗ."""
    want = _tr.extract_tickets_from_note(text)
    if not want:
        return
    acts = [a for a in actions
            if a.type not in (DELETE_DAY, DELETE_TASK, COPY_FROM, NOT_ACTION)
            and any(t.get("task") not in _ticketless() for t in a.tasks)]
    if not acts:
        return
    # 1) Trả mã về ĐÚNG dạng người dùng gõ (AI hay bỏ dấu gạch: PACSNP-3892 → PACSNP3892)
    restore_ticket_forms(want, acts)
    got = _tr.extract_tickets_from_note(" ".join(
        f"{t.get('project', '')} {t.get('description', '')}"
        for a in acts for t in a.tasks))
    have = {_tkey(tk) for tk in got}
    want_keys = {_tkey(tk) for tk in want}
    # 2) Mã LẠ AI tự thêm (không có trong câu người dùng gõ, vd PACSNP8994) → cảnh báo
    extra = [tk for tk in dict.fromkeys(got) if _tkey(tk) not in want_keys]
    if extra:
        acts[0].needs_confirm = True
        acts[0].warning = ((acts[0].warning + " ") if acts[0].warning else "") + (
            "⚠️ AI thêm mã KHÔNG có trong câu bro gõ: " + ", ".join(extra)
            + " — kiểm tra kỹ, sai thì nói lại hoặc 'hủy'.")
        log.warning("ensure_all_tickets: AI thêm mã lạ %s", extra)
    # 3) So KHÔNG phân biệt dấu gạch / khoảng trắng / hoa-thường
    missing = [tk for tk in want if _tkey(tk) not in have]
    if not missing:
        return
    sigs = {tuple((t.get("task"), t.get("project")) for t in a.tasks) for a in acts}
    single_slot = all(sum(t.get("task") not in _ticketless() for t in a.tasks) == 1
                      for a in acts)
    if len(sigs) == 1 and single_slot:
        for a in acts:
            t = next(t for t in a.tasks if t.get("task") not in _ticketless())
            for tk in missing:
                is_np = (tk.startswith("PACSNP") and t.get("task") in _NP_TASKS)
                key = "project" if is_np else "description"
                t[key] = _put_ticket(t.get(key, ""), tk)
            a.warning = ((a.warning + " ") if a.warning else "") + (
                "AI bỏ sót ticket, mình đã TỰ BỔ SUNG: "
                + ", ".join(missing) + " — kiểm tra lại giúp mình.")
    else:
        acts[0].needs_confirm = True
        acts[0].warning = ((acts[0].warning + " ") if acts[0].warning else "") + (
            "⚠️ AI bỏ sót ticket: " + ", ".join(missing)
            + " — không rõ thuộc ngày/task nào, bro nói lại rõ hơn hoặc sửa tay.")
    log.warning("ensure_all_tickets: thiếu %s", missing)


# ===========================================================================
# VALIDATE — kiểm tra + tự sửa action + đánh dấu cần xác nhận
# ===========================================================================
def validate_actions(actions: list[Action], parsed_days: dict,
                     config) -> list[Action]:
    """Validate chặt từng action so với parsed_days hiện có.
    - Tự sửa action sai (ADD_TASK ngày chưa có → ADD_DAY...).
    - Đánh dấu needs_confirm cho action nguy hiểm.
    - Đánh dấu error nếu không thực thi được.
    parsed_days: dict {iso_date: {"entries": [...]}}
    """
    hours_per_day = config.get("hours_per_day") or 8

    for act in actions:
        day_iso = act.day.isoformat() if act.day else None
        day_exists = day_iso in parsed_days if day_iso else False

        # --- Không có ngày ---
        if act.day is None and act.type != NOT_ACTION:
            act.error = "Chưa rõ ngày nào — nói rõ ngày giúp mình."
            continue

        # --- COPY_FROM ---
        if act.type == COPY_FROM:
            src_iso = act.copy_from.isoformat() if act.copy_from else None
            if not src_iso or src_iso not in parsed_days:
                act.error = (f"Không có dữ liệu ngày nguồn "
                             f"{act.copy_from} để copy.")
                continue
            # Copy entries từ ngày nguồn
            src_entries = parsed_days[src_iso].get("entries", [])
            act.tasks = [dict(e) for e in src_entries]
            # Nếu ngày đích đã có → hỏi ghi đè
            if day_exists:
                act.needs_confirm = True
                act.confirm_msg = (
                    f"Ngày {_dmy(act.day)} đã có task. "
                    f"Ghi đè bằng bản copy từ {_dmy(act.copy_from)}?")
            continue

        # --- DELETE_DAY / DELETE_TASK ---
        if act.type in (DELETE_DAY, DELETE_TASK):
            if not day_exists:
                act.error = f"Không thấy ngày {_dmy(act.day)} để xóa."
                continue
            act.needs_confirm = True
            if act.type == DELETE_DAY:
                act.confirm_msg = f"Chắc muốn XÓA cả ngày {_dmy(act.day)}?"
            else:
                tname = act.tasks[0]["task"] if act.tasks else "?"
                act.confirm_msg = (f"Chắc muốn xóa task '{tname}' "
                                   f"ngày {_dmy(act.day)} (giữ task khác)?")
            continue

        # --- ADD_TASK: ngày chưa có → tự đổi ADD_DAY ---
        if act.type == ADD_TASK and not day_exists:
            act.type = ADD_DAY
            log.debug("ADD_TASK ngày %s chưa có → tự đổi ADD_DAY", day_iso)

        # --- REPLACE_DAY / MODIFY_TASK: ngày chưa có → ADD_DAY ---
        if act.type in (REPLACE_DAY, MODIFY_TASK) and not day_exists:
            act.type = ADD_DAY
            log.debug("%s ngày %s chưa có → tự đổi ADD_DAY",
                      act.type, day_iso)

        # --- CHẶN tasks rỗng cho action GHI (tránh xóa sạch ngày do AI bóc thiếu) ---
        if act.type in (ADD_DAY, ADD_TASK, REPLACE_DAY, MODIFY_TASK) \
                and not act.tasks:
            act.error = (f"Không rõ task nào cho ngày {_dmy(act.day)} — "
                         "nói rõ task giúp mình (muốn xóa thì nói 'xóa').")
            continue

        # --- ADD_DAY: ngày đã có → hỏi ghi đè ---
        if act.type == ADD_DAY and day_exists:
            act.needs_confirm = True
            act.confirm_msg = (
                f"Ngày {_dmy(act.day)} đã có task rồi. "
                f"Chắc muốn GHI ĐÈ thành task mới?")

        # --- REPLACE_DAY: ngày đã có → hỏi ghi đè ---
        if act.type == REPLACE_DAY and day_exists:
            old = parsed_days[day_iso].get("entries", [])
            old_desc = ", ".join(e.get("task", "") for e in old)
            act.needs_confirm = True
            act.confirm_msg = (
                f"Ngày {_dmy(act.day)} đang có: {old_desc}. "
                f"Ghi đè thành task mới?")

        # --- ADD_TASK: task trùng D/E/F → hỏi ---
        if act.type == ADD_TASK and day_exists and act.tasks:
            existing = parsed_days[day_iso].get("entries", [])
            for nt in act.tasks:
                if _task_exists(nt, existing):
                    act.needs_confirm = True
                    act.confirm_msg = (
                        f"Task '{nt['task']}' (D/E/F giống) đã có ngày "
                        f"{_dmy(act.day)}. Chắc muốn thêm nữa?")

        # --- Chuẩn hóa task name + validate hours + D/E/F ---
        if act.tasks and act.type in (ADD_DAY, ADD_TASK, REPLACE_DAY,
                                      MODIFY_TASK):
            import task_names as _tn
            for t in act.tasks:
                # E5: chuẩn hóa task name về đúng chuẩn (coding/ut → Coding/UT)
                if t.get("task"):
                    norm = _tn.normalize_task_name(t["task"])
                    if norm:
                        t["task"] = norm
                # Tự áp project_const + desc_const từ task_rules
                # (Annual Leave → project=Annual Leave; DFU → Production Support;
                #  NP Coding/UT → desc="New product day 2 items")
                if t.get("task"):
                    pc = _tr.get_project_const(t["task"])
                    # task có project cố định → ghi đè; TRỪ khi người dùng chỉ định
                    # rõ dự án ("prod issue, WR PACSNP-3083, mô tả …") — 25-Sep
                    if pc and not t.get("_explicit_project"):
                        t["project"] = pc
                    dc = _tr.get_desc_const(t["task"])
                    if dc and not t.get("description"):
                        t["description"] = dc
                # E4: chặn hours âm hoặc phi lý
                h = t.get("hours")
                if h is not None and (h < 0 or h > 24):
                    act.error = (f"Giờ {h} không hợp lệ cho task "
                                 f"'{t.get('task','')}' (phải 0-24).")
                    break
            if act.error:
                continue
            # Validate D/E/F
            for t in act.tasks:
                if not t.get("task"):
                    continue
                errs = _tr.validate_entry(
                    t.get("project", ""), t.get("task", ""),
                    t.get("description", ""),
                    t.get("hours") or 8, is_friday=False)
                hard = [e for e in errs if "cột E" in e or "cột D" in e]
                if hard:
                    act.error = "; ".join(hard)

    _warn_public_holidays(actions, config)
    return actions


def _warn_public_holidays(actions: list, config) -> None:
    """Ghi / sửa / copy việc vào NGÀY LỄ (lịch MOM) — thêm 25-Sep.
    CẢNH BÁO, KHÔNG CHẶN: bắt xem trước + 'ok' (kể cả ngày đang trống, vốn
    được ghi thẳng) và thêm 1 dòng báo ngày lễ. Task toàn là 'Public Holiday'
    hoặc lệnh XÓA → không cảnh báo. Dùng chung ghi chú thường, /edittimesheet
    và luật dự phòng (đều gọi validate_actions)."""
    try:
        import sg_holidays
    except Exception:  # noqa: BLE001
        return
    for a in actions:
        if a.error or a.day is None or a.type in (DELETE_DAY, DELETE_TASK):
            continue
        # CÙNG hàm với bước soạn nháp (workday_holidays): đã áp luật lễ CHỦ NHẬT
        # → nghỉ bù THỨ HAI, lễ thứ 7 → không tính. (Sửa 25-Sep: bản đầu tra
        # lịch MOM gốc → thứ 2 nghỉ bù Deepavali 9/11 KHÔNG được cảnh báo.)
        try:
            name = sg_holidays.workday_holidays(a.day, a.day, config=config).get(a.day)
        except Exception as e:  # noqa: BLE001 — thiếu lịch lễ không được làm hỏng việc ghi
            log.debug("Không đọc được lịch lễ %s (%s)", a.day, e)
            name = None
        if not name:
            continue
        tasks = a.tasks or []
        if tasks and all(t.get("task") == _tr.TASK_PUBLIC_HOLIDAY for t in tasks):
            continue
        a.needs_confirm = True
        a.warning = ((a.warning + " ") if a.warning else "") + (
            f"🎌 {_dmy(a.day)} là NGÀY LỄ ({name}). Bro vẫn đi làm ngày này? "
            "Nhắn 'ok' để ghi như trên, hoặc nói sửa lại nội dung khác.")


def _task_exists(new_task: dict, existing: list) -> bool:
    """True nếu task mới trùng D/E/F với task đã có."""
    for e in existing:
        if (e.get("project", "").strip().lower() == new_task["project"].strip().lower()
                and e.get("task", "").strip().lower() == new_task["task"].strip().lower()
                and e.get("description", "").strip().lower() == new_task["description"].strip().lower()):
            return True
    return False


def _dmy(d: date) -> str:
    thu = ["thứ Hai", "thứ Ba", "thứ Tư", "thứ Năm",
           "thứ Sáu", "thứ Bảy", "CN"]
    return f"{thu[d.weekday()]} {d.strftime('%d/%m/%Y')}"


# ===========================================================================
# APPLY — thực thi actions lên parsed_days (dict), trả parsed_days mới
# ===========================================================================
def apply_actions(actions: list[Action], parsed_days: dict,
                  config) -> dict:
    """Thực thi các action đã validate lên parsed_days.
    parsed_days: dict {iso: {"entries": [...]}} — SẼ BỊ SỬA (copy trước).
    Trả {"parsed_days": dict mới, "touched": [date], "summary": [str]}.
    Bỏ qua action có error.
    """
    hours_per_day = config.get("hours_per_day") or 8
    pd = {k: {"entries": [dict(e) for e in v.get("entries", [])]}
          for k, v in parsed_days.items()}   # deep-ish copy
    touched = []
    summary = []

    for act in actions:
        if act.error or act.type == NOT_ACTION:
            continue
        day_iso = act.day.isoformat() if act.day else None
        if not day_iso:
            continue

        if act.type == DELETE_DAY:
            pd.pop(day_iso, None)
            touched.append(act.day)
            summary.append(f"Đã xóa ngày {_dmy(act.day)}")
            continue

        if act.type == DELETE_TASK:
            if day_iso in pd and act.tasks:
                tname = act.tasks[0]["task"].strip().lower()
                pd[day_iso]["entries"] = [
                    e for e in pd[day_iso]["entries"]
                    if e.get("task", "").strip().lower() != tname]
                if not pd[day_iso]["entries"]:
                    pd.pop(day_iso, None)
                    summary.append(f"Đã xóa task, ngày {_dmy(act.day)} "
                                   "giờ trống → xóa luôn ngày")
                else:
                    # Reset giờ task còn lại (trừ leave) để chia lại đủ 8h
                    for e in pd[day_iso]["entries"]:
                        if e.get("task") not in (_tr.TASK_ANNUAL_LEAVE,
                                                 _tr.TASK_PUBLIC_HOLIDAY,
                                                 _tr.TASK_SPECIAL_LEAVE,
                                         _tr.TASK_SICK_LEAVE):
                            e["hours"] = None
                    _, warn = _rebalance(pd[day_iso]["entries"], hours_per_day)
                    msg = f"Đã xóa task khỏi ngày {_dmy(act.day)}"
                    if warn:
                        msg += f" ⚠️ {warn}"
                    summary.append(msg)
                touched.append(act.day)
            continue

        if act.type in (ADD_DAY, REPLACE_DAY, COPY_FROM):
            # Ghi đè cả ngày = tasks mới
            entries = [_norm_task(t, act.day) for t in act.tasks]
            _, warn = _rebalance(entries, hours_per_day)
            pd[day_iso] = {"entries": entries}
            touched.append(act.day)
            msg = f"Đã ghi ngày {_dmy(act.day)} ({len(entries)} task)"
            if warn:
                msg += f" ⚠️ {warn}"
            summary.append(msg)
            continue

        if act.type == ADD_TASK:
            # Thêm task, giữ task cũ. Chia lại giờ: task MỚI có giờ chỉ
            # định thì giữ, các task còn lại (cũ + mới không giờ) chia đều.
            if day_iso not in pd:
                pd[day_iso] = {"entries": []}
            # Reset giờ task CŨ về None để chia lại (trừ leave luôn 8h)
            for e in pd[day_iso]["entries"]:
                if e.get("task") not in (_tr.TASK_ANNUAL_LEAVE,
                                         _tr.TASK_PUBLIC_HOLIDAY,
                                         _tr.TASK_SPECIAL_LEAVE,
                                         _tr.TASK_SICK_LEAVE):
                    e["hours"] = None
            for t in act.tasks:
                pd[day_iso]["entries"].append(_norm_task(t, act.day))
            _, warn = _rebalance(pd[day_iso]["entries"], hours_per_day)
            touched.append(act.day)
            msg = f"Đã thêm task vào ngày {_dmy(act.day)}"
            if warn:
                msg += f" ⚠️ {warn}"
            summary.append(msg)
            continue

        if act.type == MODIFY_TASK:
            # Sửa task cùng tên (cột E), hoặc thêm nếu không thấy
            if day_iso not in pd:
                pd[day_iso] = {"entries": []}
            for nt in act.tasks:
                replaced = False
                for i, e in enumerate(pd[day_iso]["entries"]):
                    if e.get("task", "").lower() == nt["task"].lower():
                        pd[day_iso]["entries"][i] = _norm_task(nt, act.day)
                        replaced = True
                        break
                if not replaced:
                    pd[day_iso]["entries"].append(_norm_task(nt, act.day))
            _, warn = _rebalance(pd[day_iso]["entries"], hours_per_day)
            touched.append(act.day)
            msg = f"Đã sửa task ngày {_dmy(act.day)}"
            if warn:
                msg += f" ⚠️ {warn}"
            summary.append(msg)
            continue

    return {"parsed_days": pd, "touched": touched, "summary": summary}


_NP_TASKS = (_tr.TASK_CODING_UT, _tr.TASK_INVESTIGATION_ASSESSMENT,
             _tr.TASK_UAT_SUPPORT)
NP_DESC_CONST = "New product day 2 items"


def _norm_task(t: dict, day: date) -> dict:
    """Chuẩn hóa 1 task entry cho parsed_days.
    - Viết hoa MÃ ticket ở cột D và cột F; chữ mô tả khác GIỮ NGUYÊN.
    - NP task (Coding/UT + Investigation/Assessment có ticket PACSNP ở
      cột D): đảm bảo description = constant, ticket NP nằm ở cột D.
    """
    project = _uppercase_tickets(t.get("project", ""))
    task = t.get("task", "")
    desc = _uppercase_tickets(t.get("description", ""))

    # NP task (Coding/UT, Investigation/Assessment, UAT Support) có ticket
    # PACSNP ở BẤT KỲ cột nào → cột D = mọi PACSNP gom 1 dòng (viết hoa, bỏ
    # trùng), cột F = constant NP. (Sửa 25-Sep: trước chỉ chạy khi PACSNP ĐÃ
    # ở cột D, và Investigation/Assessment + UAT không lấy được constant.)
    if task in _NP_TASKS:
        import re as _re
        np_re = r"\bPACSNP-?\d{2,6}\b"
        found = (_re.findall(np_re, project, flags=_re.IGNORECASE)
                 + _re.findall(np_re, desc, flags=_re.IGNORECASE))
        if found:
            seen, tks = set(), []
            for tk in found:
                if tk.upper() not in seen:
                    seen.add(tk.upper()); tks.append(tk.upper())
            project = ", ".join(tks)
            desc = NP_DESC_CONST

    return {
        "date": day.isoformat(),
        "project": project,
        "task": task,
        "description": desc,
        "hours": t.get("hours"),
    }


def _uppercase_tickets(desc: str) -> str:
    """Viết HOA ticket (kèm 'PART X') — dùng định nghĩa ticket chung ở
    task_rules (có/không gạch, INC/PACS/CHG/REQ)."""
    return _tr.normalize_ticket_text(desc)


def _rebalance(entries: list, hours_per_day: int) -> tuple[bool, str]:
    """Chia lại giờ cho các entry trong 1 ngày (in-place).
    Dùng validator.split_hours: task có giờ giữ nguyên, còn lại chia đều.
    Trả (ok, warning): warning != "" nếu tổng giờ bất thường (> hoặc < 8h)."""
    if not entries:
        return True, ""
    balanced, err = validator.split_hours(entries, hours_per_day)
    if err:
        # Không chia được (vd tổng cố định > 8h) — giữ giờ đã có, task
        # chưa giờ = 0, KHÔNG đánh rớt. Cảnh báo để người dùng biết.
        for e in entries:
            if e.get("hours") is None:
                e["hours"] = 0.0
        total = sum(float(e.get("hours") or 0) for e in entries)
        return False, (f"Tổng giờ = {total:g}h (không khớp {hours_per_day}h) "
                       f"— {err}")
    entries[:] = balanced
    total = sum(float(e.get("hours") or 0) for e in balanced)
    if abs(total - hours_per_day) > 0.01:
        return True, f"Tổng giờ = {total:g}h (khác {hours_per_day}h)"
    return True, ""


# ===========================================================================
# FORMAT — preview + kết quả
# ===========================================================================
# Verb user-friendly cho từng action (KHÔNG hiện tên kỹ thuật REPLACE_DAY...)
_ACTION_VERB = {
    ADD_DAY:     "Ghi ngày (ngày chưa có)",
    ADD_TASK:    "Thêm task vào ngày (giữ task cũ)",
    REPLACE_DAY: "Sửa lại cả ngày (ghi đè task cũ)",
    MODIFY_TASK: "Sửa task trong ngày",
    DELETE_DAY:  "XÓA cả ngày",
    DELETE_TASK: "Xóa 1 task trong ngày",
    COPY_FROM:   "Copy nội dung sang ngày",
}


def _task_signature(tasks: list) -> str:
    """Chuỗi nhận dạng nội dung task (để gộp các ngày cùng nội dung)."""
    return "|".join(
        f"{t.get('task','')}:{t.get('project','')}:{t.get('description','')}"
        for t in tasks)


def format_preview(actions: list[Action]) -> str:
    """Hiện các action để người dùng xác nhận trước khi ghi.
    GỘP các action cùng type + cùng nội dung task thành 1 dòng
    "từ ngày X đến ngày Y (N ngày)" — không liệt kê 5 dòng riêng."""
    valid = [a for a in actions if not a.error and a.type != NOT_ACTION]
    errors = [a for a in actions if a.error]

    lines = ["✏️ MÌNH HIỂU BRO MUỐN:", "━━━━━━━━━━━━━━━━━━"]

    # Gộp action cùng (type, task_signature) → 1 nhóm nhiều ngày
    groups = []   # [(type, task_sig, [days], tasks)]
    for act in valid:
        sig = _task_signature(act.tasks)
        merged = False
        for g in groups:
            if g[0] == act.type and g[1] == sig:
                g[2].append(act.day)
                merged = True
                break
        if not merged:
            groups.append([act.type, sig, [act.day], act.tasks])

    for atype, _sig, days, tasks in groups:
        verb = _ACTION_VERB.get(atype, atype)
        days_sorted = sorted(d for d in days if d)
        if len(days_sorted) == 1:
            day_str = _dmy(days_sorted[0])
        elif len(days_sorted) > 1:
            day_str = (f"{len(days_sorted)} ngày: từ {_dmy(days_sorted[0])} "
                       f"đến {_dmy(days_sorted[-1])}")
        else:
            day_str = "(không rõ ngày)"
        lines.append(f"► {verb} — {day_str}:")
        if atype not in (DELETE_DAY,):
            for t in tasks:
                h = f"{t['hours']:g}h " if t.get("hours") else ""
                desc = f" | {t['description']}" if t.get("description") else ""
                lines.append(f"    {h}{t.get('task','')} — {t.get('project','')}{desc}")

    for act in errors:
        lines.append(f"⚠️ {act.error}")
    for w in dict.fromkeys(a.warning for a in actions if a.warning):
        lines.append(f"🔎 {w}")

    lines.append("━━━━━━━━━━━━━━━━━━")
    # Nếu cụm nhiều ngày: nhắc cách sửa 1 ngày cụ thể
    multi = any(len(g[2]) > 1 for g in groups)
    if multi:
        lines.append("Nhắn 'ok' để áp cho TẤT CẢ ngày trên.")
        lines.append("Muốn sửa 1 ngày khác → nói rõ ngày đó (vd 'thứ 3 làm SDF').")
    else:
        lines.append("Nhắn 'ok' để xác nhận, hoặc nói mình sửa lại / 'hủy'.")
    return "\n".join(lines)


def format_result(applied: dict) -> str:
    """Thông báo sau khi ghi thành công — HIỂN THỊ CHI TIẾT task từng
    ngày (không chỉ "đã ghi ngày X"), để người dùng thấy rõ đã ghi gì."""
    lines = ["✅ ĐÃ GHI THÀNH CÔNG:", "━━━━━━━━━━━━━━━━━━"]
    written = applied.get("written_days", [])
    if written:
        for d, entries in sorted(written, key=lambda x: x[0]):
            if entries is None:
                lines.append(f"🗑️ {_dmy(d)}: đã xóa")
                continue
            total = sum(float(e.get("hours") or 0) for e in entries)
            lines.append(f"📅 {_dmy(d)}:")
            for e in entries:
                h = f"{e['hours']:g}h " if e.get("hours") else ""
                desc = f" | {e['description']}" if e.get("description") else ""
                lines.append(f"  • {h}{e.get('task','')} — "
                             f"{e.get('project','')}{desc}")
            lines.append(f"  (tổng {total:g}h)")
    else:
        for s in applied.get("summary", []):
            lines.append(f"  • {s}")
    mc = mc_reminder(applied)
    if mc:
        lines.append(mc)
    return "\n".join(lines)


def mc_reminder(applied: dict) -> str:
    """Có ghi Sick Leave → nhắc gửi MC (thêm 24-Sep)."""
    days = sorted({d for d, entries in applied.get("written_days", [])
                   if entries and any(e.get("task") == _tr.TASK_SICK_LEAVE
                                      for e in entries)})
    if not days:
        return ""
    ds = ", ".join(_dmy(d) for d in days)
    return (f"🩺 Có ngày NGHỈ BỆNH ({ds}) — nhớ gửi MC (giấy khám bệnh) "
            "cho sếp/HR nhé.")


# ===========================================================================
# PERSIST — ghi kết quả xuống parsed_days (daily_store) + Excel nếu đã gửi
# ===========================================================================
def _sent_days_for(days: list, state: dict, config) -> list:
    """Ngày nào ĐÃ GỬI sếp: <= last_sent, HOẶC đang nằm trong file Excel
    tháng (file làm việc chỉ được ghi khi gửi / sửa ngày đã gửi)."""
    import excel_writer
    import state as state_mod
    last = state_mod.last_sent_date(state)
    in_excel: dict = {}
    out = []
    for d in sorted(days):
        mk = (d.year, d.month)
        if mk not in in_excel:
            try:
                in_excel[mk] = {e["date"] for e in excel_writer.read_month_entries(
                    date(d.year, d.month, 1), config)}
            except Exception as ex:  # noqa: BLE001
                log.warning("Không đọc được Excel tháng %s/%s (%s)", d.month, d.year, ex)
                in_excel[mk] = set()
        if (last is not None and d <= last) or d in in_excel[mk]:
            out.append(d)
    return out


def persist_actions(actions: list, config, state,
                    also_excel_if_sent: bool = False) -> dict:
    """Ghi các action ĐÃ XÁC NHẬN xuống parsed_days (và Excel nếu ngày
    đã gửi + also_excel_if_sent=True).

    Đọc parsed_days hiện tại → apply_actions → ghi lại từng ngày touched.
    also_excel_if_sent=True (dùng cho /edittimesheet): ngày <= last_sent
    còn ghi vào Excel qua orchestrator.apply_edit_smart.

    Trả {"summary": [...], "touched": [...], "excel_files": [...],
         "excel_months": [...]}.
    """
    import daily_store
    import state as state_mod

    pd = daily_store.load_all()
    res = apply_actions(actions, pd, config)
    new_pd = res["parsed_days"]
    touched = res["touched"]

    # Ghi từng ngày touched xuống parsed_days + thu chi tiết để hiển thị
    written_days = []   # [(date, entries)] hoặc (date, None) nếu xóa
    for d in touched:
        iso = d.isoformat()
        if iso in new_pd:
            entries = [{**e, "date": d} for e in new_pd[iso]["entries"]]
            daily_store.save_day(d, entries)
            written_days.append((d, entries))
        else:
            daily_store.forget_day(d)
            written_days.append((d, None))   # đã xóa

    # CHECKPOINT: validate cấu trúc các ngày vừa ghi (bắt key≠date,
    # tổng≠8h, trùng task) — cảnh báo để người dùng biết, không chặn.
    struct_warnings = []
    try:
        hpd = config.get("hours_per_day") or 8
        pd_now = daily_store.load_all()
        touched_iso = {d.isoformat() for d in touched}
        pd_check = {k: v for k, v in pd_now.items() if k in touched_iso}
        struct_warnings = validator.validate_parsed_structure(pd_check, hpd)
    except Exception:  # noqa: BLE001 — validate lỗi không chặn ghi
        pass

    result = {"summary": res["summary"], "touched": [d.isoformat() for d in touched],
              "written_days": written_days, "struct_warnings": struct_warnings,
              "excel_files": [], "excel_months": []}

    # Ngày ĐÃ GỬI → ghi Excel (chỉ khi /edittimesheet). Sửa 24-Sep:
    #  - nhận "đã gửi" = <= last_sent HOẶC đang có trong file Excel tháng
    #    (state lỡ mất last_sent vẫn nhận đúng)
    #  - gọi thẳng prepare_past_edit/apply_past_edit, KHÔNG nuốt need_info
    #  - Excel ghi THẤT BẠI → HOÀN TÁC parsed_days các ngày đó (không bao giờ
    #    để parsed_days và Excel lệch nhau) + báo lỗi rõ ràng
    if also_excel_if_sent:
        sent_days = _sent_days_for(touched, state, config)
        result["sent_days"] = [d.isoformat() for d in sent_days]
        if sent_days:
            import orchestrator
            outside, del_days = [], []
            for d in sent_days:
                iso = d.isoformat()
                if iso in new_pd:
                    for e in new_pd[iso]["entries"]:
                        outside.append({**e, "date": d})
                else:
                    del_days.append(d)
            err = ""
            try:
                prep = orchestrator.prepare_past_edit(outside, del_days, config, state)
                if prep.get("status") == "need_info":
                    err = "; ".join(prep.get("questions") or ["không rõ lý do"])
                else:
                    applied = orchestrator.apply_past_edit(config, state_mod.load_state())
                    result["excel_files"] = applied.get("files", [])
                    result["excel_months"] = applied.get("months", [])
                    if not result["excel_files"]:
                        err = "không có file Excel nào được ghi"
            except PermissionError:
                err = ("file Excel đang MỞ (Windows khóa file) — ĐÓNG file Excel "
                       "trong output\\ rồi làm lại")
            except Exception as ex:  # noqa: BLE001
                log.exception("persist_actions ghi Excel lỗi")
                err = f"{type(ex).__name__}: {ex}"
            if err:
                for d in sent_days:   # HOÀN TÁC về bản trước khi sửa
                    iso = d.isoformat()
                    if iso in pd:
                        daily_store.save_day(d, [{**x, "date": d}
                                                 for x in pd[iso]["entries"]])
                    else:
                        daily_store.forget_day(d)
                result["excel_error"] = err
                result["rolled_back"] = [d.isoformat() for d in sent_days]
                log.error("Sửa ngày đã gửi THẤT BẠI (%s) — đã hoàn tác parsed_days %s",
                          err, result["rolled_back"])

    # 🔄 (02-Oct) Bản nháp đang chờ gửi có chứa ngày vừa sửa → HỦY bản nháp cũ,
    # để 'ok' KHÔNG gửi bản chưa sửa. Sửa trên chính `state` người gọi đang giữ
    # (người gọi lưu state sau đó → không lưu đè bản nháp cũ trở lại).
    try:
        dr = (state or {}).get("draft") or {}
        ps, pe = dr.get("period_start"), dr.get("period_end")
        if dr and ps and pe and any(ps <= d.isoformat() <= pe for d in touched):
            state["draft"] = None
            if (state.get("conversation") or {}).get("awaiting") == "ts_mail_confirm":
                state["conversation"] = None
            state_mod.save_state(state)
            result["draft_invalidated"] = True
            log.info("Đã HỦY bản nháp %s→%s vì sửa ngày trong kỳ.", ps, pe)
    except Exception as e:  # noqa: BLE001
        log.warning("Không kiểm tra được bản nháp sau khi sửa (%s)", e)

    return result


# ===========================================================================
# SELF-TEST (không gọi AI)
# ===========================================================================
if __name__ == "__main__":
    from config_loader import load_config
    cfg = load_config()

    print("=" * 55)
    print("NOTE_ACTION SELF-TEST")
    print("=" * 55)

    pd = {
        "2026-09-24": {"entries": [
            {"date": "2026-09-24", "project": "PACSNP-1", "task": "Coding/UT",
             "description": "New product day 2 items", "hours": 8.0}]},
    }

    # T1: ADD_TASK vào ngày đã có → chia lại giờ
    acts = [Action(type=ADD_TASK, day=date(2026,9,24),
                   tasks=[{"project":"Production Support","task":"SDF",
                           "description":"ABC","hours":2.0}])]
    acts = validate_actions(acts, pd, cfg)
    res = apply_actions(acts, pd, cfg)
    e = res["parsed_days"]["2026-09-24"]["entries"]
    print(f"\nT1 ADD_TASK (SDF 2h vào ngày có Coding 8h):")
    for x in e: print(f"   {x['hours']:g}h {x['task']}")
    hours = {x['task']: x['hours'] for x in e}
    assert hours['SDF'] == 2.0 and hours['Coding/UT'] == 6.0
    print("   ✓ SDF=2h cố định, Coding chia còn 6h")

    # T2: REPLACE_DAY → xóa hết ghi mới
    acts = [Action(type=REPLACE_DAY, day=date(2026,9,24),
                   tasks=[{"project":"Annual Leave","task":"Annual Leave",
                           "description":"","hours":None}])]
    acts = validate_actions(acts, pd, cfg)
    assert acts[0].needs_confirm  # ngày đã có → hỏi
    res = apply_actions(acts, pd, cfg)
    e = res["parsed_days"]["2026-09-24"]["entries"]
    print(f"\nT2 REPLACE_DAY (đổi thành nghỉ phép):")
    print(f"   {len(e)} task: {e[0]['task']} {e[0]['hours']:g}h")
    assert len(e) == 1 and e[0]['task'] == "Annual Leave"
    print("   ✓ Xóa Coding, ghi Annual Leave 8h, có hỏi xác nhận")

    # T3: DELETE_DAY ngày không có → error
    acts = [Action(type=DELETE_DAY, day=date(2026,9,25))]
    acts = validate_actions(acts, pd, cfg)
    print(f"\nT3 DELETE ngày không có:")
    print(f"   error: {acts[0].error}")
    assert acts[0].error
    print("   ✓ Báo không thấy, không hỏi")

    # T4: DELETE_DAY ngày có → hỏi
    acts = [Action(type=DELETE_DAY, day=date(2026,9,24))]
    acts = validate_actions(acts, pd, cfg)
    assert acts[0].needs_confirm and not acts[0].error
    print(f"\nT4 DELETE ngày có: needs_confirm={acts[0].needs_confirm}")
    print("   ✓ Hỏi xác nhận trước xóa")

    # T5: ADD_TASK ngày chưa có → tự đổi ADD_DAY
    acts = [Action(type=ADD_TASK, day=date(2026,9,26),
                   tasks=[{"project":"PS","task":"DFU","description":"PACSDFUM-1","hours":None}])]
    acts = validate_actions(acts, pd, cfg)
    print(f"\nT5 ADD_TASK ngày chưa có → type={acts[0].type}")
    assert acts[0].type == ADD_DAY
    print("   ✓ Tự đổi thành ADD_DAY")

    print("\n>>> ALL GREEN <<<")
