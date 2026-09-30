"""
leave_balance.py — Tính số ngày phép còn lại (thêm 24-Sep-2026).

3 loại:
  Annual Leave  : 17 ngày / năm dương lịch (1/1–31/12), dư KHÔNG chuyển năm sau
  Sick Leave    : 14 ngày / năm (cần MC)
  Special Leave : +1 ngày cho MỖI lễ rơi THỨ 7 (lịch MOM, sg_holidays).
                  Chỉ có hiệu lực 3 THÁNG kể từ ngày lễ (hết hạn = ngày lễ
                  + 3 tháng, tính CẢ ngày đó). Dùng ngày bù sắp hết hạn trước.

NGUYÊN TẮC (quan trọng): KHÔNG lưu bộ đếm cộng/trừ mỗi lần gửi mail. Mỗi
lần cần (/leavebal, sau khi gửi, sau khi gởi lại) đều TÍNH LẠI TỪ ĐẦU:
  - "đã chốt"  = đọc file Excel tháng (bản đã gửi sếp) của cả năm
  - "dự kiến"  = đã chốt + các ngày CHƯA gửi trong parsed_days
→ gởi lại 3 lần cũng không trừ trùng; sửa quá khứ bằng /edittimesheet thì
  lần tính sau tự đúng.
Nghỉ nửa ngày: giờ / hours_per_day (4h = 0,5 ngày).

/updateleave đặt MỐC: "ngày X còn N ngày" → từ đó chỉ trừ phần dùng SAU
ngày X. Dùng khi số tự tính sai, hoặc các tháng trước khi có bot (không
có file Excel để đếm). Mốc chỉ có hiệu lực trong năm của nó.
"""

from __future__ import annotations

from datetime import date, timedelta

from log_setup import get_logger

log = get_logger("leave_balance")

# Số ngày được phép mỗi năm — ĐỌC TỪ settings.json (xem entitlement()).
# 2 số dưới chỉ là MẶC ĐỊNH khi settings.json chưa khai báo.
DEFAULT_AL_PER_YEAR = 17
DEFAULT_SICK_PER_YEAR = 14
SL_VALID_MONTHS = 3
EXPIRY_WARN_DAYS = 14

TYPES = {"annual": "Annual Leave", "sick": "Sick Leave",
         "special": "Special Leave"}
LABEL = {"annual": "Annual Leave (phép năm)", "sick": "Sick Leave (nghỉ bệnh)",
         "special": "Special Leave (nghỉ bù)"}
_TASK_TO_TYPE = {v: k for k, v in TYPES.items()}
_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ---------------------------------------------------------------------
# Tiện ích ngày
# ---------------------------------------------------------------------
def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    nxt = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
    return date(y, m, min(d.day, (nxt - timedelta(days=1)).day))


def sl_expiry(ph: date) -> date:
    """Ngày cuối được dùng ngày bù của lễ thứ 7 `ph` (tính cả ngày này)."""
    return add_months(ph, SL_VALID_MONTHS)


def _dm(d: date) -> str:
    return f"{d.day}/{d.month}"


def _num(x: float) -> str:
    return f"{x:g}".replace(".", ",")


# ---------------------------------------------------------------------
# Số ngày được phép / năm (đổi trong settings.json, KHÔNG cần sửa code)
# ---------------------------------------------------------------------
def _valid_quota(v) -> bool:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return False
    return 0 <= f <= 60 and abs(f * 2 - round(f * 2)) < 1e-9


