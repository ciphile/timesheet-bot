"""
task_rules.py — Quy tắc mapping cột D / E / F cho timesheet.

NGUỒN SỰ THẬT DUY NHẤT cho:
  - Cột D (Project Name): tên project thực hoặc constant (Production Support, Annual Leave...)
  - Cột E (Task Name):    hành động — chỉ dùng giá trị trong TASK_NAMES
  - Cột F (Description):  mô tả — một số task có giá trị mặc định cố định

CÁCH THÊM TASK TYPE MỚI:
  1. Thêm entry vào TASK_RULES bên dưới
  2. Chạy: python task_rules.py để test
  Không cần sửa file nào khác.

Cập nhật: 19-Sep-2026
"""

from dataclasses import dataclass, field


# ===========================================================================
# PROJECT NAME CONSTANTS (cột D) — các giá trị không đổi theo project
# ===========================================================================
PROJECT_PRODUCTION_SUPPORT = "Production Support"
PROJECT_ANNUAL_LEAVE        = "Annual Leave"
PROJECT_PUBLIC_HOLIDAY      = "Public Holiday"
PROJECT_SPECIAL_LEAVE       = "Special Leave"
PROJECT_SICK_LEAVE          = "Sick Leave"

# Các giá trị cột D cố định (không phải tên project thay đổi)
FIXED_PROJECT_NAMES: set[str] = {
    PROJECT_PRODUCTION_SUPPORT,
    PROJECT_ANNUAL_LEAVE,
    PROJECT_PUBLIC_HOLIDAY,
    PROJECT_SPECIAL_LEAVE,
}

# ===========================================================================
# TASK NAME CONSTANTS (cột E)
# ===========================================================================
TASK_CODING_UT              = "Coding/UT"
TASK_INVESTIGATION_ASSESSMENT = "Investigation/Assessment"
TASK_ISSUE_INVESTIGATION    = "Issue Investigation"
TASK_DFU                    = "DFU"
TASK_UAT_SUPPORT            = "UAT Support"
TASK_SDF                    = "SDF"
TASK_ANNUAL_LEAVE           = "Annual Leave"
TASK_PUBLIC_HOLIDAY         = "Public Holiday"
TASK_SPECIAL_LEAVE          = "Special Leave"
TASK_SICK_LEAVE             = "Sick Leave"   # nghỉ bệnh (cần MC) — thêm 24-Sep

# ===========================================================================
# DESCRIPTION CONSTANTS (cột F) — chỉ một số task có giá trị mặc định
# ===========================================================================
DESC_NEW_PRODUCT = "New product day 2 items"   # BẮT BUỘC cho NP task


# ===========================================================================
# TICKET PREFIX GUIDE — giúp AI và validator nhận dạng loại ticket
# ===========================================================================
TICKET_PREFIXES: dict[str, str] = {
    "PACSDFUM-": "DFU",                   # DFU data patch ticket
    "PACSNP-":   "New Product (NP)",      # NP ticket (project hoặc description)
    "INC":       "Issue Investigation",   # Production incident
    "PACSGASIA-":"Group Asia project",
    "PACSCMPOS-":"CMPOS project",
    "PACSFIN-":  "Finance project",
}

# Regex nhận dạng mọi loại ticket Jira (dùng chung cho auto-fill)
import re as _re
# ⚠️ ĐỊNH NGHĨA TICKET DUY NHẤT cho cả bot (sửa 24-Sep). Trước đây có 4
# regex khác nhau rải rác → mỗi nơi hiểu 1 kiểu, mất ticket.
#   PACS...  có/không gạch : PACSDFUM-4799, PACSDFUM777, PACSNP1982
#   INC/CHG/REQ có/không gạch : INC2799, INC-2799
#   Ticket#1234
# Hậu tố "part b / part A / part 2" ngay sau ticket được GIỮ → "Part B".
# CHỈ viết hoa MÃ ticket; chữ mô tả khác GIỮ NGUYÊN như người dùng gõ (sửa 24-Sep).
# Sửa 25-Sep: PACS tới 8 số (PACSDFUM-1234567); "Ticket # 902443" /
# "Ticket #902443" (dấu # cách chữ Ticket) cũng là ticket.
_TICKET_CORE = (r"(?:PACS[A-Z]*-?\d{2,8}"
                r"|(?:INC|CHG|REQ)-?\d{3,10}"
                r"|Ticket\s*#?\s*\d{4,10})")
ALL_TICKET_RE = _re.compile(r"\b" + _TICKET_CORE + r"\b", _re.IGNORECASE)
# part + 1 CHỮ hoặc 1-2 SỐ (không bắt nhầm "part of ...")
TICKET_PART_RE = _re.compile(
    r"\b" + _TICKET_CORE + r"\b(?:\s+part\s*(?:[A-Za-z]|\d{1,2})\b)?",
    _re.IGNORECASE)
# Chữ "ticket" đứng riêng (vd "ticket # inc..." ) → "Ticket"
# CHỈ khi ngay sau là '#' hoặc số (sửa 25-Sep: trước viết hoa MỌI chữ ticket,
# kể cả trong câu mô tả "this is the long ticket i ever seen")
_TICKET_WORD_RE = _re.compile(r"\bticket(?=\s*#|\s*\d)", _re.IGNORECASE)


