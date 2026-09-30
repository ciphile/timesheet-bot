"""
task_names.py — Danh sách Task Name chuẩn hóa cho cột E timesheet.

ĐÂY LÀ NGUỒN SỰ THẬT DUY NHẤT cho giá trị cột E.
- Thêm task mới: thêm vào TASK_NAMES và TASK_ALIASES bên dưới.
- KHÔNG hardcode tên task ở bất kỳ file nào khác.
- Thứ tự trong TASK_NAMES không quan trọng — chỉ là danh sách tham chiếu.
"""

# ===========================================================================
# DANH SÁCH TASK NAME CHUẨN (cột E trong Excel)
# Cập nhật lần cuối: 19-Sep-2026 — đọc từ 5 mẫu timesheet thực tế
#
# PHÂN BIỆT QUAN TRỌNG:
#   Cột D (Project Name): tên project/ticket/loại công việc tổng quát
#     Ví dụ: "Group Asia - Member Movement", "PACSNP-2207",
#             "Production Support", "Annual Leave", "Public Holiday"
#   Cột E (Task Name)  : HÀNH ĐỘNG thực hiện — chỉ dùng các giá trị trong file này
#     Ví dụ: "Coding/UT", "DFU", "Issue Investigation", "Annual Leave"
#
#   "Production Support" = Project Name (cột D) khi project là production
#   Task Name tương ứng = "Issue Investigation" hoặc "DFU" tùy hành động
# ===========================================================================
TASK_NAMES: list[str] = [
    "Coding/UT",                 # code mới, unit test, enhancement
    "Investigation/Assessment",  # phân tích, đánh giá, research
    "DFU",                       # deploy, fix urgent, patch, vá
    "UAT Support",               # hỗ trợ UAT, test acceptance
    "Issue Investigation",       # điều tra vấn đề production, check ticket
    "Annual Leave",              # nghỉ phép năm
    "Public Holiday",            # nghỉ lễ công cộng
    "Special Leave",             # nghỉ bù, nghỉ đặc biệt
    "Sick Leave",                # nghỉ bệnh, nghỉ ốm (cần MC)
    "SDF",                       # SDF task (giữ nguyên nếu xuất hiện)
]

# ===========================================================================
# MAPPING ALIAS → TASK NAME CHUẨN
# Dùng cho rule-based fallback khi AI không parse được.
# Mỗi alias là lowercase, AI prompt cũng dùng danh sách này.
# ===========================================================================
TASK_ALIASES: dict[str, str] = {
    # Coding/UT
    "code": "Coding/UT",
    "coding": "Coding/UT",
    "code mới": "Coding/UT",
    "viết code": "Coding/UT",
    "lập trình": "Coding/UT",
    "enhancement": "Coding/UT",
    "enhance": "Coding/UT",
    "unit test": "Coding/UT",
    "ut": "Coding/UT",
    "develop": "Coding/UT",
    "development": "Coding/UT",
    "implement": "Coding/UT",
    "np": "Coding/UT",              # new product thường = coding

    # Investigation/Assessment
    "investigate": "Investigation/Assessment",
    "investigation": "Investigation/Assessment",
    "assess": "Investigation/Assessment",
    "assessment": "Investigation/Assessment",
    "phân tích": "Investigation/Assessment",
    "đánh giá": "Investigation/Assessment",
    "research": "Investigation/Assessment",
    "tìm hiểu": "Investigation/Assessment",
    "xem xét": "Investigation/Assessment",
    "check issue": "Investigation/Assessment",
    "issue investigation": "Investigation/Assessment",

    # DFU
    "dfu": "DFU",
    "patch": "DFU",
    "patching": "DFU",
    "vá": "DFU",
    "fix": "DFU",
    "hotfix": "DFU",
    "deploy": "DFU",
    "deployment": "DFU",
    "release": "DFU",
    "dfu & patching": "DFU",

    # UAT Support
    "uat": "UAT Support",
    "uat support": "UAT Support",
    "user acceptance": "UAT Support",
    "acceptance test": "UAT Support",
    "kiểm thử": "UAT Support",

    # Issue Investigation (Task Name cột E)
    # LƯU Ý: "Production Support" = PROJECT (cột D), KHÔNG phải task name
    # Khi người dùng nói làm gì đó ở môi trường production → task name là:
    #   - "Issue Investigation" nếu đang điều tra/check
    #   - "DFU" nếu đang patch/fix/deploy
    "issue investigation": "Issue Investigation",
    "prod support": "Issue Investigation",
    "production support": "Issue Investigation",
    "prod issue": "Issue Investigation",
    "production issue": "Issue Investigation",
    "hỗ trợ production": "Issue Investigation",
    "điều tra": "Issue Investigation",
    "check ticket": "Issue Investigation",
    "investigate": "Issue Investigation",
    "investigation": "Issue Investigation",

    # Annual Leave
    "annual leave": "Annual Leave",
    "nghỉ phép": "Annual Leave",
    "nghỉ": "Annual Leave",
    "off": "Annual Leave",
    "leave": "Annual Leave",
    "phép": "Annual Leave",

    # Public Holiday
    "public holiday": "Public Holiday",
    "nghỉ lễ": "Public Holiday",
    "lễ": "Public Holiday",
    "holiday": "Public Holiday",

    # Special Leave
    "special leave": "Special Leave",
    "nghỉ bù": "Special Leave",
    "bù": "Special Leave",
    "nghỉ đặc biệt": "Special Leave",

    # Sick Leave (nghỉ bệnh, cần MC)
    "sick leave": "Sick Leave",
    "sick": "Sick Leave",
    "nghỉ bệnh": "Sick Leave",
    "nghỉ ốm": "Sick Leave",
    "bị bệnh": "Sick Leave",
    "bị ốm": "Sick Leave",
    "medical leave": "Sick Leave",
}

