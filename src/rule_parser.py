"""
rule_parser.py — Parser dự phòng khi AI hoàn toàn không khả dụng (503 chain).

Không gọi AI. Dùng regex + task_rules để bóc tách ghi chú đơn giản.
Chỉ bắt được ~70% trường hợp. Trường hợp phức tạp → trả FAILED →
bot lưu vào notes, thứ 6 AI xử lý lại.

Tiêu chí "thành công": tìm được ít nhất (ngày + task_type).
Tiêu chí "thất bại": không nhận ra ngày hoặc không nhận ra task_type.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

import task_rules as _tr
from log_setup import get_logger

log = get_logger("rule_parser")

# Trạng thái trả về
PARSE_OK     = "ok"      # bóc tách được, tự tin
PARSE_UNSURE = "unsure"  # bóc tách được nhưng không chắc → hỏi lại
PARSE_FAILED = "failed"  # không nhận ra → lưu notes, thứ 6 AI xử


@dataclass
class ParsedEntry:
    date_iso: str          # "YYYY-MM-DD"
    project: str           # cột D
    task: str              # cột E
    description: str       # cột F
    hours: float           # giờ (0 = chưa xác định)
    confidence: str        # PARSE_OK | PARSE_UNSURE
    note: str = ""         # lý do uncertain nếu có


@dataclass
class ParseResult:
    status: str            # PARSE_OK | PARSE_UNSURE | PARSE_FAILED
    entries: list[ParsedEntry] = field(default_factory=list)
    fail_reason: str = ""  # lý do nếu FAILED


# ---------------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------------
_DATE_TAG_RE = re.compile(
    r'\[D:(\d{4}-\d{2}-\d{2})\]')                    # format internal pipeline
_DATE_DMY_RE = re.compile(
    r'\b(\d{1,2})/(\d{1,2})/(\d{4})\b')              # format sau norm: 19/09/2026
_TICKET_RE   = re.compile(
    r'\b(PACS\w+-\d+|INC\d+|Ticket#?\s*\d+)\b',
    re.IGNORECASE)
_HOURS_RE    = re.compile(
    r'(\d+(?:[.,]\d+)?)\s*h(?:ours?)?', re.IGNORECASE)
_MULTI_DATE_RE = re.compile(
    r'\[D:(\d{4}-\d{2}-\d{2})\].*?\[D:(\d{4}-\d{2}-\d{2})\]',
    re.DOTALL)


def _extract_date(text: str) -> list[date]:
    """Trích ngày từ text đã normalize.
    Hỗ trợ 2 format:
    - [D:YYYY-MM-DD] (format internal pipeline)
    - DD/MM/YYYY    (format sau normalize_dates_in_text)
    """
    results = []
    seen = set()
    # Format [D:YYYY-MM-DD]
    for iso in _DATE_TAG_RE.findall(text):
        if iso not in seen:
            seen.add(iso)
            results.append(date.fromisoformat(iso))
    # Format DD/MM/YYYY
    for d_str, m_str, y_str in _DATE_DMY_RE.findall(text):
        try:
            d = date(int(y_str), int(m_str), int(d_str))
            iso = d.isoformat()
            if iso not in seen:
                seen.add(iso)
                results.append(d)
        except ValueError:
            pass
    return sorted(results)


def _extract_hours(text: str) -> float:
    """Lấy giờ từ text. Mặc định 8h nếu không tìm thấy."""
    m = _HOURS_RE.search(text)
    if m:
        return float(m.group(1).replace(',', '.'))
    return 8.0


def _description_from_text(text: str, tickets: list[str]) -> str:
    """Lấy mô tả cột F từ câu người dùng gõ (rule_parser = 1 task/tin):
      1. có "description là / desc: / mô tả là ..." → lấy phần sau đó
      2. không có → từ ticket ĐẦU TIÊN tới hết câu (bỏ "8h" ở đuôi)
    Chỉ chuẩn hóa MÃ ticket, chữ khác giữ nguyên. Ticket nào nằm ngoài
    đoạn lấy được → nối thêm vào cuối, để KHÔNG bao giờ mất ticket."""
    m = re.search(r"(?:description|desc|mô\s*tả)\s*(?:là|:|=)\s*(.+)$",
                  text, re.IGNORECASE | re.DOTALL)
    if m:
        seg = m.group(1)
    else:
        first = _tr.TICKET_PART_RE.search(text)
        seg = text[first.start():] if first else ""
    seg = re.sub(r"[\s,;.]*\b\d+(?:[.,]\d+)?\s*(?:h|giờ|tiếng)\s*$", "",
                 seg.strip(), flags=re.IGNORECASE)
    seg = seg.strip().strip('"“”\'').strip()
    desc = _tr.normalize_ticket_text(seg)
    have = {t.upper() for t in _tr.extract_tickets_from_note(desc)}
    missing = [t for t in tickets if t.upper() not in have]
    if missing:
        desc = (desc + ", " if desc else "") + ", ".join(missing)
    return desc


def _extract_tickets(text: str) -> list[str]:
    """Trích tất cả mã ticket — dùng chung regex với task_rules
    để đồng bộ (extract_tickets_from_note)."""
    return _tr.extract_tickets_from_note(text)


def _detect_task_rule(text: str) -> _tr.TaskRule | None:
    """Tìm TaskRule phù hợp nhất từ text.

    Ưu tiên nhận dạng NP task khi có dấu hiệu NP (prefix PACSNP- hoặc
    từ 'np'/'new product'), vì khi đó cột F phải là constant
    'New product day 2 items' — khác với Coding/UT thường.
    """
    low = text.lower()
    has_np_prefix = bool(re.search(r'pacsnp-\d+', low))
    has_np_word = any(w in low for w in ("new product", " np ", "np ",
                                         " np,", "làm np", "task np"))
    has_uat = "uat" in low

    # NP + UAT → UAT Support rule (cột E = UAT Support, F = ticket)
    if (has_np_prefix or has_np_word) and has_uat:
        return _tr.find_rule_by_task_name("UAT Support")
    # NP + assessment/investigation → Investigation/Assessment (F = constant)
    if (has_np_prefix or has_np_word) and any(
            w in low for w in ("assessment", "assess", "investigation",
                               "phân tích", "đánh giá")):
        # dùng NP rule (Coding/UT default) nhưng đổi task_name
        np_rule = _tr.find_rule_by_keyword("np")
        if np_rule:
            import copy
            r2 = copy.copy(np_rule)
            r2.task_name = _tr.TASK_INVESTIGATION_ASSESSMENT
            return r2
    # NP (coding hoặc mặc định) → NP rule có desc_const
    if has_np_prefix or has_np_word:
        return _tr.find_rule_by_keyword("np")

    # Ưu tiên nhận dạng task production rõ ràng (tránh "fix code" nuốt "sdf")
    if re.search(r'\bsdf\b', low):
        return _tr.find_rule_by_task_name("SDF")
    if re.search(r'\bdfu\b', low) or "pacsdfum" in low:
        return _tr.find_rule_by_task_name("DFU")
    if has_uat:
        return _tr.find_rule_by_task_name("UAT Support")

    return _tr.find_rule_by_keyword(text)


def _extract_np_tickets(text: str) -> list[str]:
    """Trích các mã PACSNP-xxxx (multi-ticket NP)."""
    # dùng chung định nghĩa ticket → bắt cả PACSNP1982 (không gạch)
    return [t for t in _tr.extract_tickets_from_note(text)
            if t.startswith("PACSNP")]


# ---------------------------------------------------------------------------
# Core parser
# ---------------------------------------------------------------------------
def parse_note(normalized_text: str) -> ParseResult:
    """Bóc tách 1 ghi chú đã được date_normalizer chuẩn hóa.

    normalized_text: text sau khi qua normalize_dates_in_text()
    (ngày đã ở dạng [D:YYYY-MM-DD])
    """
    text = normalized_text.strip()
    if not text:
        return ParseResult(status=PARSE_FAILED,
                           fail_reason="Ghi chú rỗng")

    # ---- 1. Tìm ngày ----
    dates = _extract_date(text)
    if not dates:
        return ParseResult(status=PARSE_FAILED,
                           fail_reason="Không tìm thấy ngày cụ thể trong ghi chú")

    # ---- 2. Phát hiện MULTI-TASK (nhiều task trong 1 ngày) ----
    # rule_parser chỉ bóc tách được 1 task/ngày. Nếu ghi chú có dấu
    # hiệu nhiều task (nhiều mốc "Xh" hoặc nhiều dòng bullet) → không
    # tự xử, trả UNSURE để AI (thứ 6) tách chính xác.
    hour_marks = re.findall(r'\d+(?:[.,]\d+)?\s*h\b', text, re.IGNORECASE)
    bullet_lines = [ln for ln in text.split("\n")
                    if ln.strip().startswith(("•", "-", "*"))]
    if len(hour_marks) >= 2 or len(bullet_lines) >= 2:
        return ParseResult(
            status=PARSE_UNSURE,
            fail_reason=("Ghi chú có nhiều task trong 1 ngày — mình bóc "
                         "tách tự động chưa chắc đúng, để AI xử cho chuẩn"))

    # ---- 2b. Tìm task rule ----
    rule = _detect_task_rule(text)
    if rule is None:
        return ParseResult(status=PARSE_FAILED,
                           fail_reason="Không nhận ra loại task (keyword không khớp)")

    # ---- 3. Xây dựng entries ----
    hours    = _extract_hours(text)
    tickets  = _extract_tickets(text)   # tất cả ticket, đã dedup + uppercase
    np_tix   = _extract_np_tickets(text)  # riêng PACSNP-xxxx
    entries  = []
    notes    = []

    task    = rule.task_name

    for day in dates:
        # ── Cột D (project) ──
        if rule.project_const:
            # Production Support / Annual Leave... (cố định)
            project = rule.project_const
        elif task == _tr.TASK_UAT_SUPPORT and tickets:
            # UAT Support: cột D = ticket ĐẦU (project dự án),
            # cột F = ticket còn lại (do pick_description_ticket xử)
            project = tickets[0]
        elif np_tix and task in (_tr.TASK_CODING_UT,
                                 _tr.TASK_INVESTIGATION_ASSESSMENT):
            # NP Coding/Assessment: gộp TẤT CẢ PACSNP-xxxx vào cột D
            # (multi-ticket 1 dòng), cột F = constant
            project = ", ".join(np_tix)
        elif tickets:
            # Task động khác: dùng ticket đầu làm project
            project = tickets[0]
        else:
            project = ""

        # ── Cột F (description) — dùng pick_description_ticket ──
        # để phân biệt project ticket (cột D) vs description ticket (cột F),
        # và áp dụng desc_const cho NP (Coding/UT, Investigation/Assessment)
        if rule.desc_const:
            # NP Coding/UT hoặc Investigation/Assessment → constant
            desc = rule.desc_const
        elif task != _tr.TASK_UAT_SUPPORT and tickets:
            # Sửa 24-Sep: GIỮ phần mô tả người dùng gõ (trước chỉ nối ticket →
            # mất chữ như "Soft lock after AFI transaction PN 1234567")
            desc = _description_from_text(text, tickets)
        else:
            picked = _tr.pick_description_ticket(tickets, project, task)
            desc = picked or ""

        # ── Cột G (hours) — Leave luôn 8h ──
        entry_hours = hours
        if task in (_tr.TASK_ANNUAL_LEAVE,
                    _tr.TASK_PUBLIC_HOLIDAY,
                    _tr.TASK_SPECIAL_LEAVE, _tr.TASK_SICK_LEAVE):
            entry_hours = 8.0
            desc = ""   # Leave: cột F trống

        # ── Kiểm tra thiếu sót → UNSURE ──
        entry_note = ""
        if not project and rule.project_const is None:
            entry_note = f"ngày {day.strftime('%d/%m')}: chưa rõ tên project (cột D)"
            notes.append(entry_note)
        # Ticket bắt buộc nhưng không có (và không phải task dùng desc_const)
        if (rule.ticket_required and not desc and not rule.desc_const
                and task not in (_tr.TASK_ANNUAL_LEAVE,
                                 _tr.TASK_PUBLIC_HOLIDAY,
                                 _tr.TASK_SPECIAL_LEAVE, _tr.TASK_SICK_LEAVE)):
            entry_note = (f"ngày {day.strftime('%d/%m')}: {task} "
                          "cần có ticket/mô tả (cột F)")
            notes.append(entry_note)

        entries.append(ParsedEntry(
            date_iso    = day.isoformat(),
            project     = project,
            task        = task,
            description = desc,
            hours       = entry_hours,
            confidence  = PARSE_UNSURE if entry_note else PARSE_OK,
            note        = entry_note,
        ))

    if not entries:
        return ParseResult(status=PARSE_FAILED,
                           fail_reason="Không tạo được entry nào")

    status = (PARSE_OK if all(e.confidence == PARSE_OK for e in entries)
              else PARSE_UNSURE)

    result = ParseResult(status=status, entries=entries)
    if notes:
        result.fail_reason = "; ".join(notes)

    log.info("rule_parser: %s — %d entries, %d ngày — %s",
             status, len(entries), len(dates), result.fail_reason or "OK")
    return result


def parse_note_to_dict(normalized_text: str) -> dict:
    """Wrapper trả dict tương thích với pipeline.postprocess_ai_days.

    Trả:
    {
      "status": "ok"|"unsure"|"failed",
      "entries": [{"date": date, "project": .., "task": .., "description": .., "hours": ..}],
      "questions": [str],   # câu hỏi nếu unsure
      "fail_reason": str,
    }
    """
    result = parse_note(normalized_text)
    entries_dict = []
    for e in result.entries:
        entries_dict.append({
            "date":        date.fromisoformat(e.date_iso),
            "project":     e.project,
            "task":        e.task,
            "description": e.description,
            "hours":       e.hours,
        })
    questions = []
    if result.status == PARSE_UNSURE and result.fail_reason:
        questions = [result.fail_reason]
    return {
        "status":      result.status,
        "entries":     entries_dict,
        "questions":   questions,
        "fail_reason": result.fail_reason,
    }


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from date_normalizer import normalize_dates_in_text as norm
    today = date(2026, 9, 19)

    tests = [
        # (ghi chú gốc, expected_status, expected_task)
        ("hôm nay làm DFU PACSDFUM-4865",
         PARSE_OK, "DFU"),
        ("ngày 1/9 làm NP PACSNP-7660, PACSNP-7619, PACSNP-6632",
         PARSE_OK, "Coding/UT"),
        ("hôm nay nghỉ phép",
         PARSE_OK, "Annual Leave"),
        ("thứ 4 tuần rồi check issue INC0044930",
         PARSE_OK, "Issue Investigation"),
        ("sdf cho prod issue hôm nay",
         PARSE_UNSURE, "SDF"),        # SDF nhưng không có ticket → unsure
        ("hôm nay làm việc linh tinh gì đó",
         PARSE_FAILED, None),         # không nhận ra task
        ("xyz abc 123",
         PARSE_FAILED, None),
    ]

    print("=" * 55)
    print("RULE PARSER SELF-TEST")
    print("=" * 55)
    all_ok = True
    for raw, exp_status, exp_task in tests:
        normalized = norm(raw, today)
        result = parse_note(normalized)
        ok = result.status == exp_status
        if exp_task and result.entries:
            ok = ok and result.entries[0].task == exp_task
        if not ok: all_ok = False
        mark = "✓" if ok else "✗"
        task_got = result.entries[0].task if result.entries else "—"
        print(f"  {mark} '{raw[:50]}'")
        print(f"       status={result.status} task={task_got}")
        if not ok:
            print(f"       expected status={exp_status} task={exp_task}")
            if result.fail_reason:
                print(f"       reason: {result.fail_reason}")
    print(f"\n>>> {'ALL GREEN' if all_ok else 'CÓ LỖI'} <<<")