def canon_ticket(raw: str) -> str:
    """Chuẩn hóa 1 ticket, CHỈ viết hoa phần MÃ (sửa 24-Sep):
      'pacsdfum-4799  part b' → 'PACSDFUM-4799 Part B'
      'inc-2799 part A'       → 'INC-2799 Part A'
      'ticket#02225399'       → 'Ticket#02225399' (giữ khoảng trắng như gõ)
    Giữ nguyên có/không gạch như người dùng gõ."""
    s = " ".join(raw.split())
    m = _re.match(r"(?i)^(ticket)(\s*#?\s*\d+)(.*)$", s)
    if m:
        code, rest = "Ticket" + m.group(2), m.group(3)
    else:
        m = _re.match(r"^(\S+)(.*)$", s)
        code, rest = m.group(1).upper(), m.group(2)
    part = _re.match(r"(?i)^\s*part\s*([a-z]|\d{1,2})$", rest)
    if part:
        return f"{code} Part {part.group(1).upper()}"
    return code + rest


def extract_tickets_from_note(note_text: str) -> list[str]:
    """Trích TẤT CẢ mã ticket (kèm 'Part X' nếu có) từ text.
    Trả list dạng chuẩn (canon_ticket), bỏ trùng, giữ thứ tự xuất hiện."""
    seen, result = set(), []
    for m in TICKET_PART_RE.finditer(note_text or ""):
        t = canon_ticket(m.group(0))
        if t.upper() not in seen:
            seen.add(t.upper()); result.append(t)
    return result


def normalize_ticket_text(text: str) -> str:
    """Chuẩn hóa ticket trong 1 đoạn mô tả, TÔN TRỌNG chữ người dùng gõ:
    chỉ viết hoa MÃ ticket, 'part b' → 'Part B', chữ 'ticket' → 'Ticket'.
    Mọi chữ khác (vd 'Soft lock after AFI transaction pn 1234567')
    GIỮ NGUYÊN hoa/thường. (Trước 24-Sep: viết hoa cả 'PART', 'TICKET#'
    và mọi chuỗi dạng chữ-số như 'drop-22' → sai ý người dùng.)"""
    if not text:
        return text or ""
    text = TICKET_PART_RE.sub(lambda m: canon_ticket(m.group(0)), text)
    text = BARE_PREFIX_RE.sub(_canon_bare, text)
    return _TICKET_WORD_RE.sub("Ticket", text)


# Tiền tố ticket ĐỨNG TRƠ (thiếu số), vd "pacsdfum part e" → viết hoa
# "PACSDFUM Part E" + note_action CẢNH BÁO "ticket thiếu số" (thêm 24-Sep).
# Không khớp khi ngay sau là số (PACSDFUM-4799, PACSDFUM777 = ticket đủ).
BARE_PREFIX_RE = _re.compile(
    r"\b(pacs[a-z]{2,})\b(?!\s*-?\s*\d)(?:\s*part\s*([a-z]|\d{1,2})\b)?",
    _re.IGNORECASE)


def _canon_bare(m) -> str:
    return m.group(1).upper() + (f" Part {m.group(2).upper()}" if m.group(2) else "")


def find_bare_prefixes(text: str) -> list[str]:
    """Các tiền tố ticket THIẾU SỐ trong text (để cảnh báo)."""
    return [_canon_bare(m) for m in BARE_PREFIX_RE.finditer(text or "")]


def pick_description_ticket(tickets: list[str], project: str,
                             task_name: str) -> str | None:
    """Chọn ticket phù hợp nhất để điền vào cột F (description).

    Nguyên tắc:
    - NP task (Coding/UT, Investigation/Assessment): cột F = constant,
      không cần ticket → trả None
    - UAT Support với project PACSNP-xxxx: cột D đã là project ticket,
      cột F = ticket UAT (ticket khác, thường là PACSNP-xxxx nhỏ hơn)
    - DFU: cột F = PACSDFUM-xxxx
    - Issue Investigation: cột F = INC-xxxx hoặc mô tả
    - Nếu nhiều ticket → lấy tất cả (DFU thường nhiều ticket/dòng)
    """
    if not tickets:
        return None

    # NP task dùng constant description → không điền ticket
    if task_name in ("Coding/UT", "Investigation/Assessment"):
        proj_up = (project or "").upper()
        if proj_up.startswith("PACSNP"):
            return None  # NP → desc_const = "New product day 2 items"

    # DFU / Issue Investigation: GIỮ TẤT CẢ ticket (sửa 24-Sep). Trước đây
    # DFU chỉ giữ PACSDFUM (VỨT INC), Issue Investigation chỉ giữ INC →
    # mất ticket. người dùng: INC nằm dưới DFU là bình thường.
    if task_name in ("DFU", "Issue Investigation"):
        return ", ".join(tickets)

    # UAT Support: cột F = ticket khác cột D
    if task_name == "UAT Support":
        proj_tickets = set()
        for t in (project or "").upper().split(","):
            t = t.strip()
            if ALL_TICKET_RE.match(t):
                proj_tickets.add(t)
        desc_tickets = [t for t in tickets if t not in proj_tickets]
        if desc_tickets:
            return ", ".join(desc_tickets)
        return ", ".join(tickets)

    # Default: tất cả ticket
    return ", ".join(tickets) if tickets else None