# ===========================================================================
# PROMPT SNIPPET — nạp vào AI để map ngôn ngữ tự nhiên → task name chuẩn
# ===========================================================================
def build_task_name_prompt_section() -> str:
    """Trả đoạn prompt mô tả TASK_NAMES để inject vào prompt parse.
    AI dùng danh sách này để map text tự nhiên → task name chuẩn."""
    names_block = "\n".join(f'  - "{t}"' for t in TASK_NAMES)
    aliases_examples = [
        ('code, coding, unit test, enhancement, NP', 'Coding/UT'),
        ('investigate, assess, assessment, phân tích, check issue', 'Investigation/Assessment'),
        ('dfu, patch, vá, fix, hotfix, deploy', 'DFU'),
        ('uat, uat support, kiểm thử', 'UAT Support'),
        ('issue investigation, prod issue, investigate, điều tra', 'Issue Investigation'),
        ('nghỉ phép, nghỉ, off, leave', 'Annual Leave'),
        ('nghỉ lễ, public holiday, holiday', 'Public Holiday'),
        ('nghỉ bù, nghỉ đặc biệt, special leave', 'Special Leave'),
        ('nghỉ bệnh, nghỉ ốm, bị bệnh, sick leave', 'Sick Leave'),
    ]
    examples_block = "\n".join(
        f'  "{src}" → "{dst}"' for src, dst in aliases_examples)

    return f"""
TASK NAME (cột E Excel) — CHỈ dùng đúng các giá trị sau, KHÔNG sáng tạo thêm:
{names_block}

Mapping từ ngôn ngữ tự nhiên → task name chuẩn:
{examples_block}

Quy tắc mapping:
- Nếu người dùng nói "DFU" và "investigation/check" trong cùng 1 task
  → "DFU" (ưu tiên action cuối cùng thực hiện)
- Nếu không map được vào bất kỳ giá trị nào ở trên
  → dùng "Coding/UT" làm mặc định VÀ đặt vào "unclear_days" để hỏi lại
- KHÔNG được tự đặt giá trị ngoài danh sách trên
""".strip()


def normalize_task_name(raw: str) -> str | None:
    """Rule-based fallback: map text thô → task name chuẩn.
    Trả None nếu không match — khi đó dùng AI để quyết định.
    """
    key = raw.strip().lower()
    # Exact match alias
    if key in TASK_ALIASES:
        return TASK_ALIASES[key]
    # Exact match với tên chuẩn (case-insensitive)
    for name in TASK_NAMES:
        if key == name.lower():
            return name
    # Partial match (cẩn thận — chỉ dùng khi key đủ dài)
    # Ưu tiên alias DÀI NHẤT: "bị bệnh nên nghỉ" phải ra Sick Leave, không
    # được khớp "nghỉ" (Annual Leave) trước chỉ vì "nghỉ" khai báo trước.
    if len(key) >= 4:
        for alias in sorted(TASK_ALIASES, key=len, reverse=True):
            if alias in key:
                return TASK_ALIASES[alias]
    return None


if __name__ == "__main__":
    # Test nhanh
    tests = [
        ("code",                 "Coding/UT"),
        ("Coding",               "Coding/UT"),
        ("unit test",            "Coding/UT"),
        ("NP",                   "Coding/UT"),
        ("assess",               "Investigation/Assessment"),
        ("phân tích",            "Investigation/Assessment"),
        ("check issue",          "Investigation/Assessment"),
        ("dfu",                  "DFU"),
        ("patch",                "DFU"),
        ("vá lỗi",               "DFU"),
        ("uat",                  "UAT Support"),
        ("prod support",         "Issue Investigation"),
        ("nghỉ phép",            "Annual Leave"),
        ("off",                  "Annual Leave"),
        ("nghỉ lễ",              "Public Holiday"),
        ("nghỉ bù",              "Special Leave"),
        ("nghỉ bệnh",            "Sick Leave"),
        ("bị bệnh nên nghỉ",     "Sick Leave"),
        ("xyz_unknown",          None),
    ]
    print(f"TASK_NAMES ({len(TASK_NAMES)} giá trị):", TASK_NAMES)
    print(f"\nTest normalize_task_name:")
    all_ok = True
    for raw, expected in tests:
        result = normalize_task_name(raw)
        ok = result == expected
        if not ok: all_ok = False
        print(f"  {'✓' if ok else '✗'} '{raw}' → '{result}' (kỳ vọng: '{expected}')")
    print(f"\n>>> {'ALL GREEN' if all_ok else 'CÓ LỖI'} <<<")
    print(f"\nPrompt snippet (inject vào AI):\n{build_task_name_prompt_section()}")
