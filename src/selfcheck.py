"""
selfcheck.py — Kiểm tra toàn bộ cài đặt trên máy có ĐỒNG BỘ không.

Vì sao cần: người dùng chép file thủ công từ chat về nhiều đợt, rất dễ sót
1-2 file -> máy chạy LẪN LỘN bản cũ và bản mới. Kiểu lỗi này rất khó
nhận ra (bot vẫn chạy, chỉ im lặng thiếu tính năng hoặc sai hành vi),
vd 17-Sep-2026 đã gặp:
  - sg_holidays.py bản cũ  -> AttributeError ensure_next_year_cached
  - settings.json bản cũ   -> bot vẫn tự tắt 22:50 thay vì 23:59

Chạy sau MỖI LẦN chép file mới:
    cd thư mục timesheet\\src
    python selfcheck.py

Không cần mạng, không tốn lượt AI, không đụng dữ liệu thật.
"""

import sys
from datetime import date

PASS, FAIL, WARN = "  [OK]  ", "  [SAI] ", "  [!]   "

results = []


def check(label: str, ok: bool, detail: str = "", warn_only=False):
    results.append((label, ok, detail, warn_only))
    mark = PASS if ok else (WARN if warn_only else FAIL)
    print(f"{mark}{label}" + (f" — {detail}" if detail else ""))