# ===========================================================================
# TASK RULES — quy tắc mapping từ loại công việc → D / E / F
# ===========================================================================
@dataclass
class TaskRule:
    """Quy tắc cho 1 loại task.

    project_const: cột D luôn là giá trị này (None = tên project thay đổi)
    task_name:     cột E — giá trị cố định
    desc_const:    cột F mặc định (None = hỏi hoặc lấy từ ghi chú)
    desc_required: True = BẮT BUỘC hỏi nếu không có description
    ticket_required: True = BẮT BUỘC có ticket/Jira trong description
    ticket_prefix: prefix ticket dự kiến (để validator nhắc nhở)
    multi_ticket_ok: True = nhiều ticket gộp 1 dòng (vd NP, DFU)
    keywords:      các từ khóa nhận dạng từ ngôn ngữ tự nhiên
    """
    task_name:        str
    keywords:         list[str]
    project_const:    str | None = None   # None = project thay đổi
    desc_const:       str | None = None   # None = không có mặc định
    desc_required:    bool = False
    ticket_required:  bool = False
    ticket_prefix:    str | None = None
    multi_ticket_ok:  bool = False
    notes:            str = ""            # ghi chú cho dev/AI


TASK_RULES: list[TaskRule] = [

    # ── 1. NGHỈ PHÉP ──────────────────────────────────────────────────────
    TaskRule(
        task_name     = TASK_ANNUAL_LEAVE,
        project_const = PROJECT_ANNUAL_LEAVE,
        keywords      = ["nghỉ phép", "annual leave", "nghỉ năm", "off",
                         "leave", "phép", "nghỉ"],
        desc_required = False,
        ticket_required = False,
        notes         = "Cột D và E đều = Annual Leave, cột F để trống",
    ),

    # ── 2. NGHỈ LỄ ────────────────────────────────────────────────────────
    TaskRule(
        task_name     = TASK_PUBLIC_HOLIDAY,
        project_const = PROJECT_PUBLIC_HOLIDAY,
        keywords      = ["nghỉ lễ", "public holiday", "lễ", "holiday"],
        desc_required = False,
        ticket_required = False,
        notes         = "Cột D và E đều = Public Holiday, cột F để trống",
    ),

    # ── 3. NGHỈ BÙ ────────────────────────────────────────────────────────
    TaskRule(
        task_name     = TASK_SPECIAL_LEAVE,
        project_const = PROJECT_SPECIAL_LEAVE,
        keywords      = ["nghỉ bù", "special leave", "nghỉ đặc biệt", "bù"],
        desc_required = False,
        ticket_required = False,
        notes         = "Cột D và E đều = Special Leave, cột F để trống",
    ),

    # ── 3b. NGHỈ BỆNH (cần MC) — thêm 24-Sep-2026 ─────────────────────────
    TaskRule(
        task_name     = TASK_SICK_LEAVE,
        project_const = PROJECT_SICK_LEAVE,
        keywords      = ["nghỉ bệnh", "nghỉ ốm", "sick leave", "bị bệnh",
                         "bị ốm", "medical leave"],
        desc_required = False,
        ticket_required = False,
        notes         = "Cột D và E đều = Sick Leave, cột F để trống (cần MC)",
    ),

    # ── 4. DFU (patch data) ───────────────────────────────────────────────
    TaskRule(
        task_name       = TASK_DFU,
        project_const   = PROJECT_PRODUCTION_SUPPORT,
        keywords        = ["dfu", "patch", "patch data", "vá data",
                           "deploy data", "data fix", "data patch"],
        desc_required   = True,
        ticket_required = True,
        ticket_prefix   = "PACSDFUM-",
        multi_ticket_ok = True,
        notes           = (
            "Cột D = Production Support (constant). "
            "Cột E = DFU (constant). "
            "Cột F = ticket PACSDFUM-xxxx, có thể nhiều ticket/dòng. "
            "BẮT BUỘC hỏi ticket nếu không có."
        ),
    ),

    # ── 5. ISSUE INVESTIGATION (check/investigate prod) ───────────────────
    TaskRule(
        task_name       = TASK_ISSUE_INVESTIGATION,
        project_const   = PROJECT_PRODUCTION_SUPPORT,
        keywords        = ["issue investigation", "investigate", "investigation",
                           "check issue", "check ticket", "điều tra",
                           "prod issue check", "production investigation",
                           "production check", "prod check", "prod issue",
                           "production issue", "production issue check",
                           "prod fix", "production fix", "prod support check",
                           "production support check",
                           "prod investigation", "softlock investigation",
                           "weekly softlock"],
        desc_required   = True,
        ticket_required = True,
        ticket_prefix   = "INC",
        notes           = (
            "Cột D = Production Support (constant). "
            "Cột E = Issue Investigation (constant). "
            "Cột F = Ticket# INCxxxxxxx hoặc mô tả issue. "
            "BẮT BUỘC hỏi ticket/mô tả nếu không có."
        ),
    ),

    # ── 6. SDF (production issue code fix) ────────────────────────────────
    TaskRule(
        task_name       = TASK_SDF,
        project_const   = PROJECT_PRODUCTION_SUPPORT,
        keywords        = ["sdf", "prod issue code", "prod fix code",
                           "fix code production", "production code fix",
                           "code fix prod"],
        desc_required   = True,
        ticket_required = True,
        notes           = (
            "Cột D = Production Support (constant). "
            "Cột E = SDF (constant). "
            "Cột F = mô tả/ticket (BẮT BUỘC hỏi). "
            "SDF = fix code lỗi production (khác DFU = patch data)."
        ),
    ),

    # ── 7. NP / NEW PRODUCT ───────────────────────────────────────────────
    # NP task có thể có 3 loại action (cột E):
    #   - Coding/UT          : đang code, develop, unit test
    #   - UAT Support        : đang support UAT cho NP
    #   - Investigation/Assessment: đang phân tích/đánh giá NP
    # AI chọn dựa vào ngữ cảnh ghi chú. Mặc định = Coding/UT nếu không rõ.
    # Cột F luôn = "New product day 2 items" cho TẤT CẢ NP task dù cột E là gì.
    TaskRule(
        task_name       = TASK_CODING_UT,       # mặc định — AI có thể đổi sang UAT Support / Investigation/Assessment
        project_const   = None,                  # tên project thay đổi
        keywords        = ["np", "new product", "new product task",
                           "coding np", "làm np", "task np"],
        desc_const      = DESC_NEW_PRODUCT,      # "New product day 2 items" — LUÔN LUÔN dù cột E là gì
        desc_required   = False,
        ticket_required = True,
        ticket_prefix   = "PACSNP-",
        multi_ticket_ok = True,
        notes           = (
            "Cột D = tên project/ticket (PACSNP-xxxx hoặc tên project). "
            "Nhiều ticket NP = GỘP 1 DÒNG: 'PACSNP-7660, PACSNP-7619'. "
            "Cột E = Coding/UT (mặc định) HOẶC UAT Support HOẶC Investigation/Assessment. "
            "  - Coding/UT: đang code/develop/unit test. "
            "  - UAT Support: đang support UAT cho NP. "
            "  - Investigation/Assessment: đang phân tích/đánh giá NP. "
            "Cột F = 'New product day 2 items' (CONSTANT — không thay đổi cho MỌI NP task). "
            "Hỏi ticket PACSNP-xxxx nếu chưa có."
        ),
    ),

    # ── 8. UAT SUPPORT ────────────────────────────────────────────────────
    TaskRule(
        task_name       = TASK_UAT_SUPPORT,
        project_const   = None,            # tên project thay đổi
        keywords        = ["uat", "uat support", "user acceptance",
                           "acceptance test", "kiểm thử uat", "support uat"],
        desc_required   = True,
        ticket_required = True,
        notes           = (
            "Cột D = tên project (PACSNP-xxxx — hỏi nếu chưa biết). "
            "Cột E = UAT Support (constant — KHÔNG viết 'Support UAT'). "
            "Cột F = ticket/mô tả (BẮT BUỘC hỏi). "
            "UAT task thường làm cả tháng — nhớ hỏi project name nếu đổi."
        ),
    ),

    # ── 9. CODING / GENERAL PROJECT ───────────────────────────────────────
    TaskRule(
        task_name       = TASK_CODING_UT,
        project_const   = None,
        keywords        = ["coding", "code", "lập trình", "develop",
                           "development", "enhancement", "unit test", "ut",
                           "wr", "work request", "project coding"],
        desc_required   = False,
        ticket_required = False,
        notes           = (
            "Cột D = tên project (hỏi nếu chưa biết). "
            "Cột E = Coding/UT. "
            "Cột F = mô tả (hỏi nếu không có)."
        ),
    ),

    # ── 10. INVESTIGATION / ASSESSMENT (general — không phải prod) ────────
    TaskRule(
        task_name       = TASK_INVESTIGATION_ASSESSMENT,
        project_const   = None,
        keywords        = ["investigation/assessment", "assess", "assessment",
                           "phân tích", "đánh giá", "research",
                           "tìm hiểu", "xem xét"],
        desc_required   = True,
        ticket_required = False,
        notes           = (
            "Cột D = tên project (hỏi nếu chưa biết). "
            "Cột E = Investigation/Assessment. "
            "Cột F = mô tả (BẮT BUỘC hỏi)."
        ),
    ),
]