def entitlement(config, year: int) -> dict:
    """Số ngày Annual / Sick được phép trong `year`. Thứ tự ưu tiên:
      1. settings.json "leave_entitlement_by_year": {"2028": {"annual": 18}}
         (điền TRƯỚC cho năm sau mà không ảnh hưởng năm nay)
      2. settings.json "annual_leave_per_year" / "sick_leave_per_year"
      3. mặc định trong code (17 / 14)
    Giá trị sai (chữ, âm, > 60, lẻ không phải 0,5) → bỏ qua, ghi log, dùng
    mức kế tiếp — KHÔNG làm sập bot. Trả {"annual","sick","source"}."""
    s = getattr(config, "settings", {}) or {}
    out = {"annual": float(DEFAULT_AL_PER_YEAR),
           "sick": float(DEFAULT_SICK_PER_YEAR), "source": "mặc định"}
    for kind, key in (("annual", "annual_leave_per_year"),
                      ("sick", "sick_leave_per_year")):
        if key in s:
            if _valid_quota(s[key]):
                out[kind] = float(s[key]); out["source"] = "settings.json"
            else:
                log.warning("settings.json %s=%r không hợp lệ — dùng %g.",
                            key, s[key], out[kind])
    by_year = (s.get("leave_entitlement_by_year") or {}).get(str(year)) or {}
    for kind in ("annual", "sick"):
        if kind in by_year:
            if _valid_quota(by_year[kind]):
                out[kind] = float(by_year[kind])
                out["source"] = f"settings.json (riêng năm {year})"
            else:
                log.warning("leave_entitlement_by_year[%s][%s]=%r không hợp "
                            "lệ — bỏ qua.", year, kind, by_year[kind])
    return out


# ---------------------------------------------------------------------
# Nguồn dữ liệu
# ---------------------------------------------------------------------
def _hpd(config) -> float:
    return float(config.get("hours_per_day") or 8)


EXCEL_READ_ERRORS: list = []   # tháng có file Excel đọc lỗi ở lần tính gần nhất


def sent_usage(year: int, config) -> list[dict]:
    """Ngày nghỉ trong các file Excel tháng của năm (= bản đã gửi sếp)."""
    import excel_writer
    hpd, out = _hpd(config), []
    for m in range(1, 13):
        try:
            rows = excel_writer.read_month_entries(date(year, m, 1), config)
        except Exception as e:  # noqa: BLE001 — 1 file hỏng không được làm sập cả phần tính phép
            log.warning("Không đọc được file Excel tháng %d/%d (%s) — bỏ qua "
                        "tháng này khi tính phép.", m, year, e)
            EXCEL_READ_ERRORS.append(f"{m:02d}/{year}")
            continue
        for e in rows:
            t = _TASK_TO_TYPE.get(e.get("task"))
            if t and e["date"].year == year:
                out.append({"date": e["date"], "type": t,
                            "days": float(e.get("hours") or 0) / hpd,
                            "sent": True})
    return out


def pending_usage(year: int, state: dict, config) -> list[dict]:
    """Ngày nghỉ trong parsed_days CHƯA gửi sếp (sau last_sent)."""
    import daily_store
    import state as state_mod
    last = state_mod.last_sent_date(state)
    hpd, out = _hpd(config), []
    for iso, day in daily_store.load_all().items():
        d = date.fromisoformat(iso)
        if d.year != year or (last is not None and d <= last):
            continue
        for e in day.get("entries", []):
            t = _TASK_TO_TYPE.get(e.get("task"))
            if t:
                out.append({"date": d, "type": t,
                            "days": float(e.get("hours") or 0) / hpd,
                            "sent": False})
    return out


def sl_credits(year: int, config) -> list[dict]:
    """Ngày bù phát sinh liên quan năm `year`: lễ thứ 7 trong năm, và lễ
    thứ 7 năm TRƯỚC mà hạn 3 tháng còn kéo sang năm nay."""
    import sg_holidays
    out = []
    for y in (year - 1, year):
        try:
            sats = sg_holidays.saturday_holidays(y, config=config)
        except Exception as e:  # noqa: BLE001 — thiếu lịch năm cũ không sao
            log.warning("Không lấy được lễ thứ 7 năm %s (%s).", y, e)
            continue
        for iso, name in sats:
            ph = date.fromisoformat(iso)
            exp = sl_expiry(ph)
            if ph.year == year or exp >= date(year, 1, 1):
                out.append({"ph": ph, "name": name, "expiry": exp,
                            "remaining": 1.0})
    return sorted(out, key=lambda c: c["ph"])


def pick_sl_credit(sl_day: date, credits_ph: list, used_ph: set):
    """Chọn lễ-thứ-7 để gắn cho 1 ngày Special Leave: phải CÒN HẠN tại
    ngày đó (lễ < ngày nghỉ bù <= hết hạn), chưa bị dùng; ưu tiên lễ SẮP
    HẾT HẠN trước. Trả date lễ hoặc None. (Dùng chung với orchestrator.)"""
    ok = [ph for ph in credits_ph
          if ph not in used_ph and ph < sl_day <= sl_expiry(ph)]
    return min(ok, key=sl_expiry) if ok else None