def main():
    print("=" * 62)
    print("KIỂM TRA CÀI ĐẶT TIMESHEET BOT")
    print("=" * 62)

    # ---------- 1) Các module phải import được ----------
    print("\n1. Các module:")
    modules = ["config_loader", "log_setup", "audit_log", "notes_store",
               "state", "daily_store", "validator", "sg_holidays",
               "excel_writer", "mailer", "ai_client", "pipeline",
               "orchestrator", "housekeeping", "weekly_run"]
    loaded = {}
    for name in modules:
        try:
            loaded[name] = __import__(name)
            check(f"{name}.py", True)
        except Exception as e:
            check(f"{name}.py", False, f"{type(e).__name__}: {e}")

    # ---------- 2) Hàm/hằng BẮT BUỘC phải có (bắt file bản cũ) ----------
    print("\n2. Tính năng phải có (thiếu = file còn bản cũ, chép lại):")
    required = {
        "sg_holidays": ["ensure_next_year_cached", "prune_old_caches",
                        "workday_holidays", "saturday_holidays"],
        "state": ["state_lock", "async_state_lock", "remember_questions",
                  "pending_questions", "clear_stale_lock_at_startup",
                  "MAX_SENT_DAYS_KEEP"],
        "pipeline": ["open_window", "recent_history",
                     "describe_day", "postprocess_ai_days"],
        "orchestrator": ["prepare_draft", "apply_edit", "finalize_and_send",
                         "make_draft_seal", "draft_seal_changes",
                         "prepare_past_edit", "apply_past_edit",
                         "resend_months", "chunk_text",
                         "prepare_send_preview", "prepare_resend_preview"],
        "daily_store": ["save_day", "forget_day", "entries_for_days",
                        "prune_before"],
        "housekeeping": ["run", "prune_notes", "trim_audit_log",
                         "prune_holiday_caches", "snapshot_parsed_days",
                         "migrate_old_backups"],
        "ai_client": ["generate_json", "list_available_models",
                      "usage_summary", "BudgetExceeded"],
        "excel_writer": ["write_month_entries", "read_month_entries",
                         "make_delivery_copy", "delivery_file_name"],
        "mailer": ["send_email", "build_subject", "build_body",
                   "build_special_leave_note", "get_mail_route",
                   "build_email_preview", "failure_message"],
        # ── thêm 24-Sep (bản 11.0) ──
        "company_mailer": ["send_email_company", "check_connection"],
        "mail_errors": ["classify", "check_refused", "precheck_attachments",
                        "SendFailed"],
        "leave_balance": ["compute_balance", "entitlement", "parse_update",
                          "pick_sl_credit"],
        "status_report": ["build_status"],
        "note_action": ["parse_actions", "actions_from_rule_parser",
                        "ensure_all_tickets", "mc_reminder", "persist_actions"],
        "task_rules": ["canon_ticket", "normalize_ticket_text",
                       "TASK_SICK_LEAVE"],
        "date_normalizer": ["expand_multi_day_span"],
        "compose_email": ["fmt_leave_day"],
        "config_loader": ["DATA_BACKUP_DIR", "NOTES_BAK_DIR", "PARSED_BAK_DIR",
                          "PARSED_SNAPSHOT_DIR", "CORRUPT_DIR"],
        "validator": ["find_issues", "describe_issues", "issue_lines", "split_hours",
                      "period_bounds"],
        "notes_store": ["add_note", "read_notes_between"],
    }
    for mod_name, attrs in required.items():
        mod = loaded.get(mod_name)
        if mod is None:
            continue
        missing = [a for a in attrs if not hasattr(mod, a)]
        check(f"{mod_name}: {len(attrs) - len(missing)}/{len(attrs)} tính năng",
              not missing,
              f"THIẾU: {', '.join(missing)} -> chép lại {mod_name}.py"
              if missing else "")

    # ---------- 3) Cấu hình ----------
    print("\n3. Cấu hình (config\\settings.json + secrets.env):")
    try:
        from config_loader import load_config
        cfg = load_config()
        check("Đọc được cấu hình", True)

        stop = cfg.get("bot_stop_time")
        check(f"bot_stop_time = {stop!r}", stop == "23:59",
              "người dùng đã chốt 23:59 — sửa dòng này trong settings.json"
              if stop != "23:59" else "")

        model = str(cfg.get("gemini_model")).strip()
        auto = model.lower() in ("auto", "latest")
        check(f"gemini_model = {model!r}", True,
              "TỰ ĐỘNG — hệ thống tự dò model mới nhất từ Google (tốt "
              "nhất, Google đổi tên model vẫn chạy)" if auto else
              "Đang ghim tên cụ thể. Nếu model này bị khai tử, hệ thống "
              'vẫn tự chuyển model khác, nhưng nên để "auto" cho gọn.',
              warn_only=True)

        # Model đã dò được lần gần nhất (nếu có cache)
        try:
            import ai_client, json as _json
            from datetime import datetime as _dt
            if ai_client.MODEL_CACHE_FILE.exists():
                cached = _json.loads(
                    ai_client.MODEL_CACHE_FILE.read_text(encoding="utf-8"))
                resolved = cached.get("resolved_at", "")
                model_name = cached.get("model", "?")
                try:
                    age_days = (_dt.now() - _dt.fromisoformat(resolved)).days
                    expires = ai_client.MODEL_CACHE_DAYS - age_days
                    freshness = (f"còn hạn {expires} ngày" if expires > 0
                                 else f"HẾT HẠN {-expires} ngày trước "
                                      "(sẽ dò lại lần dùng AI kế)")
                except Exception:
                    freshness = f"dò lúc {resolved}"
                check(f"Model đang dùng: {model_name!r}", True,
                      freshness + " | refresh do housekeeping mỗi ngày bot bật",
                      warn_only=True)
            else:
                check("Cache model", True,
                      "chưa dò lần nào — sẽ tự dò ở lần gọi AI đầu tiên",
                      warn_only=True)
        except Exception:
            pass

        check(f"boss_email = {cfg.get('boss_email')!r}", True,
              ">>> ĐANG Ở CHẾ ĐỘ TEST (gửi về chính mình)"
              if cfg.get("boss_email") in (cfg.get("bcc_email"), __import__("config_loader").personal("bcc_when_company")) else
              ">>> ĐANG TRỎ SẾP THẬT", warn_only=True)
        check(f"bcc_email = {cfg.get('bcc_email')!r}",
              bool(cfg.get("bcc_email")))
    except Exception as e:
        check("Đọc cấu hình", False, f"{type(e).__name__}: {e}")
        cfg = None

    # ---------- 4) File/thư mục ----------
    print("\n4. File và thư mục:")
    if cfg:
        from config_loader import (BASE_DIR, DATA_DIR, OUTPUT_DIR,
                                   BACKUP_DIR, TEMPLATE_DIR)
        tpl = TEMPLATE_DIR / "master_template.xlsx"
        check("template\\master_template.xlsx", tpl.exists(),
              "THIẾU -> không ghi được Excel" if not tpl.exists() else "")
        for d in (DATA_DIR, OUTPUT_DIR, BACKUP_DIR):
            check(f"{d.name}\\", d.exists())
        # Windows: start_bot.vbs · Mac: start_bot.command
        launcher = next((BASE_DIR / n for n in ("start_bot.vbs", "start_bot.command")
                         if (BASE_DIR / n).exists()), None)
        check("file bật bot (start_bot.vbs / start_bot.command)", launcher is not None,
              "THIẾU -> lịch tự động không chạy bot nền được"
              if launcher is None else "")

    # ---------- 5) Lịch nghỉ lễ ----------
    print("\n5. Lịch nghỉ lễ Singapore (cache, không cần mạng):")
    if cfg:
        try:
            import sg_holidays
            this_year = date.today().year
            for y in (this_year, this_year + 1):
                cached = sg_holidays._load_cache(y)
                check(f"Lịch lễ năm {y}", cached is not None,
                      f"{len(cached)} ngày" if cached else
                      ("chưa có — sẽ tự fetch khi cần"
                       if y > this_year else
                       "CHƯA CÓ -> chạy: python sg_holidays.py"),
                      warn_only=(y > this_year))
        except Exception as e:
            check("Lịch nghỉ lễ", False, str(e))

    # ---------- Tổng kết ----------
    print("\n" + "=" * 62)
    hard_fails = [r for r in results if not r[1] and not r[3]]
    warns = [r for r in results if not r[1] and r[3]]
    if hard_fails:
        print(f"CÓ {len(hard_fails)} VẤN ĐỀ CẦN SỬA:")
        for label, _, detail, _ in hard_fails:
            print(f"  - {label}: {detail}")
        print("\nSửa xong chạy lại: python selfcheck.py")
        return 1
    print("TẤT CẢ ĐỒNG BỘ — máy đang chạy đúng bản mới nhất.")
    if warns:
        print("\nLưu ý (không phải lỗi):")
        for label, _, detail, _ in warns:
            print(f"  - {label}: {detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