# ===========================================================================
# LOOKUP HELPERS
# ===========================================================================
def find_rule_by_keyword(text: str) -> TaskRule | None:
    """Tìm rule phù hợp nhất từ text ngôn ngữ tự nhiên.
    Ưu tiên match dài hơn (tránh "np" match trước "new product")."""
    text_lower = text.lower().strip()
    best: tuple[int, TaskRule | None] = (0, None)
    for rule in TASK_RULES:
        for kw in rule.keywords:
            # KHỚP NGUYÊN TỪ (sửa 25-Sep): trước dò "chứa trong chuỗi" → "np"
            # khớp bên trong "pacsnp1982", "dfu" trong "pacsdfum-1", "wr" trong
            # "wrong" → "production check cho pacsnp…" bị hiểu thành NP.
            if len(kw) > best[0] and _re.search(
                    r"(?<![\w])" + _re.escape(kw) + r"(?![\w])", text_lower):
                best = (len(kw), rule)
    return best[1]


def find_rule_by_task_name(task_name: str) -> TaskRule | None:
    """Tìm rule theo task name chuẩn (cột E)."""
    tn = task_name.strip()
    for rule in TASK_RULES:
        if rule.task_name.lower() == tn.lower():
            return rule
    return None


def get_project_const(task_name: str) -> str | None:
    """Trả project constant nếu task này luôn dùng project cố định.
    None = project thay đổi theo ghi chú của người dùng."""
    rule = find_rule_by_task_name(task_name)
    return rule.project_const if rule else None