def _allocate_sl(credits: list, usages: list, links: dict) -> list:
    """Trừ ngày Special Leave vào ngày bù. Ưu tiên liên kết đã có trong
    state (đã báo sếp trong email), còn lại: lễ còn hạn, sắp hết hạn trước.
    Sửa `credits` tại chỗ, trả list ngày Special Leave KHÔNG khớp lễ nào."""
    by_ph = {c["ph"]: c for c in credits}
    unmatched = []
    for u in sorted(usages, key=lambda x: x["date"]):
        need = u["days"]
        # 1) liên kết có sẵn (sat_iso → sl_iso)
        for sat_iso, sl_iso in links.items():
            c = by_ph.get(date.fromisoformat(sat_iso))
            if sl_iso == u["date"].isoformat() and c and c["remaining"] > 0:
                take = min(need, c["remaining"])
                c["remaining"] -= take
                need -= take
        # 2) còn thiếu → lễ còn hạn, sắp hết hạn trước
        for c in sorted(credits, key=lambda c: c["expiry"]):
            if need <= 1e-9:
                break
            if c["remaining"] > 0 and c["ph"] < u["date"] <= c["expiry"]:
                take = min(need, c["remaining"])
                c["remaining"] -= take
                need -= take
        if need > 1e-9:
            unmatched.append(u["date"])
    return unmatched


# ---------------------------------------------------------------------
# Tính số dư
# ---------------------------------------------------------------------
def _baseline(state: dict, kind: str, year: int):
    b = (state.get("leave_baseline") or {}).get(kind)
    if not b:
        return None
    try:
        as_of = date.fromisoformat(b["as_of"])
    except (KeyError, ValueError, TypeError):
        return None
    if as_of.year != year:
        return None
    out = {"value": float(b["value"]), "as_of": as_of}
    if "conf_at_set" in b:                 # mốc kiểu MỚI (24-Sep): ảnh chụp dữ liệu
        out["conf_at_set"] = float(b["conf_at_set"])
        out["pend_at_set"] = float(b.get("pend_at_set") or 0)
    return out


def _usage_totals(config, state: dict, year: int) -> dict:
    """Tổng ngày đã dùng mỗi loại: {kind: (đã chốt, chưa gửi)} tại lúc gọi."""
    sent = sent_usage(year, config)
    pend = pending_usage(year, state, config)
    return {k: (sum(u["days"] for u in sent if u["type"] == k),
                sum(u["days"] for u in pend if u["type"] == k)) for k in TYPES}


def _snapshot_balance(bl: dict, conf_now: float, pend_now: float):
    """Mốc kiểu MỚI: con số người dùng nhập = số dư SAU MỌI dữ liệu lúc đặt mốc.
    Sau đó MỌI thay đổi (kể cả sửa ngày CŨ trước mốc) đều trừ/cộng lại:
      đã chốt = mốc − (đã chốt bây giờ − đã chốt lúc đặt)
      dự kiến = đã chốt − (chưa gửi bây giờ − chưa gửi lúc đặt)
    Ngày chưa gửi được gửi đi → chuyển từ 'chưa gửi' sang 'đã chốt' → số dư
    dự kiến giữ nguyên (không trừ 2 lần)."""
    d_conf = conf_now - bl["conf_at_set"]
    d_pend = pend_now - bl["pend_at_set"]
    return bl["value"] - d_conf, bl["value"] - d_conf - d_pend, d_pend


def compute_balance(config, state: dict = None, today: date = None) -> dict:
    """Tính số dư 3 loại phép. Trả dict (xem format_balance để hiểu cấu trúc)."""
    import state as state_mod
    state = state if state is not None else state_mod.load_state()
    today = today or date.today()
    year = today.year
    EXCEL_READ_ERRORS.clear()
    sent = sent_usage(year, config)
    pend = pending_usage(year, state, config)
    result = {"year": year, "today": today,
              "excel_errors": list(EXCEL_READ_ERRORS), "log": sorted(
        sent + pend, key=lambda u: (u["date"], u["type"]))}

    ent = entitlement(config, year)
    result["entitlement_source"] = ent["source"]
    for kind, entitled in (("annual", ent["annual"]), ("sick", ent["sick"])):
        bl = _baseline(state, kind, year)
        if bl and "conf_at_set" in bl:
            conf_now = sum(u["days"] for u in sent if u["type"] == kind)
            pend_now = sum(u["days"] for u in pend if u["type"] == kind)
            b_c, b_p, d_p = _snapshot_balance(bl, conf_now, pend_now)
            result[kind] = {"entitled": entitled, "baseline": bl,
                            "used_confirmed": conf_now, "used_pending": max(d_p, 0.0),
                            "balance_confirmed": b_c, "balance_projected": b_p}
            continue
        after = (lambda u, b=bl: u["type"] == kind
                 and (b is None or u["date"] > b["as_of"]))
        used_s = sum(u["days"] for u in sent if after(u))
        used_p = sum(u["days"] for u in pend if after(u))
        start = bl["value"] if bl else entitled
        result[kind] = {"entitled": entitled, "baseline": bl,
                        "used_confirmed": used_s, "used_pending": used_p,
                        "balance_confirmed": start - used_s,
                        "balance_projected": start - used_s - used_p}

    # Special Leave
    links = state.get("special_leave_links") or {}
    sl_sent = [u for u in sent if u["type"] == "special"]
    sl_pend = [u for u in pend if u["type"] == "special"]
    bl = _baseline(state, "special", year)
    if bl and "conf_at_set" in bl:
        new_cred = [c for c in sl_credits(year, config) if c["ph"] > bl["as_of"]]
        earned = sum(1.0 for c in new_cred if c["expiry"] >= today)
        conf_now = sum(u["days"] for u in sl_sent)
        pend_now = sum(u["days"] for u in sl_pend)
        b_c, b_p, d_p = _snapshot_balance(bl, conf_now, pend_now)
        result["special"] = {
            "baseline": bl, "credits": new_cred, "unmatched": [],
            "expiring": [c for c in new_cred
                         if today <= c["expiry"] <= today + timedelta(EXPIRY_WARN_DAYS)],
            "expired": [],
            "used_confirmed": conf_now, "used_pending": max(d_p, 0.0),
            "balance_confirmed": b_c + earned, "balance_projected": b_p + earned}
    elif bl:
        new_cred = [c for c in sl_credits(year, config) if c["ph"] > bl["as_of"]]
        used_s = sum(u["days"] for u in sl_sent if u["date"] > bl["as_of"])
        used_p = sum(u["days"] for u in sl_pend if u["date"] > bl["as_of"])
        earned = sum(1.0 for c in new_cred if c["expiry"] >= today)
        result["special"] = {
            "baseline": bl, "credits": new_cred, "unmatched": [],
            "expiring": [c for c in new_cred
                         if today <= c["expiry"] <= today + timedelta(EXPIRY_WARN_DAYS)],
            "expired": [],
            "used_confirmed": used_s, "used_pending": used_p,
            "balance_confirmed": bl["value"] + earned - used_s,
            "balance_projected": bl["value"] + earned - used_s - used_p}
    else:
        conf = sl_credits(year, config)
        unm_c = _allocate_sl(conf, sl_sent, links)
        proj = sl_credits(year, config)
        unm_p = _allocate_sl(proj, sl_sent + sl_pend, links)
        live = lambda cs: [c for c in cs if c["expiry"] >= today and c["remaining"] > 1e-9]
        result["special"] = {
            "baseline": None, "credits": proj,
            "unmatched": sorted(set(unm_p) | set(unm_c)),
            "expiring": [c for c in live(proj)
                         if c["expiry"] <= today + timedelta(EXPIRY_WARN_DAYS)],
            "expired": [c for c in proj if c["expiry"] < today
                        and c["remaining"] > 1e-9 and c["ph"].year == year],
            "used_confirmed": sum(u["days"] for u in sl_sent),
            "used_pending": sum(u["days"] for u in sl_pend),
            "balance_confirmed": sum(c["remaining"] for c in live(conf)),
            "balance_projected": sum(c["remaining"] for c in live(proj))}
    return result