def get_desc_const(task_name: str) -> str | None:
    """Trả description mặc định nếu có (ví dụ NP = 'New product day 2 items').
    None = không có mặc định, cần hỏi hoặc lấy từ ghi chú."""
    rule = find_rule_by_task_name(task_name)
    return rule.desc_const if rule else None


def is_ticket_required(task_name: str) -> bool:
    """True nếu task này BẮT BUỘC có ticket/Jira trong description."""
    rule = find_rule_by_task_name(task_name)
    return rule.ticket_required if rule else False


def is_multi_ticket_ok(task_name: str) -> bool:
    """True nếu nhiều ticket được gộp vào 1 dòng (NP, DFU)."""
    rule = find_rule_by_task_name(task_name)
    return rule.multi_ticket_ok if rule else False


def get_ticket_prefix(task_name: str) -> str | None:
    """Trả prefix ticket dự kiến để validator nhắc nhở."""
    rule = find_rule_by_task_name(task_name)
    return rule.ticket_prefix if rule else None


# ===========================================================================
# PROMPT BUILDER — inject vào AI prompt
# ===========================================================================
def build_column_mapping_prompt() -> str:
    """Trả đoạn prompt mô tả đầy đủ quy tắc cột D/E/F cho AI.
    AI dùng đoạn này để map ngôn ngữ tự nhiên → giá trị Excel chính xác."""

    lines = [
        "QUY TẮC MAPPING CỘT D (Project Name) / E (Task Name) / F (Description):",
        "QUAN TRỌNG: Cột E chỉ được dùng đúng các giá trị trong danh sách, không tự đặt giá trị khác.",
        "",
    ]

    for rule in TASK_RULES:
        proj = f'"{rule.project_const}"' if rule.project_const else "(tên project thay đổi — lấy từ ghi chú)"
        desc = f'"{rule.desc_const}"  ← CONSTANT, luôn dùng giá trị này' if rule.desc_const \
               else ("BẮT BUỘC hỏi nếu không có" if rule.desc_required else "lấy từ ghi chú hoặc hỏi")
        ticket_note = f"BẮT BUỘC có ticket (prefix: {rule.ticket_prefix})" if rule.ticket_required and rule.ticket_prefix \
                      else ("BẮT BUỘC có ticket/mô tả" if rule.ticket_required else "không bắt buộc")
        multi = "  Nhiều ticket gộp 1 dòng: OK" if rule.multi_ticket_ok else ""

        lines += [
            f"► Nhận ra: {', '.join(rule.keywords[:5])}{'...' if len(rule.keywords) > 5 else ''}",
            f"  Cột D = {proj}",
            f"  Cột E = \"{rule.task_name}\"",
            f"  Cột F = {desc}",
            f"  Ticket: {ticket_note}{multi}",
            "",
        ]

    lines += [
        "TICKET PREFIX (để nhận dạng loại task từ mã ticket):",
    ]
    for prefix, meaning in TICKET_PREFIXES.items():
        lines.append(f"  {prefix}xxx → {meaning}")

    lines += [
        "",
        "QUY TẮC QUAN TRỌNG:",
        "- NP/New Product (task Coding/UT hoặc Investigation/Assessment):",
        "  * Cột F LUÔN = 'New product day 2 items' (constant).",
        "  * TẤT CẢ mã ticket PACSNP-xxxx → GOM HẾT vào CỘT D (Project),",
        "    VIẾT HOA, ngăn cách bằng dấu phẩy, TRÊN CÙNG 1 DÒNG/1 TASK.",
        "    TUYỆT ĐỐI KHÔNG tách mỗi ticket thành 1 task riêng.",
        "    TUYỆT ĐỐI KHÔNG để ticket NP vào cột F.",
        "  * Ví dụ: 'code NP pacsnp1982, pacsnp4583, pacsnp284' →",
        "    1 TASK: cột D = 'PACSNP1982, PACSNP4583, PACSNP284',",
        "    cột E = 'Coding/UT', cột F = 'New product day 2 items'.",
        "  * Nếu người dùng nhắc thời lượng (vd '6 tiếng code NP A, B, C') thì",
        "    đó là 1 task 6h với 3 ticket gom vào cột D, KHÔNG phải 3 task.",
        "- DFU: cột D LUÔN = 'Production Support', cột E = 'DFU'.",
        "  Nếu ghi chú có mã PACSDFUM-xxxx → điền THẲNG vào cột F, KHÔNG hỏi lại.",
        "  Ví dụ: 'làm DFU với ticket PACSDFUM-4983' → description = 'PACSDFUM-4983'.",
        "  Chỉ hỏi khi KHÔNG tìm thấy mã PACSDFUM- nào trong toàn bộ ghi chú về ngày đó.",
        "- SDF: cột D LUÔN = 'Production Support', cột E = 'SDF', fix code lỗi production.",
        "  Nếu ghi chú có mã ticket/Jira → điền vào cột F, KHÔNG hỏi lại.",
        "- Issue Investigation: cột D LUÔN = 'Production Support', cột E = 'Issue Investigation'.",
        "  Nếu ghi chú có mã INC-xxxx hoặc bất kỳ ticket nào → điền vào cột F, KHÔNG hỏi lại.",
        "- UAT Support: cột E = 'UAT Support'.",
        "  Phân biệt 2 loại mã trong ghi chú:",
        "  * Mã dự án (PACSNP-xxxx, PACSGASIA-xxxx lớn) → cột D (project name)",
        "  * Mã ticket UAT (PACSNP-xxxx nhỏ hơn, mã khác) → cột F (description)",
        "  Ví dụ: 'UAT support dự án PACSNP-8384, ticket PACSNP-3882'",
        "    → cột D = PACSNP-8384, cột E = UAT Support, cột F = PACSNP-3882",
        "  Nếu ghi chú có ticket → điền thẳng vào cột F, KHÔNG hỏi lại.",
        "- UAT Support: cột E PHẢI = 'UAT Support' (KHÔNG viết 'Support UAT' hay dạng khác)",
        "- Annual/Public/Special/Sick Leave: cột D = cột E = tên leave tương ứng, cột F để trống",
        "- Nghỉ bệnh / nghỉ ốm / bị bệnh → Sick Leave (KHÔNG phải Annual Leave)",
        "- NP task: cột E có thể là Coding/UT (code), UAT Support (test), Investigation/Assessment (phân tích)",
        "  Dù cột E là gì, cột F của NP LUÔN = 'New product day 2 items'",
        "  Nhận dạng NP: project có prefix PACSNP- hoặc người dùng nói 'np', 'new product'",
        "- QUAN TRỌNG - KHÔNG HỎI LẠI KHI ĐÃ CÓ TICKET: Nếu ghi chú đã chứa mã ticket",
        "  (PACSDFUM-xxxx, INC-xxxx, PACSNP-xxxx, PACSGASIA-xxxx, Ticket#...) thì điền",
        "  THẲNG vào cột F. TUYỆT ĐỐI không hỏi 'cho mình số Jira ticket' khi ticket đã có.",
        "- Chỉ hỏi ticket khi HOÀN TOÀN không tìm thấy mã ticket nào liên quan đến ngày đó.",
        "- Issue Investigation: cột D LUÔN = 'Production Support', cột E = 'Issue Investigation'",
        "  Đây là task điều tra lỗi production — KHÔNG nhầm với Investigation/Assessment (NP/WR)",
    ]

    return "\n".join(lines)


# ===========================================================================
# SELF-TEST
# ===========================================================================
# ===========================================================================
# VALID COMBINATIONS — cặp (cột D, cột E) hợp lệ
# Key = Task Name (cột E), Value = set project name hợp lệ cho cột D
# None trong set = project name thay đổi tự do (không cố định)
# ===========================================================================
VALID_COMBINATIONS: dict[str, dict] = {
    # Task E                  Project D hợp lệ        Desc bắt buộc?
    "Coding/UT": {
        "project_fixed": None,        # thay đổi tự do
        "desc_required": False,       # hỏi nếu không có, nhưng không block
        "desc_default": None,         # không có mặc định (trừ NP — xử lý riêng)
    },
    "Investigation/Assessment": {
        "project_fixed": None,
        "desc_required": True,
        "desc_default": None,
    },
    "Issue Investigation": {
        "project_fixed": PROJECT_PRODUCTION_SUPPORT,  # BẮT BUỘC
        "desc_required": True,
        "desc_default": None,
    },
    "DFU": {
        "project_fixed": PROJECT_PRODUCTION_SUPPORT,  # BẮT BUỘC
        "desc_required": True,        # ticket PACSDFUM-xxxx
        "desc_default": None,
    },
    "SDF": {
        "project_fixed": PROJECT_PRODUCTION_SUPPORT,  # BẮT BUỘC
        "desc_required": True,
        "desc_default": None,
    },
    "UAT Support": {
        "project_fixed": None,        # thay đổi theo project
        "desc_required": True,        # ticket/mô tả bắt buộc
        "desc_default": None,
    },
    "Annual Leave": {
        "project_fixed": PROJECT_ANNUAL_LEAVE,        # BẮT BUỘC
        "desc_required": False,
        "desc_default": None,
    },
    "Public Holiday": {
        "project_fixed": PROJECT_PUBLIC_HOLIDAY,      # BẮT BUỘC
        "desc_required": False,
        "desc_default": None,
    },
    "Special Leave": {
        "project_fixed": PROJECT_SPECIAL_LEAVE,       # BẮT BUỘC
        "desc_required": False,
        "desc_default": None,
    },
    "Sick Leave": {
        "project_fixed": PROJECT_SICK_LEAVE,          # BẮT BUỘC
        "desc_required": False,
        "desc_default": None,
    },
}

# Cặp (project_D, task_E) nào hợp lệ cho Production Support
PRODUCTION_SUPPORT_TASKS: set[str] = {
    "Issue Investigation", "DFU", "SDF",
    # UAT Support và Coding/UT KHÔNG dùng với Production Support
}