# ---------------------------------------------------------------------
# Hiển thị
# ---------------------------------------------------------------------
def _line(kind: str, r: dict) -> list[str]:
    x = r[kind]
    total = f" / {_num(x['entitled'])}" if kind != "special" else ""
    lines = [f"• {LABEL[kind]}: còn {_num(x['balance_confirmed'])}{total} ngày"]
    if x["used_pending"] > 1e-9:
        lines.append(f"    + {_num(x['used_pending'])} ngày tuần này CHƯA gửi "
                     f"→ sau khi gửi còn {_num(x['balance_projected'])}")
    if x["baseline"]:
        b = x["baseline"]
        lines.append(f"    (theo số dư nhập tay /updateleave ngày {b['as_of']:%d/%m/%Y}: "
                     f"{_num(b['value'])} ngày — mọi thay đổi sau đó, kể cả sửa "
                     "ngày cũ, đều được trừ/cộng)")
    if x["balance_projected"] < -1e-9:
        lines.append("    ⚠️ ÂM — đã nghỉ quá số ngày được phép")
    return lines


def format_balance(r: dict) -> str:
    lines = [f"🏖️ NGÀY PHÉP NĂM {r['year']} (tính tới {r['today']:%d/%m/%Y})",
             "━━━━━━━━━━━━━━━━━━"]
    lines += _line("annual", r) + _line("sick", r) + _line("special", r)
    sp = r["special"]
    live = [c for c in sp["credits"] if c["expiry"] >= r["today"]
            and c["remaining"] > 1e-9]
    for c in live:
        left = (c["expiry"] - r["today"]).days
        lines.append(f"    ◦ bù lễ {c['name']} ({_EN[c['ph'].weekday()]} "
                     f"{_dm(c['ph'])}) — dùng trước {_dm(c['expiry'])} "
                     f"(còn {left} ngày)")
    for c in sp["expiring"]:
        lines.append(f"⏰ SẮP HẾT HẠN: ngày bù lễ {c['name']} hết hạn "
                     f"{c['expiry']:%d/%m} — nhớ xin nghỉ trước ngày đó!")
    for c in sp["expired"]:
        lines.append(f"    ✗ đã MẤT ngày bù lễ {c['name']} (hết hạn "
                     f"{_dm(c['expiry'])}, chưa dùng)")
    for d in sp["unmatched"]:
        lines.append(f"⚠️ Special Leave ngày {d:%d/%m} không khớp lễ thứ 7 "
                     "nào còn hạn — kiểm tra lại (hoặc /updateleave).")
    for m in r.get("excel_errors", []):
        lines.append(f"⚠️ Không đọc được file Excel tháng {m} — ngày nghỉ tháng "
                     "đó CHƯA được tính. Kiểm tra file trong output\\.")
    lines += ["━━━━━━━━━━━━━━━━━━",
              f"Số ngày/năm: Annual {_num(r['annual']['entitled'])}, Sick "
              f"{_num(r['sick']['entitled'])} (theo {r['entitlement_source']}; "
              "reset 1/1 mỗi năm)",
              "Nguồn: file Excel đã gửi sếp + parsed_days tuần này.",
              "Chi tiết từng ngày: /leavelog   •   Sai số: /updateleave"]
    return "\n".join(lines)


def short_summary(config, state: dict = None) -> str:
    """1-2 dòng gắn sau khi gửi / gởi lại mail timesheet."""
    r = compute_balance(config, state)
    s = (f"🏖️ Phép còn: Annual {_num(r['annual']['balance_projected'])}/"
         f"{_num(r['annual']['entitled'])} · Sick "
         f"{_num(r['sick']['balance_projected'])}/{_num(r['sick']['entitled'])}"
         f" · Special {_num(r['special']['balance_projected'])}")
    for c in r["special"]["expiring"]:
        s += f"\n⏰ Ngày bù lễ {c['name']} hết hạn {c['expiry']:%d/%m} — nhớ dùng!"
    return s


def compose_hint(config) -> str:
    """Dòng số dư hiện trong preview email xin nghỉ (không bao giờ làm hỏng
    luồng soạn email — lỗi thì trả chuỗi rỗng)."""
    try:
        r = compute_balance(config)
    except Exception as e:  # noqa: BLE001
        log.warning("compose_hint lỗi (%s) — bỏ qua dòng số dư.", e)
        return ""
    al, sk, sp = (r[k]["balance_projected"] for k in ("annual", "sick", "special"))
    s = (f"🏖️ Số dư hiện tại: Annual còn {_num(al)}/"
         f"{_num(r['annual']['entitled'])} · Sick còn {_num(sk)}/"
         f"{_num(r['sick']['entitled'])} · Special còn {_num(sp)}")
    if al <= 0:
        s += "\n⚠️ Đã HẾT phép năm — xin nghỉ thêm sẽ vượt số ngày được phép."
    elif al < 2:
        s += f"\n⚠️ Phép năm chỉ còn {_num(al)} ngày — kiểm tra số ngày xin nghỉ."
    for c in r["special"]["expiring"]:
        s += (f"\n⏰ Còn ngày bù lễ {c['name']} hết hạn {c['expiry']:%d/%m} — "
              "có thể xin Special Leave thay vì Annual Leave.")
    return s


def format_log(r: dict) -> str:
    lines = [f"📒 LỊCH SỬ NGÀY NGHỈ NĂM {r['year']}", "━━━━━━━━━━━━━━━━━━"]
    for kind in ("annual", "sick", "special"):
        items = [u for u in r["log"] if u["type"] == kind]
        tot = sum(u["days"] for u in items)
        lines.append(f"\n{LABEL[kind]} — tổng {_num(tot)} ngày:")
        if not items:
            lines.append("  (chưa có)")
        for u in items:
            tag = "✅ đã gửi" if u["sent"] else "🕓 chưa gửi"
            lines.append(f"  {_EN[u['date'].weekday()]} {u['date']:%d/%m} — "
                         f"{_num(u['days'])} ngày  {tag}")
    lines += ["━━━━━━━━━━━━━━━━━━",
              "Chỉ gồm ngày có trong file Excel/parsed_days. Tháng trước khi "
              "dùng bot không có dữ liệu → dùng /updateleave đặt mốc."]
    return "\n".join(lines)


# ---------------------------------------------------------------------
# /updateleave
# ---------------------------------------------------------------------
_KEYS = {"al": "annual", "annual": "annual", "phép": "annual", "phep": "annual",
         "sick": "sick", "bệnh": "sick", "benh": "sick", "mc": "sick",
         "sl": "special", "special": "special", "bù": "special", "bu": "special"}
_MAX = {"annual": 60, "sick": 60, "special": 20}


def parse_update(text: str):
    """'AL 10 sick 14 SL 0' / 'al=10, sl=0' → ({'annual':10,...}, lỗi[]).
    'reset' → ({'reset': True}, [])."""
    import re
    low = text.strip().lower()
    if low in ("reset", "xóa mốc", "xoa moc"):
        return {"reset": True}, []
    found, errs = {}, []
    for key, num in re.findall(r"([a-zà-ỹ]+)\s*[:=]?\s*(-?\d+(?:[.,]\d+)?)", low):
        kind = _KEYS.get(key)
        if not kind:
            errs.append(f"Không hiểu loại phép '{key}' (dùng AL / SICK / SL).")
            continue
        v = float(num.replace(",", "."))
        if v < 0 or v > _MAX[kind] or abs(v * 2 - round(v * 2)) > 1e-9:
            errs.append(f"{LABEL[kind]}: {num} không hợp lệ (0–{_MAX[kind]}, "
                        "bước 0,5).")
            continue
        found[kind] = v
    if not found and not errs:
        errs.append("Không thấy số nào. Ví dụ: AL 10 SICK 14 SL 0")
    return found, errs


def apply_update(state: dict, values: dict, today: date = None,
                 config=None) -> None:
    """Lưu mốc. Có config → mốc kiểu MỚI: chụp lại tổng ngày đã dùng lúc đặt
    (conf_at_set / pend_at_set) để sau này sửa ngày CŨ vẫn trừ/cộng đúng.
    (Trước 24-Sep: chỉ trừ ngày SAU ngày đặt mốc → sửa 10/9 thành nghỉ bù sau
    khi đặt mốc 25/9 KHÔNG bị trừ.)"""
    today = today or date.today()
    if values.get("reset"):
        state["leave_baseline"] = {}
        return
    bl = dict(state.get("leave_baseline") or {})
    totals = _usage_totals(config, state, today.year) if config is not None else {}
    for kind, v in values.items():
        bl[kind] = {"value": v, "as_of": today.isoformat()}
        if kind in totals:
            bl[kind]["conf_at_set"], bl[kind]["pend_at_set"] = totals[kind]
    state["leave_baseline"] = bl