# NP task: khi project có PACSNP-xxxx prefix, desc_const luôn là này
NP_DESC_CONST = DESC_NEW_PRODUCT  # "New product day 2 items"
NP_TASK_NAMES_VALID: set[str] = {"Coding/UT", "UAT Support", "Investigation/Assessment"}
NP_PROJECT_PREFIX = "PACSNP-"


def validate_entry(project: str, task_name: str,
                   description: str, hours: float,
                   is_friday: bool = False) -> list[str]:
    """Validate 1 dòng timesheet: kiểm tra D/E/F khớp với rule.

    Trả list[str] errors — rỗng = hợp lệ.
    is_friday=True: lỗi cột F trống → ERROR (không cho gửi).
    is_friday=False: lỗi cột F trống → WARNING (hỏi lại).
    """
    errors: list[str] = []
    project = (project or "").strip()
    task_name = (task_name or "").strip()
    description = (description or "").strip()

    # 1. Task name phải hợp lệ
    if task_name not in VALID_COMBINATIONS:
        errors.append(
            f"Cột E '{task_name}' không hợp lệ. "
            f"Phải là một trong: {', '.join(VALID_COMBINATIONS)}"
        )
        return errors  # không check tiếp nếu E sai

    combo = VALID_COMBINATIONS[task_name]

    # 2. Project D phải khớp với E (nếu có ràng buộc).
    #    Ngoại lệ (25-Sep): Issue Investigation CHO 1 DỰ ÁN cụ thể ("prod issue,
    #    WR PACSNP-3083, mô tả …") → D = tên dự án người dùng chỉ định là hợp lệ.
    #    D trống vẫn là lỗi. (note_action vẫn tự đặt Production Support khi
    #    người dùng KHÔNG ghi mốc dự án.)
    if combo["project_fixed"] and not (
            task_name == TASK_ISSUE_INVESTIGATION and project.strip()):
        if project != combo["project_fixed"]:
            errors.append(
                f"Cột D '{project}' sai. "
                f"Với task '{task_name}', cột D phải là "
                f"'{combo['project_fixed']}'"
            )

    # 3. Production Support chỉ dùng với task nhất định
    if project == PROJECT_PRODUCTION_SUPPORT:
        if task_name not in PRODUCTION_SUPPORT_TASKS:
            errors.append(
                f"Cột D 'Production Support' không hợp lệ với "
                f"task '{task_name}'. "
                f"Production Support chỉ dùng với: "
                f"{', '.join(sorted(PRODUCTION_SUPPORT_TASKS))}"
            )

    # 4. NP task: PACSNP- prefix → desc phải = NP_DESC_CONST
    is_np = bool(project) and NP_PROJECT_PREFIX.upper() in project.upper()
    if is_np:
        # Issue Investigation cho dự án NP (vd prod issue của PACSNP-3083) hợp lệ
        if task_name not in NP_TASK_NAMES_VALID and task_name != TASK_ISSUE_INVESTIGATION:
            errors.append(
                f"NP task (PACSNP-) có cột E '{task_name}' không hợp lệ. "
                f"Phải là: {', '.join(NP_TASK_NAMES_VALID)}"
            )
        # NP constant "New product day 2 items" CHỈ áp dụng khi E = Coding/UT
        # hoặc Investigation/Assessment (không phải UAT Support)
        np_needs_const = task_name in ("Coding/UT", "Investigation/Assessment")
        if np_needs_const:
            if description and description != NP_DESC_CONST:
                errors.append(
                    f"NP task với '{task_name}' — cột F phải là "
                    f"'{NP_DESC_CONST}', không phải '{description}'"
                )
            # Nếu trống → pipeline tự điền, không phải lỗi
        # UAT Support cho NP: cột F = ticket, không cần NP constant

    # 5. Description (cột F) bắt buộc
    if combo["desc_required"] and not description and not is_np:
        msg = (
            f"Cột F (Description) trống cho task '{task_name}' — "
            f"cần có ticket/mô tả"
        )
        # Thứ 6: lỗi cứng (không cho gửi)
        # Ngày thường: cảnh báo (hỏi lại người dùng)
        prefix = "❌ LỖI" if is_friday else "⚠️ THIẾU"
        errors.append(f"{prefix}: {msg}")

    # 6. DFU/Investigation: ticket prefix đúng không?
    # Bỏ qua nếu là NP constant hoặc là NP task (F không cần ticket prefix).
    # Sửa 22-Sep: KHÔNG dùng startswith (chỉ xét ký tự đầu → sót ticket
    # nằm GIỮA mô tả, vd "làm cho INC002435..."). Nay dùng ALL_TICKET_RE
    # search: chỉ cần description CÓ CHỨA 1 ticket hợp lệ bất kỳ vị trí
    # nào (INC..., PACSDFUM-..., PACSGASIA-..., Ticket#...) là hợp lệ.
    ticket_prefix = get_ticket_prefix(task_name)
    if (ticket_prefix and description
            and description != NP_DESC_CONST
            and not is_np
            and not ALL_TICKET_RE.search(description)):
        errors.append(
            f"Cột F '{description[:30]}' có vẻ thiếu ticket. "
            f"Dự kiến có mã ticket (vd {ticket_prefix}xxxx hoặc INCxxxx)"
        )

    # 7. Giờ hợp lệ
    if hours <= 0 or hours > 24:
        errors.append(f"Giờ {hours} không hợp lệ (phải 0 < hours ≤ 24)")

    return errors


def validate_day_entries(entries: list[dict],
                         is_friday: bool = False) -> list[str]:
    """Validate tất cả entries của 1 ngày. Trả list errors."""
    all_errors = []
    total_hours = sum(float(e.get("hours") or 0) for e in entries)

    for e in entries:
        errs = validate_entry(
            project=e.get("project", ""),
            task_name=e.get("task", ""),
            description=e.get("description", ""),
            hours=float(e.get("hours") or 0),
            is_friday=is_friday,
        )
        for err in errs:
            day_str = str(e.get("date", ""))
            all_errors.append(f"[{day_str}] {err}")

    if abs(total_hours - 8.0) > 0.01 and total_hours > 0:
        all_errors.append(
            f"Tổng giờ = {total_hours}h (phải đủ 8h)"
        )
    return all_errors


if __name__ == "__main__":
    print("=" * 60)
    print("TASK RULES — SELF TEST")
    print("=" * 60)

    tests = [
        # (input text,         expected_task,               expected_project_const,      expected_desc_const)
        ("dfu",                TASK_DFU,                    PROJECT_PRODUCTION_SUPPORT,  None),
        ("patch data",         TASK_DFU,                    PROJECT_PRODUCTION_SUPPORT,  None),
        ("sdf",                TASK_SDF,                    PROJECT_PRODUCTION_SUPPORT,  None),
        ("prod issue code",    TASK_SDF,                    PROJECT_PRODUCTION_SUPPORT,  None),
        ("investigate",        TASK_ISSUE_INVESTIGATION,    PROJECT_PRODUCTION_SUPPORT,  None),
        ("check issue",        TASK_ISSUE_INVESTIGATION,    PROJECT_PRODUCTION_SUPPORT,  None),
        ("weekly softlock",    TASK_ISSUE_INVESTIGATION,    PROJECT_PRODUCTION_SUPPORT,  None),
        ("np",                 TASK_CODING_UT,              None,                        DESC_NEW_PRODUCT),
        ("new product",        TASK_CODING_UT,              None,                        DESC_NEW_PRODUCT),
        ("coding np",          TASK_CODING_UT,              None,                        DESC_NEW_PRODUCT),
        ("uat",                TASK_UAT_SUPPORT,            None,                        None),
        ("uat support",        TASK_UAT_SUPPORT,            None,                        None),
        ("nghỉ phép",          TASK_ANNUAL_LEAVE,           PROJECT_ANNUAL_LEAVE,        None),
        ("off",                TASK_ANNUAL_LEAVE,           PROJECT_ANNUAL_LEAVE,        None),
        ("nghỉ lễ",            TASK_PUBLIC_HOLIDAY,         PROJECT_PUBLIC_HOLIDAY,      None),
        ("nghỉ bù",            TASK_SPECIAL_LEAVE,          PROJECT_SPECIAL_LEAVE,       None),
        ("nghỉ bệnh",          TASK_SICK_LEAVE,             PROJECT_SICK_LEAVE,          None),
        ("nghỉ ốm",            TASK_SICK_LEAVE,             PROJECT_SICK_LEAVE,          None),
        ("coding",             TASK_CODING_UT,              None,                        None),
        ("assess",             TASK_INVESTIGATION_ASSESSMENT, None,                      None),
    ]
    # Xác nhận NP rule có desc_const đúng
    np_rule = find_rule_by_keyword("np")
    assert np_rule is not None and np_rule.desc_const == DESC_NEW_PRODUCT
    assert np_rule.task_name == TASK_CODING_UT  # mặc định
    assert np_rule.ticket_prefix == "PACSNP-"
    print("  ✓ NP rule: desc_const='New product day 2 items', ticket_prefix='PACSNP-'")
    print("  ✓ NP rule: cột E có thể là Coding/UT, UAT Support, Investigation/Assessment (AI chọn)")

    all_ok = True
    for text, exp_task, exp_proj, exp_desc in tests:
        rule = find_rule_by_keyword(text)
        if rule is None:
            print(f"  ✗ '{text}' → không tìm thấy rule!")
            all_ok = False
            continue
        t_ok = rule.task_name == exp_task
        p_ok = rule.project_const == exp_proj
        d_ok = rule.desc_const == exp_desc
        ok   = t_ok and p_ok and d_ok
        if not ok: all_ok = False
        mark = "✓" if ok else "✗"
        print(f"  {mark} '{text}'")
        if not t_ok: print(f"      task: '{rule.task_name}' ≠ '{exp_task}'")
        if not p_ok: print(f"      proj: '{rule.project_const}' ≠ '{exp_proj}'")
        if not d_ok: print(f"      desc: '{rule.desc_const}' ≠ '{exp_desc}'")

    print(f"\n>>> {'ALL GREEN' if all_ok else 'CÓ LỖI'} <<<")
    print(f"\n{'='*60}")
    print("PROMPT SNIPPET (inject vào AI):")
    print("=" * 60)
    print(build_column_mapping_prompt())
