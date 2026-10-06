# 🤖 BOT TIMESHEET QUA TELEGRAM — HƯỚNG DẪN ĐẦY ĐỦ

Mỗi ngày bạn **nhắn tin cho bot** trên Telegram kể mình làm gì (bằng tiếng Việt, như nhắn cho đồng nghiệp).
Bot tự điền vào bảng timesheet. **Tối thứ 6**, bot soạn sẵn file Excel + email, cho bạn **xem trước**,
bạn nhắn `ok` thì bot mới gửi cho sếp.

> 📌 Cứ làm lần lượt từng bước, đừng bỏ bước nào.

### 💡 Về dự án này

- **Mục đích:** bớt việc điền timesheet hằng tuần — mỗi ngày nhắn vài chữ; **cuối tuần bot tự tổng hợp** nội dung, **soạn file Excel đúng mẫu**, **soạn email** và **GỬI MAIL chính xác cho sếp** (kèm file Excel) — bạn chỉ việc xem trước rồi nhắn `ok`.
- **Ngày nghỉ & ngày lễ tự điền vào Excel:** nhắn *"nghỉ phép / nghỉ bệnh / nghỉ bù"* → bot ghi đúng loại nghỉ vào file Excel; ngày lễ Singapore bot **tự điền** (lễ rơi Chủ nhật → tự nghỉ bù thứ 2).
- **Chọn mail gửi:** mặc định **mail công ty**; đổi sang **Gmail cá nhân** bằng `/personalmailon` (đổi lại: `/personalmailoff`) — áp dụng cho mọi email bot gửi.
- **Gửi email cho sếp bất kỳ nội dung gì** (xin nghỉ, báo việc…): `/composemail` → bạn nói tiếng Việt, **AI viết email tiếng Anh ngắn gọn, chuẩn chỉnh** → xem trước → `ok` là gửi. Muốn tự gõ: `/composemanual`.
- **Quản lý ngày phép:** 3 loại — **Annual Leave** (17 ngày/năm), **Sick Leave** (14 ngày/năm), **Special Leave** (nghỉ bù: +1 ngày cho mỗi lễ rơi thứ 7, dùng trong **3 tháng**). Số dư **tự trừ khi file Excel gửi sếp có ngày nghỉ** (số "dự kiến" tính cả ngày đã nhắn nhưng chưa gửi). Có thể **sửa tay** số dư (`/updateleave`), **xem danh sách từng ngày đã nghỉ** (`/leavelog`), và bot **tự nhắc khi ngày nghỉ bù sắp hết hạn** 3 tháng kể từ ngày lễ (chi tiết mục 8).
- **Vì sao dùng bot Telegram, không làm app Android / iOS?** Không phải cài app riêng, không qua App Store / Google Play, không tốn phí phát hành; Telegram có sẵn trên điện thoại **lẫn** máy tính, có thông báo tức thì, nhắn tin là xong. Bot chỉ trả lời **đúng tài khoản của bạn** (chat_id), người khác nhắn vào bị từ chối.
- **Vì sao chọn Python?** Miễn phí, chạy được **cả Windows lẫn Mac**, có sẵn thư viện tốt cho mọi việc bot cần (Telegram, Excel, email, AI, lịch lễ), code dễ đọc dễ sửa.
- **So với dùng AI trong Microsoft 365 bản trả phí (Copilot):** Copilot giúp soạn / sửa trong Excel, nhưng bạn vẫn phải tự mở file và ra lệnh mỗi lần, và cần license trả phí. Bot này **miễn phí** (dùng gói AI miễn phí của Google), chạy **trên máy bạn** (dữ liệu nằm ở máy bạn), **tự làm trọn quy trình**: nhắc thứ 6, kiểm tra đủ 8h / 40h và luật từng loại task (cột D / E / F), tự điền ngày lễ Singapore, đếm ngày phép, soạn + gửi email kèm file Excel — chỉ cần nhắn tin từ điện thoại. AI lỗi / hết lượt thì bot vẫn chạy bằng luật dự phòng.
- **Tác giả:** bot do **Steve Nguyen** phát triển (*vibe code* cùng **Claude** — mô hình **Opus 5.5** và **Fable 5**) để việc điền timesheet tiện lợi hơn.
- **Email & file Excel "sạch" như tự làm tay:** email bot gửi đi chỉ có các dòng đầu thư bình thường (From / To / Cc / Bcc / Subject) — **không mang nhãn "agent-initiated"**, không có dấu hiệu "gửi tự động" hay "tạo bởi AI / bot". File Excel (xem trước, bản gửi sếp, file tháng) có **tác giả = tên bạn** (lấy từ `"employee_name"` trong `settings.json`), ứng dụng ghi **Microsoft Excel** — không ghi tên bot, AI hay thư viện lập trình.

---

## 📑 MỤC LỤC

1. [Bot làm được gì](#1-bot-làm-được-gì)
2. [Cần chuẩn bị gì](#2-cần-chuẩn-bị-gì)
3. [Cài đặt từng bước](#3-cài-đặt-từng-bước) (làm 1 lần, khoảng 30–45 phút) — **Windows và Mac**
3b. [Lịch chạy tự động (Task Scheduler / launchd)](#3b-lịch-chạy-tự-động)
3c. [Các file khởi chạy `.vbs` / `.bat` / `.command` là gì — đặt ở đâu](#3c-các-file-khởi-chạy-là-gì)
3d. [Khởi động lại bot](#3d-khởi-động-lại-bot)
3e. [Cơ chế vận hành: 2 chương trình — bot & việc chốt tuần](#3e-cơ-chế-vận-hành-2-chương-trình)
4. [Ghi timesheet hằng ngày](#4-ghi-timesheet-hằng-ngày) ⭐ quan trọng nhất
5. [Tối thứ 6 — gửi timesheet cho sếp](#5-tối-thứ-6--gửi-timesheet-cho-sếp)
6. [Sửa timesheet đã gửi + gửi lại](#6-sửa-timesheet-đã-gửi--gửi-lại)
7. [Email cho sếp (xin nghỉ...) + chọn mail gửi](#7-email-cho-sếp-xin-nghỉ--chọn-mail-gửi)
8. [Ngày phép](#8-ngày-phép)
9. [Khi AI bị lỗi mạng](#9-khi-ai-bị-lỗi-mạng)
9b. [Bot gọi AI thế nào — model, hết lượt, lỗi thường gặp](#9b-bot-gọi-ai-thế-nào)
10. [Dữ liệu, backup và các lệnh xóa](#10-dữ-liệu-backup-và-các-lệnh-xóa)
11. [Bảng TẤT CẢ lệnh](#11-bảng-tất-cả-lệnh)
12. [Sự cố thường gặp](#12-sự-cố-thường-gặp)
13. [Bảo mật — điều tuyệt đối không làm](#13-bảo-mật--điều-tuyệt-đối-không-làm)
14. [Cập nhật phiên bản mới](#14-cập-nhật-phiên-bản-mới)
15. [Bot có nặng máy không? — kết quả đo thực tế](#15-bot-có-nặng-máy-không)

---

## 1. Bot làm được gì

| Việc | Bot làm |
|---|---|
| Ghi việc hằng ngày | Bạn nhắn *"hôm nay DFU pacsdfum-4799 part b, inc2495"* → bot hiểu, điền đúng 3 cột **D (Project) / E (Task) / F (Description)** |
| Nhiều ngày 1 lần | *"thứ 2 tới thứ 4 tuần này nghỉ phép"*, *"nguyên tuần này giống thứ 6 tuần trước"* |
| Ngày lễ Singapore | Tự lấy lịch lễ của MOM, **tự điền** Public Holiday. Lễ rơi Chủ nhật → tự nghỉ bù thứ 2 |
| Tối thứ 6 | Tự soạn Excel + email, **cho xem trước**, chờ bạn `ok` mới gửi |
| Sửa tuần đã gửi | `/edittimesheet` → sửa → `/resend` gửi lại sếp |
| Email xin nghỉ | `/composemail` → bạn nói tiếng Việt, AI viết email tiếng Anh |
| Ngày phép | Tự đếm Annual / Sick / Special Leave còn lại |
| An toàn | **Mọi thao tác ghi / sửa / xóa / gửi đều hiện XEM TRƯỚC → bạn nhắn `ok` mới làm**, nhắn `hủy` để thôi |

**Lịch chạy mặc định:**
- 🕓 **16:00 hằng ngày**: máy tính tự bật bot (bot chạy tới **23:59** rồi tự tắt).
- 🕔 **Thứ 6, 17:00**: máy tính tự chạy việc chốt timesheet, bot nhắn bản nháp cho bạn duyệt.

> ⚠️ Bot chạy **trên máy tính của bạn** (Windows hoặc Mac). Máy phải **bật** (và đăng nhập) thì bot mới trả lời được.
> Lịch tự động: Windows dùng **Task Scheduler**, Mac dùng **launchd** — bộ cài tạo sẵn cho bạn (mục 3b).

---

## 2. Cần chuẩn bị gì

- Máy tính **Windows 10/11** hoặc **Mac (macOS)**, có Internet.
- Điện thoại (hoặc máy tính) có **Telegram**.
- Tài khoản **Google** (để lấy khóa AI miễn phí).
- **Mật khẩu email công ty** của bạn (để bot gửi mail bằng mail công ty).
- Hỏi người chia sẻ bot cho bạn: **địa chỉ server mail công ty** (dạng `mail.tencongty.com`).

---

## 3. Cài đặt từng bước

### Bước 1 — Cài Python

1. Vào https://www.python.org/downloads/ → bấm nút vàng **Download Python 3.x**.
2. Mở file vừa tải. ⚠️ **QUAN TRỌNG:** ở màn hình đầu tiên, **tick vào ô `Add python.exe to PATH`** (ở dưới cùng).
3. Bấm **Install Now**, chờ xong, bấm **Close**.
4. Kiểm tra: bấm phím **Windows**, gõ `cmd`, Enter. Trong cửa sổ đen, gõ:
   ```
   python --version
   ```
   Hiện `Python 3.10...` (hoặc số lớn hơn) là được. Nếu báo lỗi → cài lại, nhớ tick ô PATH.

**🍎 Trên Mac:**
1. Vào https://www.python.org/downloads/macos/ → tải bản **macOS 64-bit universal2 installer** mới nhất → mở file `.pkg` → Continue… → Install.
2. Kiểm tra: mở **Terminal** (Cmd + Space → gõ `Terminal` → Enter), gõ:
   ```
   python3 --version
   ```
   Hiện `Python 3.10...` trở lên là được. (Trên Mac luôn gõ **`python3`**, không phải `python`.)

### Bước 2 — Tải code về máy

1. Mở link kho GitHub của bot (người chia sẻ gửi cho bạn). Kho để **công khai (public)** → **không cần tài khoản GitHub, không cần đăng nhập**.
2. Bấm nút xanh **`<> Code`** → **Download ZIP**.
3. Giải nén file ZIP ra một thư mục tạm, ví dụ `C:\taive\timesheet-bot`.
   (Đây **chỉ là thư mục tải về**, không phải nơi bot chạy.)

Chi tiết từng bước tải (kho public):
- Trên trang kho, bấm nút **màu xanh lá `<> Code`** (phía trên danh sách file, bên phải) → trong khung hiện ra, bấm **Download ZIP** (dòng cuối).
- Trình duyệt tải về file **`timesheet-bot-main.zip`** (tên có thể khác chút) vào thư mục **Downloads**.
- 🪟 Windows: chuột phải file ZIP → **Extract All…** → chọn thư mục (vd `C:\taive`) → **Extract**. 🍎 Mac: nhấp đúp file ZIP là tự giải nén.
- Mở thư mục vừa giải nén: phải thấy **`CAI_DAT.bat`** (🍎 `cai_dat_mac.sh`) nằm **cạnh thư mục `src`** — đúng cấu trúc thì sang Bước 3.
- Có bản cập nhật mới → tải lại ZIP y như trên (xem mục 14).

### Bước 3 — Chạy file cài đặt

1. Vào thư mục vừa giải nén, **nhấp đúp** file **`CAI_DAT.bat`**.
2. Hỏi thư mục cài đặt → cứ **Enter** để dùng mặc định `C:\timesheet` (hoặc gõ ổ khác, vd `D:\timesheet`).
3. Bot sẽ tự: tạo thư mục, chép đủ **28 file**, cài thư viện (cần Internet, 1–3 phút).
4. Hỏi *"Tao lich tu dong ngay bay gio [Y,N]?"* → bấm **Y** (bot sẽ tự bật lúc 16:00 và tự chốt thứ 6 lúc 17:00).
5. Cuối cùng 2 file **Notepad** tự mở: `secrets.env` và `settings.json` → làm tiếp Bước 4–10 để điền.

#### 🔎 `CAI_DAT.bat` làm những gì? (đọc để hiểu, không cần làm gì thêm)

Bộ cài chạy **1 lần, lúc bạn nhấp đúp**. Nó **không bật bot ngay** — nó dọn chỗ, chép file và **đăng ký lịch** với Windows; từ đó **Windows** tự bật bot đúng giờ mỗi ngày.

| # | Việc | Để làm gì | Có tác dụng lúc nào |
|---|---|---|---|
| 0 | **Kiểm tra an toàn** trước khi làm gì: thư mục đích đã có bot (có `config\secrets.env`) → **dừng**; trùng thư mục tải về → dừng; chưa có Python → dừng | Không bao giờ ghi đè bot / dữ liệu đang có | Ngay khi chạy |
| 1 | Tạo 6 thư mục `src`, `config`, `template`, `data`, `output`, `backup` | Chỗ chứa chương trình, cấu hình, dữ liệu | Ngay |
| 2 | Chép **28 file .py**, file Excel mẫu, `start_bot.vbs`, `run_weekly.vbs`, `restart_bot.bat`, `README.md`, `requirements.txt`. Tạo `settings.json` + `secrets.env` từ **file mẫu** — **chỉ khi chưa có** (không đè file bạn đã điền). Đếm lại đủ 28 file .py | Có đủ chương trình + 2 file cấu hình để bạn điền | Ngay |
| 3 | Cài thư viện Python theo `requirements.txt` (cần Internet) | Bot cần các thư viện này để chạy (Telegram, Excel, AI, email...) | Ngay (1–3 phút) |
| 4 | **Hỏi Y/N** → nếu **Y**: đăng ký **2 lịch** vào **Task Scheduler** của Windows (chi tiết bên dưới) | Bot tự chạy mà bạn không phải nhớ | Từ **16:00 hôm nay** trở đi |
| 5 | Mở `secrets.env` + `settings.json` bằng Notepad | Để bạn điền ngay (Bước 4–9) | Ngay |

**2 lịch được đăng ký ở bước 4 — cơ chế:**

| Lịch (tên trong Task Scheduler) | Khi nào | Windows chạy gì | Kết quả |
|---|---|---|---|
| **Timesheet Bot** | **16:00 mỗi ngày** | `start_bot.vbs` → mở `bot.py` **chạy ẩn** (không có cửa sổ) | Bot bắt đầu nghe tin nhắn Telegram; **tự tắt lúc 23:59** |
| **Timesheet Weekly** | **Thứ 6, 17:00** | `run_weekly.vbs` → chạy `weekly_run.py` 1 lần rồi thoát | Soạn bản nháp tuần → nhắn Telegram cho bạn duyệt (mục 5). **Chưa gửi sếp** tới khi bạn `ok` |

Kèm 2 tùy chọn cho **laptop** (bộ cài tự bật):
- **Chạy cả khi dùng pin** — mặc định Windows bỏ qua lịch nếu laptop không cắm sạc.
- **Chạy bù khi bật máy** — lúc 16:00 / 17:00 máy đang tắt → bật máy lên Windows chạy bù ngay.

Ghi chú:
- Lịch chạy **dưới tài khoản Windows của bạn**, quyền thường (không cần Admin); phải **đăng nhập Windows** thì lịch mới chạy.
- Bấm **N** ở bước 4 → không có lịch; bạn tự bật bot bằng `start_bot.vbs` mỗi lần, hoặc tạo lịch tay sau (mục 3b).
- Bộ cài **chỉ dùng để cài lần đầu**. Chạy lại vào thư mục đã có bot → nó tự dừng. Cập nhật bản mới → xem mục 14.
- Bộ cài **không** gửi gì ra ngoài, **không** đụng file nào khác trên máy ngoài thư mục cài đặt và 2 lịch trên.

**🍎 Mac — `cai_dat_mac.sh` làm y như vậy**, khác 3 điểm: cài thư viện vào **môi trường riêng** `~/timesheet/.venv` (Mac đời mới không cho cài thẳng vào Python hệ thống); lịch dùng **launchd** thay Task Scheduler (2 file `com.timesheet.bot.plist` 16:00 hằng ngày và `com.timesheet.weekly.plist` thứ 6 17:00, trong `~/Library/LaunchAgents/`); Mac đang ngủ lúc tới giờ thì **tự chạy bù khi thức dậy** (tắt hẳn thì không).

**🍎 Trên Mac** (thay cho `CAI_DAT.bat`):
1. Mở **Terminal**, gõ `bash ` (chữ bash + **1 dấu cách**), rồi **kéo thả** file `cai_dat_mac.sh` từ Finder vào cửa sổ Terminal → **Enter**.
2. Hỏi thư mục cài → **Enter** để dùng mặc định `~/timesheet` (tức `/Users/<tên-bạn>/timesheet`).
3. Bộ cài tự tạo thư mục, chép đủ **28 file**, tạo môi trường Python riêng (`.venv`) và cài thư viện.
4. Hỏi *"Tao lich tu dong ngay bay gio? [Y/N]"* → gõ **Y** → Enter (tạo lịch launchd, xem mục 3b).
5. 2 file tự mở bằng **TextEdit**. ⚠️ **Trước khi gõ**: menu **Edit → Substitutions** → **bỏ tick `Smart Quotes`** (nếu không, TextEdit tự đổi dấu `"` thành `“ ”` làm hỏng file `settings.json`).

Sau khi cài, thư mục của bạn trông như sau:
```
C:\timesheet\
├── src\              ← 28 file chương trình (.py) — KHÔNG sửa
├── config\
│   ├── secrets.env   ← mật khẩu, token (BÍ MẬT)
│   └── settings.json ← tên bạn, tên sếp, email...
├── template\         ← file Excel mẫu
├── data\             ← dữ liệu timesheet (bot tự tạo)
├── output\           ← file Excel theo tháng (bot tự tạo)
├── backup\           ← bản sao Excel trước khi sửa
├── start_bot.vbs     ← nhấp đúp để BẬT bot (mục 3c)
├── run_weekly.vbs    ← chạy việc chốt thứ 6 bằng tay (mục 3c)
├── restart_bot.bat   ← TẮT rồi BẬT LẠI bot (mục 3d)
└── README.md         ← tài liệu này
```
**🍎 Mac:** thư mục là `~/timesheet`, có thêm `.venv/` (thư viện Python riêng — đừng xóa); thay 2 file `.vbs` là **`start_bot.command`**, **`run_weekly.command`**; thay `restart_bot.bat` là **`restart_bot.command`**; và có thêm **`tao_lich_mac.sh`** (tạo lịch tự động).

### Bước 4 — Tạo bot Telegram của riêng bạn (lấy TOKEN)

1. Mở Telegram, tìm **@BotFather** (có dấu tick xanh), bấm **Start**.
2. Gõ `/newbot`.
3. Đặt **tên hiển thị**, ví dụ `Timesheet cua Minh`.
4. Đặt **username** (phải kết thúc bằng `bot`), ví dụ `timesheet_minh_bot`.
5. BotFather trả về một dòng dài dạng `1234567890:AAH....` → đó là **TOKEN**. Copy lại.

> ⚠️ Ai có TOKEN là điều khiển được bot của bạn. **Không gửi cho ai, không chụp màn hình.**

### Bước 5 — Lấy chat_id của bạn

1. Trên Telegram, tìm **@userinfobot**, bấm **Start**.
2. Bot trả lời có dòng `Id: 123456789` → dãy số đó là **chat_id** của bạn.

(Bot timesheet chỉ trả lời đúng chat_id này — người khác nhắn vào bot của bạn sẽ bị từ chối.)

### Bước 6 — Lấy khóa AI Gemini (miễn phí)

1. Vào https://aistudio.google.com/apikey, đăng nhập tài khoản Google.
2. Bấm **Create API key** → copy dòng bắt đầu bằng `AIza...` (hoặc `AQ.`).

> AI dùng để **hiểu câu tiếng Việt** bạn nhắn. Gói miễn phí đủ dùng cho 1 người. Khi AI lỗi, bot vẫn chạy bằng luật dự phòng (xem mục 9).

### Bước 7 — Mật khẩu ứng dụng Gmail (TÙY CHỌN)

**Không bắt buộc.** Chỉ cần nếu bạn muốn **gửi dự phòng bằng Gmail cá nhân** khi mail công ty trục trặc (lệnh `/personalmailon`). **Không dùng Gmail** → bỏ qua bước này, ở Bước 8 **để nguyên `chua_co`** cho 2 dòng `GMAIL_…`: bot vẫn khởi động bình thường và **luôn gửi bằng mail công ty**, không báo lỗi gì.

1. Bật **xác minh 2 bước** cho Gmail: https://myaccount.google.com/security
2. Vào https://myaccount.google.com/apppasswords → đặt tên `timesheet` → **Create**.
3. Google hiện **16 ký tự** (dạng `abcd efgh ijkl mnop`) → copy, **bỏ hết khoảng trắng**.


### Bước 8 — Điền file `secrets.env` (BÍ MẬT)

Trong Notepad đang mở `C:\timesheet\config\secrets.env`, thay chữ `chua_co` bằng giá trị thật:

| Dòng | Điền gì | Lấy ở đâu |
|---|---|---|
| `TELEGRAM_BOT_TOKEN=` | token dạng `1234567890:AAH...` | Bước 4 |
| `TELEGRAM_ALLOWED_CHAT_ID=` | dãy số chat_id | Bước 5 |
| `GMAIL_ADDRESS=` | Gmail cá nhân của bạn | — |
| `GMAIL_APP_PASSWORD=` | 16 ký tự, **không khoảng trắng** | Bước 7 |

> 2 dòng `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` là **tùy chọn** — không dùng Gmail thì **để nguyên `chua_co`**.
| `GEMINI_API_KEY=` | `AIza...` | Bước 6 |
| `COMPANY_MAIL_PASSWORD=` | mật khẩu email công ty | bạn biết |

⚠️ **Không** để khoảng trắng quanh dấu `=`, **không** thêm dấu nháy. Ví dụ đúng:
```
TELEGRAM_ALLOWED_CHAT_ID=123456789
```
Lưu lại (**Ctrl + S**).

### Bước 9 — Điền file `settings.json` (thông tin của bạn)

Trong Notepad đang mở `C:\timesheet\config\settings.json`, **chỉ sửa phần chữ trong dấu nháy** của các dòng sau (giữ nguyên dấu `"` và dấu `,`):

| Khóa | Ý nghĩa | Ví dụ |
|---|---|---|
| `"employee_name"` | Họ tên đầy đủ (hiện trong cột B Excel) | `"Tran Van Minh"` |
| `"signature_name"` | Tên ký cuối email | `"Minh"` |
| `"boss_name"` | Tên sếp (email mở đầu "Hi ...") | `"Lan"` |
| `"boss_email"` | Email **người nhận timesheet**. ⚠️ **Lúc đầu để email CỦA BẠN** để chạy thử | `"minh.rieng@gmail.com"` |
| `"bcc_email"` | Email công ty của bạn | `"minh.tran@congty.com"` |
| `"company_email"` | Email công ty của bạn (gửi mail bằng địa chỉ này) | `"minh.tran@congty.com"` |
| `"company_display_name"` | Tên hiện ở ô "Từ" khi sếp nhận mail | `"Minh Tran"` |
| `"company_mail_host"` | Server mail công ty (hỏi người chia sẻ) | `"mail.congty.com"` |
| `"bcc_when_company"` | Gửi bằng mail công ty thì gửi **bản sao ẩn** tới đâu (vd Gmail riêng). Để `""` nếu không cần | `"minh.rieng@gmail.com"` |
| `"file_name_pattern"` | Tên file Excel gửi sếp → **chỉ đổi chữ `TenBan`** thành tên bạn | `"LiveReport {file_month}_{file_year} -Minh ({send_day} {send_month}).xlsx"` |

Các dòng khác **để nguyên**. Muốn đổi số ngày phép/năm: thêm (hoặc sửa) 2 dòng
`"annual_leave_per_year": 17,` và `"sick_leave_per_year": 14,` (xem mục 8).

⚠️ File này phải **đúng định dạng** (dấu nháy, dấu phẩy). Sai 1 dấu là bot không chạy — bước 10 sẽ báo cho bạn biết.

Lưu lại (**Ctrl + S**).

#### 📄 Tên của bạn trong file Excel — KHÔNG cần sửa file mẫu

File Excel mẫu (`template\master_template.xlsx`) được để **trống ô tên** (ô **A4**, ngay dưới tiêu đề *"Employee Name"* ở ô A3). Bạn **không cần mở file mẫu để điền**: mỗi lần tạo file Excel, **bot tự ghi** tên lấy từ dòng `"employee_name"` trong `settings.json` (Bước 9) vào:
- ô **A4** (tên đầu bảng), và
- **cột B** (*Employee Name*) của **từng dòng** công việc.

`CAI_DAT.bat` / `cai_dat_mac.sh` **không đụng** tới file Excel — tên được ghi lúc bot tạo file. Vì vậy chỉ cần **điền đúng `"employee_name"`** (viết đúng như sếp / công ty đang dùng).

**Muốn tự gõ tên vào file mẫu** (vd ghi kèm tên nhóm) — không bắt buộc:
1. Mở `C:\timesheet\template\master_template.xlsx` bằng Excel (🍎 Mac: `~/timesheet/template/master_template.xlsx`).
2. Bấm ô **A4** → gõ tên → **Ctrl + S** (lưu, giữ đúng định dạng `.xlsx`). **Đừng** sửa hay xóa các ô / dòng khác.
3. Bot sẽ **giữ nguyên** chữ bạn gõ ở A4; cột B từng dòng vẫn lấy theo `"employee_name"`.

**Đổi tên sau này:** sửa `"employee_name"` trong `settings.json` → **khởi động lại bot** (mục 3d). Cột B cập nhật ở lần ghi kế tiếp; riêng ô A4 của file Excel **tháng đang làm** (đã tạo trước đó) vẫn giữ tên cũ → mở file `output\LiveReport_YYYY-MM.xlsx` sửa tay ô A4 nếu cần.

### Bước 10 — Kiểm tra cấu hình

Mở `cmd` (phím Windows → gõ `cmd` → Enter), gõ **từng dòng**:
```
cd /d C:\timesheet\src
python config_loader.py
```
- Hiện **`CONFIG OK`** → tốt.
- Hiện **`LỖI CẤU HÌNH`** → đọc dòng lỗi (tiếng Việt), sửa đúng chỗ đó trong `secrets.env` / `settings.json`, chạy lại.

Tiếp:
```
python selfcheck.py
```
Kiểm tra đủ file, đủ thư viện. Có dòng `✗` → chụp màn hình gửi người chia sẻ.

**🍎 Mac** — mở Terminal, gõ thay cho 3 dòng trên:
```
cd ~/timesheet/src
../.venv/bin/python config_loader.py
../.venv/bin/python selfcheck.py
```
(Các lệnh `python ...` bên dưới: trên Mac gõ `../.venv/bin/python ...`.)

Kiểm tra **mail công ty**:
```
python company_mailer.py --check
python company_mailer.py --test
```
- `--check`: thử đăng nhập server mail (chưa gửi gì).
- `--test`: gửi 1 mail thử tới `bcc_when_company` (hoặc chính email công ty). Mở hộp thư xem đã nhận chưa (xem cả **Spam**).

### Bước 11 — Bật bot lần đầu

1. Nhấp đúp **`C:\timesheet\start_bot.vbs`** (không có cửa sổ nào hiện ra — bình thường).
2. Mở Telegram, tìm bot của bạn (username ở Bước 4), bấm **Start** hoặc gõ `/start`.
3. Bot trả lời bảng hướng dẫn → **XONG!** 🎉

Bot không trả lời sau 30 giây → xem mục 12 (Sự cố).

**🍎 Mac:** nhấp đúp **`~/timesheet/start_bot.command`** (một cửa sổ Terminal hiện *"Da bat bot…"*, đóng được).
Lần đầu Mac có thể chặn *"cannot be opened because it is from an unidentified developer"* → **chuột phải** file → **Open** → **Open**.

### Bước 12 — Việc cần làm ngay lần đầu

1. **Khai số ngày phép còn lại thật** (bot không biết các tháng trước khi có bot):
   ```
   /updateleave AL 10 SICK 14 SL 0
   ```
   (AL = phép năm còn 10 ngày, SICK = nghỉ bệnh còn 14, SL = nghỉ bù còn 0 — thay bằng số thật của bạn.)
2. **Chạy thử 1 tuần** với `"boss_email"` = email **của chính bạn** (bước 9). Tối thứ 6 nhận thử timesheet, mở Excel xem đúng chưa.
3. Thấy ổn → sửa `"boss_email"` thành **email sếp thật** → **khởi động lại bot** (mục 12, "Đổi settings.json").

---

## 3b. Lịch chạy tự động

Bot cần **2 lịch**:

| Lịch | Chạy lúc | Làm gì |
|---|---|---|
| **Timesheet Bot** | 16:00 hằng ngày | bật bot (bot tự tắt lúc 23:59) |
| **Timesheet Weekly** | Thứ 6, 17:00 | chốt timesheet tuần, nhắn bản nháp cho bạn duyệt |

Bộ cài (`CAI_DAT.bat` / `cai_dat_mac.sh`) **tạo sẵn** khi bạn bấm **Y**. Phần dưới để **kiểm tra** hoặc **tự tạo tay**.

### 🪟 Windows — Task Scheduler

**Kiểm tra:** phím Windows → gõ **Task Scheduler** → mở → bên trái bấm **Task Scheduler Library** → phải có **Timesheet Bot** và **Timesheet Weekly**. Cột *Last Run Result* = `(0x0)` là chạy tốt.

**Tự tạo tay** (nếu lúc cài bấm N, hoặc bị mất):
1. Trong Task Scheduler, cột phải bấm **Create Basic Task…**
2. **Name:** `Timesheet Bot` → **Next**.
3. **Trigger:** chọn **Daily** → Next → **Start:** `16:00:00`, **Recur every:** `1` days → Next.
4. **Action:** **Start a program** → Next.
5. **Program/script:** `wscript.exe`
   **Add arguments:** `"C:\timesheet\start_bot.vbs"` (có dấu nháy; đổi đường dẫn nếu cài chỗ khác) → Next → **Finish**.
6. Làm lại từ bước 1 cho task thứ 2:
   **Name** `Timesheet Weekly` · **Trigger** **Weekly** → tick **Friday**, Start `17:00:00` · **Program** `wscript.exe` · **Arguments** `"C:\timesheet\run_weekly.vbs"`.

**⭐ Bắt buộc cho LAPTOP** (làm cho **cả 2** task — bộ cài đã tự bật, tạo tay thì phải làm):
- Chuột phải task → **Properties** → tab **Conditions** → **BỎ tick** *"Start the task only if the computer is on AC power"* (không thì dùng pin là lịch **không chạy**).
- Tab **Settings** → **tick** *"Run task as soon as possible after a scheduled start is missed"* (lúc 16:00 / 17:00 máy đang tắt → bật máy lên sẽ **chạy bù**).
- Bấm **OK**.

**Thử ngay:** chuột phải **Timesheet Bot** → **Run** → nhắn `/status` cho bot.

### 🍎 Mac — launchd

launchd là "Task Scheduler" của Mac. Bộ cài tạo 2 file lịch trong `~/Library/LaunchAgents/`:
`com.timesheet.bot.plist` (16:00 hằng ngày) và `com.timesheet.weekly.plist` (thứ 6 17:00).

**Kiểm tra** (Terminal):
```
launchctl list | grep timesheet
```
Thấy 2 dòng `com.timesheet.bot` và `com.timesheet.weekly` là đã có lịch.

**Thử ngay:**
```
launchctl kickstart gui/$(id -u)/com.timesheet.bot
```
rồi nhắn `/status` cho bot.

**Tạo / tạo lại lịch** (lúc cài gõ N, hoặc lịch bị mất) — Terminal:
```
bash ~/timesheet/tao_lich_mac.sh
```
(Không chạy lại `cai_dat_mac.sh` — nó dừng lại vì thấy bot đã cài, để bảo vệ dữ liệu của bạn.)

**Tắt lịch** (khi không dùng bot nữa):
```
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.timesheet.bot.plist
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.timesheet.weekly.plist
```

**Mac đang ngủ (gập máy) lúc 16:00 / 17:00** → launchd **tự chạy bù** khi máy thức dậy. Mac **tắt hẳn** thì không chạy bù → bật bot tay bằng `start_bot.command`.

> ⚠️ Mac: bảo đảm **không tắt máy** lúc 17:00 thứ 6, hoặc tối thứ 6 tự nhấp đúp `run_weekly.command`.

---

## 3c. Các file khởi chạy là gì

Bot là chương trình **Python** (28 file `.py` trong `src\`). Để **bạn không phải gõ lệnh**, bộ cài để sẵn vài file "bấm là chạy" ở thư mục cài đặt:

| File | Máy | Làm gì | Ai chạy nó |
|---|---|---|---|
| `start_bot.vbs` | Windows | **BẬT bot** chạy nền, **không có cửa sổ** → bot nghe tin nhắn Telegram tới **23:59** rồi tự tắt | Task Scheduler lúc **16:00** mỗi ngày · hoặc bạn **nhấp đúp** |
| `run_weekly.vbs` | Windows | Chạy **việc chốt timesheet tuần** 1 lần (ẩn): soạn bản nháp → nhắn Telegram cho bạn duyệt → tự thoát. **Không gửi sếp** | Task Scheduler **thứ 6 17:00** · hoặc bạn nhấp đúp (vd quên, chạy bù) |
| `restart_bot.bat` | Windows | **Tắt đúng bot** rồi **bật lại** (mục 3d) | Bạn nhấp đúp khi cần |
| `start_bot.command` · `run_weekly.command` · `restart_bot.command` | Mac | Y hệt 3 file trên | launchd · hoặc nhấp đúp |

> Bấm `start_bot.vbs` **nhiều lần không sao** — bot tự chặn chạy trùng (chỉ 1 bot chạy).

**Mỗi file khởi chạy gọi file Python nào (chuỗi chạy):**

🪟 **Windows**
```
start_bot.vbs   → Windows Script Host (wscript.exe, có sẵn trong Windows)
                → tìm thư mục chứa chính nó → vào src\
                → chạy ẨN:  python.exe  src\bot.py        (không chờ, xong là thoát)
                → bot.py chạy tiếp tới 23:59, tự nạp các file .py khác trong src\
                  (ghi chú, Excel, email, ngày phép, AI, lịch lễ…)

run_weekly.vbs  → wscript.exe → chạy ẨN:  python.exe  src\weekly_run.py
                → weekly_run.py: soạn / kiểm tra bản nháp → nhắn Telegram
                → nếu bot đang tắt: bật lịch "Timesheet Bot" (= start_bot.vbs → bot.py)
                → weekly_run.py tự thoát (vài giây)

restart_bot.bat → cửa sổ đen (cmd) → PowerShell tìm python đang chạy  src\bot.py  → tắt
                → chờ 3 giây → gọi start_bot.vbs → bot.py chạy lại

Task Scheduler: "Timesheet Bot"    (16:00)   → wscript.exe "…\start_bot.vbs"
                "Timesheet Weekly" (T6 17:00) → wscript.exe "…\run_weekly.vbs"
```

🍎 **Mac**
```
start_bot.command   → Terminal (bash) → chạy NỀN:  .venv/bin/python  src/bot.py
run_weekly.command  → .venv/bin/python  src/weekly_run.py   (chạy xong tự thoát)
restart_bot.command → tắt đúng python đang chạy bot.py → chờ 3 giây → start_bot.command
launchd (lịch tự động) gọi THẲNG python, không qua file .command:
     com.timesheet.bot    (16:00)    → .venv/bin/python  …/src/bot.py
     com.timesheet.weekly (T6 17:00) → .venv/bin/python  …/src/weekly_run.py
```

- Chỉ **2 file Python được "khởi chạy"**: `bot.py` (bot) và `weekly_run.py` (chốt tuần). 26 file `.py` còn lại là **phần dùng chung** — 2 file kia tự nạp khi cần, bạn không chạy trực tiếp (trừ vài công cụ kiểm tra như `selfcheck.py`, `config_loader.py`).
- Trong Task Manager có thể thấy **2 dòng `python.exe`** cho 1 bot: một **tiến trình mồi** rất nhỏ (chỉ để khởi động) và **bot thật** — bình thường (xem mục 15).

**`.vbs` là gì? Khác `.exe`, `.bat` thế nào?**

| Loại file | Là gì | Mở bằng Notepad đọc được? | Khi chạy |
|---|---|---|---|
| **`.exe`** | Chương trình đã đóng gói sẵn (mã máy) | ❌ Không (toàn ký tự lạ) | Tùy chương trình |
| **`.bat`** | Danh sách lệnh cho **cửa sổ đen (cmd)** của Windows | ✅ Có | **Hiện cửa sổ đen** trong lúc chạy |
| **`.vbs`** | *VBScript* — đoạn lệnh ngắn do **Windows Script Host** (`wscript.exe`, có sẵn trong mọi máy Windows, không cần cài) chạy | ✅ Có (mỗi file chỉ ~5 dòng) | Có thể chạy **ẩn**, không cửa sổ |

Bot dùng `.vbs` để **chạy ngầm cả buổi chiều mà không có cửa sổ đen nào** trên màn hình (không lỡ tay đóng mất bot). Nếu dùng `.bat`, cửa sổ đen phải mở suốt, đóng lại là bot tắt.
`.vbs` **không tự chạy** — chỉ chạy khi bạn nhấp đúp, hoặc Task Scheduler gọi đúng giờ (mục 3b). Mở bằng Notepad (chuột phải → **Edit**) sẽ thấy nội dung chỉ là: *tìm thư mục chứa file này → vào `src` → chạy `python bot.py` ẩn*.

**⚠️ Đặt ở đâu? — PHẢI để NGUYÊN trong thư mục cài đặt**

Mỗi file tự tìm thư mục `src\` **nằm cạnh nó**. Vì vậy:
- ✅ Để nguyên tại `C:\timesheet\` (cạnh thư mục `src`).
- ❌ **Mang `run_weekly.vbs` (hay `start_bot.vbs`) ra Desktop → KHÔNG chạy** (ra Desktop thì bên cạnh không có `src\bot.py`). Task Scheduler cũng đang trỏ vào đường dẫn cũ → **lịch tự động hỏng**.
- ✅ Muốn bấm từ Desktop cho tiện → tạo **SHORTCUT** (lối tắt), file gốc vẫn nằm yên:
  chuột phải `run_weekly.vbs` → **Show more options** (Windows 11) → **Send to** → **Desktop (create shortcut)**. Nhấp đúp shortcut trên Desktop = chạy file gốc.
- 🍎 Mac: chuột phải file `.command` → **Make Alias** → kéo **alias** ra Desktop (đừng kéo file gốc).
- Muốn đổi chỗ cài cả bot → dời **cả thư mục** `timesheet` rồi tạo lại lịch (mục 3b).

---

## 3d. Khởi động lại bot

**Khi nào cần:** vừa sửa `settings.json` / `secrets.env` (bot chỉ đọc cấu hình **lúc bật**), vừa cập nhật code mới (mục 14), hoặc bot không trả lời dù máy đang bật.

**🪟 Windows — cách nhanh (khuyên dùng):** nhấp đúp **`C:\timesheet\restart_bot.bat`**
→ cửa sổ đen hiện: *"Da tat bot…"* → *"Dang bat lai bot…"* → *"Xong"* → bấm phím bất kỳ để đóng → chờ ~10 giây → nhắn `/status` cho bot.
File này **chỉ tắt đúng chương trình bot** (python đang chạy `src\bot.py`), **không đụng** chương trình Python khác trên máy.

**🪟 Windows — làm tay** (nếu không dùng file trên):
1. Mở **Task Manager** (**Ctrl + Shift + Esc**) → tab **Details**.
2. Chuột phải tiêu đề cột → **Select columns** → tick **Command line** → OK.
3. Tìm dòng `python.exe` có cột Command line chứa **`\src\bot.py`** → chọn → **End task**.
   (Đừng tắt `python.exe` khác — có thể là chương trình khác của bạn.)
4. Nhấp đúp **`start_bot.vbs`** để bật lại.

**🍎 Mac — cách nhanh:** nhấp đúp **`~/timesheet/restart_bot.command`** (một cửa sổ Terminal hiện các bước, xong thì đóng).
**🍎 Mac — làm tay:** mở **Activity Monitor** → ô tìm kiếm gõ `python` → chọn tiến trình python của bot → nút **ⓧ** → **Quit**. Rồi nhấp đúp **`start_bot.command`**.

**Chỉ muốn TẮT bot (không bật lại):** làm bước tắt ở trên (Task Manager / Activity Monitor). Bình thường **không cần** — bot tự tắt lúc 23:59 và lịch tự bật lại 16:00 hôm sau.

---

## 3e. Cơ chế vận hành: 2 chương trình

Trên máy bạn có **2 chương trình khác nhau**, chạy bởi **2 lịch khác nhau** (Windows: Task Scheduler · Mac: launchd):

- **Timesheet Weekly** chạy `weekly_run.py`: kiểm tra hoặc soạn bản nháp, **tự nhắn Telegram**, rồi **thoát**. Nó **không phải là bot** (không nghe tin nhắn của bạn). Vì vậy log **không có** dòng *"BOT TIMESHEET v2 KHỞI ĐỘNG"*, và `python.exe` bạn thấy hiện ra rồi biến mất trong Task Manager chính là nó chạy xong.
- **Timesheet Bot** chạy `bot.py`: chương trình **nghe và trả lời** tin nhắn / lệnh của bạn (`/status`, `ok`, ghi chú…). Chỉ khi chương trình này đang chạy thì bot mới trả lời. Lúc bật, log ghi *"BOT TIMESHEET v2 KHỞI ĐỘNG"*.

| | Timesheet Bot (`bot.py`) | Timesheet Weekly (`weekly_run.py`) |
|---|---|---|
| Chạy lúc | 16:00 mỗi ngày (hoặc nhấp đúp `start_bot.vbs`) | Thứ 6 17:00 (hoặc nhấp đúp `run_weekly.vbs`) |
| Chạy bao lâu | Tới **23:59** rồi tự tắt — riêng **T6 / T7 / CN**: tự tắt **1 phút sau khi gửi xong** timesheet tuần (mục 5) | Vài giây, **xong việc là thoát** |
| Làm gì | Nghe & trả lời tin nhắn, ghi timesheet, gửi mail khi bạn `ok` | Soạn bản nháp tuần / hỏi ngày còn thiếu → nhắn Telegram. **Không gửi sếp** |
| Có trả lời tin nhắn? | ✅ Có | ❌ Không |

**Tự bật bot khi cần:** tin nhắn của *Timesheet Weekly* thường cần bạn trả lời (vd `ok` để gửi sếp) — mà chỉ **bot** mới nhận được câu trả lời. Nên khi chạy xong, *Timesheet Weekly* **kiểm tra bot có đang chạy không**; nếu bot đang tắt thì **tự bật bot lên** và ghi thêm trong tin nhắn: *"🤖 (Bot đang tắt → mình đã BẬT lại, bro trả lời bình thường nhé.)"*. Bật không được thì báo *"⚠️ … nhấp đúp start_bot.vbs"* để bạn tự bật.

**Ví dụ tình huống:** tối qua bot bị tắt (vd máy ngủ / bị đóng) lúc 02:50. Sáng 09:44 bạn chạy lịch *Timesheet Weekly* → nó nhắn tin cho bạn rồi thoát, **đồng thời tự bật bot** → bạn gõ `/status` là bot trả lời. (Trước khi có tính năng tự bật, trường hợp này bot **không** trả lời cho tới khi bạn chạy lịch *Timesheet Bot* hoặc nhấp đúp `start_bot.vbs`.)

---

## 4. Ghi timesheet hằng ngày

### 4.1 Nguyên tắc chung

```
<ngày>  +  <từ khóa loại task>  +  <số ticket / mô tả>
```
- Nhắn **bình thường** cho bot (không cần lệnh).
- Bot trả lời *"MÌNH HIỂU BRO MUỐN: ..."* kèm cột **D / E / F** → đúng thì nhắn `ok`, sai thì nói lại (vd *"không phải, sửa thành nghỉ phép"*), không muốn thì `hủy`.
- Một số trường hợp đơn giản (ngày còn trống, câu rõ ràng) bot **ghi luôn** và báo *"✅ ĐÃ GHI THÀNH CÔNG"*.
- **Mã ticket tự viết HOA** và giữ đúng kiểu bạn gõ (có/không dấu gạch): `pacsdfum-4799 part b` → `PACSDFUM-4799 Part B`. Phần mô tả chữ **giữ nguyên**.
- **Không nói số giờ → bot chia đều 8 tiếng/ngày.**

Các cột trong Excel: **D** = Project Name · **E** = Task Name · **F** = Description · **G** = Hours.

### 4.2 Cách nói NGÀY

| Bạn nhắn | Bot hiểu |
|---|---|
| `hôm nay`, `hôm qua`, `mai` | ngày tương ứng |
| `thứ 3`, `thứ 3 tuần này`, `thứ 3 tuần trước` | đúng 1 ngày thứ 3 đó |
| `10/9`, `ngày 10/9` | ngày 10 tháng 9 |
| `thứ 2 tới thứ 4 tuần này`, `15/9 tới 18/9` | các ngày làm việc ở giữa |
| `nguyên tuần này`, `cả tuần trước` | T2 → T6 của tuần |
| `cả tháng này`, `hết tháng 10` | mọi ngày T2 → T6 của tháng |
| `2 ngày đầu tiên của tháng` | 2 ngày làm việc đầu tháng |
| `sáng nay`, `chiều nay` | hôm nay (nếu là nghỉ → hiểu là nửa ngày) |

> Với tuần / tháng, bot **luôn liệt kê từng ngày** cho bạn xem trước khi ghi.
> ⚠️ *"thứ 3 tuần này làm SDF"* chỉ là **1 ngày thứ 3**, không bao giờ thành cả tuần.

### 4.3 Từng loại task — TỪ KHÓA, CÚ PHÁP, VÍ DỤ

#### ▶ PRODUCTION SUPPORT (kiểm tra sự cố production)
- **Từ khóa:** `prod issue` · `prod check` · `prod fix` · `production issue` · `production issue check` · `production check` · `production support check`
- **Cột E luôn là `Issue Investigation`**, cột D = `Production Support`.
- **Cú pháp:** `<ngày> <từ khóa> cho <Ticket# số - mô tả>[, Ticket# số - mô tả]`

| Bạn nhắn | D | E | F |
|---|---|---|---|
| `hôm nay prod issue cho Ticket# 02238471 - to check client receives premium notice, Ticket# 479829 - to check policy softlock` | Production Support | Issue Investigation | Ticket# 02238471 - to check client receives premium notice, Ticket# 479829 - to check policy softlock |

⚠️ `prod fix code` / `prod issue code` là **SDF**, không phải Issue Investigation.
⚠️ Chữ `production support` đứng một mình **không** phải từ khóa (vì DFU, SDF cũng có D = Production Support).

#### ▶ DFU
- **Từ khóa:** `dfu` · `data fix` · `data patch` · `patch data` · `deploy data`
- Ticket nằm ở cột F.

| Bạn nhắn | D | E | F |
|---|---|---|---|
| `hôm nay DFU pacsdfum-4799 part b, inc2495` | Production Support | DFU | PACSDFUM-4799 Part B, INC2495 |

#### ▶ SDF
- **Từ khóa:** `sdf` · `prod fix code` · `prod issue code` · `production code fix`
- Có chữ mô tả thì ghi **`description là`**.

| Bạn nhắn | D | E | F |
|---|---|---|---|
| `hôm nay SDF description là PACSGASIA-4137 issue 1&2 (UAT support)` | Production Support | SDF | PACSGASIA-4137 issue 1&2 (UAT support) |

(Chữ nằm **trong mô tả** như "production issue", "UAT support" **không** làm đổi loại task — loại task lấy theo từ khóa ở **đầu câu**.)

#### ▶ NP (New Product)
- **Từ khóa:** `NP` · `làm NP` + việc: `code` / `UT` → Coding/UT · `assess` → Investigation/Assessment · `UAT` → UAT Support
- Mọi mã PACSNP **gom vào 1 dòng ở cột D**, cột F luôn là `New product day 2 items`.

| Bạn nhắn | D | E | F |
|---|---|---|---|
| `hôm nay làm NP assess cho pacsnp-7878, pacsnp-5890` | PACSNP-7878, PACSNP-5890 | Investigation/Assessment | New product day 2 items |
| `hôm nay code NP pacsnp-7878, pacsnp-5890` | PACSNP-7878, PACSNP-5890 | Coding/UT | New product day 2 items |

#### ▶ DỰ ÁN / WR (work request)
- **Từ khóa (mốc tên):** `dự án` · `project` · `WR`
- **Cú pháp:** `<ngày> WR <TÊN DỰ ÁN>, <việc>, mô tả <MÔ TẢ>`

| Bạn nhắn | D | E | F |
|---|---|---|---|
| `hôm nay WR PACSPOSCM-2012 AML screening, coding, mô tả GWIA AML screening for all payment except Paynow Fast (PL2702)` | PACSPOSCM-2012 AML screening | Coding/UT | GWIA AML screening for all payment except Paynow Fast (PL2702) |
| `hôm nay dự án LA & GA agent sync, UAT, mô tả PACSGASIA-4011 - Agent Sync UAT Support` | LA & GA agent sync | UAT Support | PACSGASIA-4011 - Agent Sync UAT Support |

Cách viết linh hoạt:
- **Mốc tên:** `dự án` / `project` / `WR` (tên ghi nguyên văn, có thể chứa số ticket).
- **Mốc mô tả:** `mô tả` / `description` / `desc` — có `là` hay `:` hay không đều được.
- **Việc:** `coding` / `code` / `UT` / `unit test` → Coding/UT · `UAT` → UAT Support · `assess` / `assessment` → Investigation/Assessment · **không ghi → Coding/UT**.
- Các phần ngăn nhau bằng **dấu phẩy** → tên dự án đừng có dấu phẩy (nếu có thì ngăn bằng `|`).

#### ▶ NGHỈ
- D = E = loại nghỉ, F để trống.

| Từ khóa | Loại nghỉ |
|---|---|
| `nghỉ phép` · `off` · `leave` | Annual Leave |
| `nghỉ bệnh` · `nghỉ ốm` · `bị bệnh` | Sick Leave (nhớ gửi giấy MC cho công ty) |
| `nghỉ bù` | Special Leave |
| `nghỉ lễ` | Public Holiday (thường **không cần nhắn** — bot tự điền) |

| Bạn nhắn | Kết quả |
|---|---|
| `hôm nay nghỉ phép` | Annual Leave 8h |
| `sáng nay nghỉ phép` / `hôm nay nghỉ phép nửa ngày` | Annual Leave 4h |

#### ▶ NHIỀU TASK TRONG 1 NGÀY
Ghi **số giờ từng phần**, ngăn bằng dấu phẩy:

| Bạn nhắn | Kết quả |
|---|---|
| `hôm nay nghỉ phép 4 tiếng, 4 tiếng làm DFU pacsdfum-4482` | 2 dòng: Annual Leave 4h + DFU 4h (PACSDFUM-4482) |
| `hôm nay 2 tiếng sdf pacsgasia-4137, 6 tiếng dfu pacsdfum-4799, pacsdfum-4482` | SDF 2h + DFU 6h |

Phần nào không ghi giờ → bot chia đều số giờ còn lại cho đủ 8h.

### 4.4 Thêm / sửa / xóa / "giống ngày khác"

| Bạn nhắn | Bot làm |
|---|---|
| `thứ 5 làm THÊM SDF 2 tiếng` | thêm task, **giữ** task cũ, chia lại giờ |
| `thứ 5 CHỈ làm Coding thôi` / `ĐỔI LẠI thứ 5 nghỉ phép` | **ghi đè** cả ngày |
| `thứ 5 làm giống thứ 2` | chép y nguyên ngày thứ 2 |
| `nguyên tuần này giống thứ 6 tuần trước` | chép cho cả tuần |
| `xóa ngày 22/9` | **luôn hỏi lại** trước khi xóa |
| `không phải, thay thế các ngày này thành nghỉ phép` | bot hiểu sai → nói lại, bot làm lại từ đầu |

⛔ Nhắn thường **không sửa được ngày đã gửi sếp** → dùng `/edittimesheet` (mục 6).

### 4.5 Ngày lễ

- Bot tự lấy lịch lễ Singapore (trang MOM) và **tự điền** `Public Holiday 8h` khi soạn nháp tối thứ 6 — bạn **không cần nhắn gì**.
- Lễ rơi **Chủ nhật** → tự nghỉ bù **thứ 2** kế tiếp.
- Lễ rơi **thứ 7** → bạn được **+1 ngày nghỉ bù (Special Leave)**, dùng trong 3 tháng (mục 8).
- Lỡ nhắn việc vào đúng ngày lễ → bot **cảnh báo** *"🎌 dd/mm là NGÀY LỄ... Bro vẫn đi làm ngày này?"* → `ok` nếu thật sự đi làm, `hủy` để giữ ngày lễ.

### 4.6 Mã ticket — những điều bot tự lo

- Nhận ra các mã: `PACS...-số` (vd PACSDFUM-4799, PACSNP-3892, PACSGASIA-4137), `INC...`, `CHG...`, `REQ...`, `Ticket# số` / `Ticket # số` / `Ticket #số`.
- Giữ `Part B`, `Part C`... đi liền với mã.
- AI lỡ **bỏ sót** mã bạn gõ → bot **tự bổ sung** và báo cho bạn.
- AI lỡ viết **mã lạ** không có trong câu bạn gõ → bot cảnh báo *"AI thêm mã KHÔNG có trong câu bro gõ"*, bắt bạn xác nhận.
- Cột F nhiều ticket (có dấu phẩy, dài) → trong Excel **tự xuống dòng mỗi ticket 1 dòng**, bỏ dấu phẩy cuối dòng cho gọn.
- Mã PACS **gõ đảo chữ** (vd `pcasdfum-89294`, `pascnp-123`) → bot **tự sửa** thành `PACSDFUM-89294`, `PACSNP-123` (viết hoa, xuống dòng như mọi ticket) và **báo cho bạn** trong bước xác nhận: *"✏️ Đã sửa mã gõ nhầm: pcasdfum-89294 → PACSDFUM-89294 — đúng thì nhắn ok, sai thì nói lại."*

### 4.7 File Excel trình bày cột D / E / F thế nào

Bot tự lo **viết hoa**, **xuống dòng** và **chiều cao hàng** — bạn chỉ cần nhắn như bình thường.

**① Viết hoa** (cột D và F)
- Chỉ **mã ticket** được viết hoa: `pacsdfum-4799` → `PACSDFUM-4799`, `inc372` → `INC372`, `ticket # inc002842` → `Ticket # INC002842`, `part b` → `Part B`.
- Dấu gạch **giữ đúng như bạn gõ** (`pacsnp-3892` → `PACSNP-3892`, `pacsnp3892` → `PACSNP3892`).
- **Chữ mô tả giữ nguyên** (không đổi hoa/thường): `fix dateend`, `to check policy softlock`...

**② Cột F tự xuống dòng — mỗi ticket 1 dòng**

Chỉ xuống dòng khi mô tả **có dấu phẩy** **và dài** (hơn khoảng 60 ký tự). Quy tắc:
- Ngắt **trước mỗi ticket** đứng sau dấu phẩy / chấm phẩy / dấu chấm.
- **Bỏ dấu phẩy ở cuối mỗi dòng** (đã xuống dòng thì không cần phẩy). Dấu phẩy ở chỗ khác giữ nguyên.
- `Ticket #` / `Ticket#` **luôn bắt đầu dòng mới**.
- **Không** ngắt bên trong dấu ngoặc `( ... )`.
- Mô tả **ngắn** → giữ **1 dòng**, còn nguyên dấu phẩy.

| Bạn nhắn (phần mô tả) | Ô cột F trong Excel |
|---|---|
| `dfu pacsdfum-224 part b, pacsdfum-4799 part d, pacsdfum-4482, inc372, ticket # inc002842: policy number 1234567 claim no 001 00 00 invalid date format for all record` | `PACSDFUM-224 Part B`<br>`PACSDFUM-4799 Part D`<br>`PACSDFUM-4482`<br>`INC372`<br>`Ticket # INC002842: policy number 1234567 claim no 001 00 00 invalid date format for all record` |
| `sdf pacsgasia-4137 fix dateend, pacsdfum-4799 rerun extract (ref inc2799, inc2800), pacsdfum-4482 retest` | `PACSGASIA-4137 fix dateend`<br>`PACSDFUM-4799 rerun extract (ref INC2799, INC2800)`<br>`PACSDFUM-4482 retest` |
| `prod issue cho Ticket# 02238471 - to check client receives premium notice despite of prem notice being suppressed, Ticket# 479829 - to check policy softlock` | `Ticket# 02238471 - to check client receives premium notice despite of prem notice being suppressed`<br>`Ticket# 479829 - to check policy softlock` |
| `dfu pacsdfum-4482, inc2799, pacsdfum-4897` (ngắn) | `PACSDFUM-4482, INC2799, PACSDFUM-4897` (1 dòng) |

(Dòng quá dài so với bề rộng cột, như dòng `Ticket # INC002842: ...` ở trên, Excel tự gói tiếp xuống dòng dưới.)

**③ Cột D dài (NP nhiều mã PACSNP)**
Không xuống dòng theo mã như cột F — ô cột D **tự gói chữ** theo bề rộng cột, vd
`PACSNP-1982, PACSNP-4583, PACSNP-284, PACSNP-7878, PACSNP-8209, PACSNP-9911, PACSNP-10234` → hiện thành 3 dòng trong ô.

**④ Cột E** luôn là **1 tên task ngắn cố định** (`Coding/UT`, `DFU`, `SDF`, `Issue Investigation`, `Annual Leave`...) → không bao giờ xuống dòng.

**⑤ Chiều cao hàng — tự nâng vừa sát chữ, không cắt chữ, không thừa khoảng trắng**

| Hàng | Chiều cao |
|---|---|
| Bình thường (cột D, F đều 1 dòng) | giữ chuẩn của file mẫu (~1 dòng) — **không đụng** |
| Cột F xuống dòng | nâng **vừa đủ** số dòng chữ của cột F |
| Cột D dài phải gói nhiều dòng | nâng **vừa đủ** cho cột D |
| Cả D lẫn F đều dài | lấy **số lớn hơn** — không cột nào bị cắt chữ |

Ví dụ thật: hàng 5 ticket ở trên cao khoảng 5–6 dòng chữ; hàng NP 7 mã khoảng 3 dòng; hàng thường giữ 1 dòng.

> Muốn hàng thấp / cao hơn chút: mở `src\excel_writer.py` bằng Notepad, bấm **Ctrl + F** tìm chữ `LINE_SPACING` — có 2 dòng
> `LINE_SPACING = 1.25` (cột D) và `LINE_SPACING_F = 1.25` (cột F) — giảm số là thấp hơn, tăng là cao hơn (thử từng bước 0.05).
>
> Bot **đo độ rộng theo từng chữ** (chữ IN HOA và chữ số rộng hơn chữ thường) để biết ô cần bao nhiêu dòng — nên hàng có nhiều mã ticket IN HOA (DFU, cột D nhiều mã PACSNP) cũng đủ cao, không cắn chữ trên / dưới.

**⑥ Nhiều task trong 1 câu** → mỗi task là **1 hàng riêng** trong Excel (vd `nghỉ phép 4 tiếng, 4 tiếng làm DFU pacsdfum-4482` → 2 hàng: Annual Leave 4h và DFU 4h).

**Lưu ý:** việc xuống dòng **chỉ có trong file Excel**. Dữ liệu bot lưu, `/summary` và email xem trước vẫn hiện mô tả **1 dòng** như bạn gõ; khi bot đọc lại Excel (gởi lại, sửa, tính phép) vẫn ra đúng câu gốc.

---

## 5. Tối thứ 6 — gửi timesheet cho sếp

### Luồng tự động

**17:00 thứ 6**, máy tính tự chạy việc chốt timesheet cho **tuần này** (T2 → T6). Có 3 trường hợp:

**① Đủ dữ liệu cả tuần** → bot nhắn **BẢN NHÁP** + file Excel xem trước. **Chưa gửi gì cho sếp.**
```
bạn nhắn:  ok        → bot hiện EMAIL XEM TRƯỚC
                       (From / To / Bcc / Subject / nội dung / D-E-F từng ngày)
bạn nhắn:  ok        → lúc này bot MỚI GỬI cho sếp
```
- Muốn tự viết nội dung email (nhắn thêm gì cho sếp) → lúc đang xem trước email, gõ **`/manualmail`** (mục 7).
- Không muốn gửi → nhắn `hủy` hoặc `/resetmailts`.

**② Còn thiếu** (vd chưa điền thứ 6) → bot nhắn danh sách thiếu:
```
Tới giờ chốt timesheet (thứ 6 02/10) mà còn thiếu nè bro:
• thứ 6 ngày 02/10: chưa có task nào
Bro điền bổ sung giúp mình (nhắn như ghi chú bình thường). Điền xong thì gõ /weeklyrun
(hoặc nhắn "gởi timesheet tới hôm nay") để mình soạn bản nháp.
```
→ Điền phần thiếu → gõ **`/weeklyrun`** → quay lại trường hợp ①.
(Điền bù vào thứ 7, Chủ nhật hay thứ 2 tuần sau vẫn được — bot vẫn chốt **đúng tuần có thứ 6 đó**.)

**③ Tuần này đã gửi rồi** → bot báo *"Timesheet thứ 6 dd/mm đã gửi trước đó rồi nha bro, tuần này khỏe."*

### Các câu / lệnh hữu ích quanh việc gửi

| Bạn nhắn / gõ | Tác dụng |
|---|---|
| `gởi timesheet tới hôm nay` | chốt sớm (vd thứ 5 xin nghỉ thứ 6) |
| `khoan gởi` / `bỏ khoan` | tạm giữ, không gửi tự động / cho gửi lại bình thường |
| `cứ gởi đi` | gửi dù còn cảnh báo |
| `/weeklyrun` | chạy việc chốt tuần bằng tay |
| `/createdraft` · `/checkdraft` · `/deletedraft` | tạo / xem / xóa bản nháp |
| `/forcedraft` | tạo bản nháp bỏ qua lỗi kiểm tra |
| `/sendmail` · `/forcesendmail` | gửi bản nháp / gửi dù còn lỗi |

**Sau khi gửi:** bot báo *"📤 ĐÃ GỬI"* (server mail đã nhận), báo số ngày phép còn lại, tự dọn nhật ký tin nhắn (có backup). Nếu là **thứ 6 / thứ 7 / CN** và vừa gửi timesheet **tuần này** → bot chúc cuối tuần và **tự tắt sau 1 phút** (xem ngay dưới).

### 🌙 Gửi xong tối thứ 6 → bot chúc cuối tuần và tự tắt

Gửi **thành công** timesheet của **tuần này** vào **thứ 6, thứ 7 hoặc Chủ nhật** → bot nhắn:
```
✅ Timesheet tuần 02/10 đã gửi thành công.
🎉 Chúc bro một cuối tuần vui vẻ bên gia đình!
🤖 Bot tự tắt lúc 17:56 sau khi gửi timesheet tuần 02/10 thành công. Cần dùng lại thì
   nhấp đúp start_bot.vbs (Mac: start_bot.command) — hoặc bot tự bật lúc 16:00 hôm sau.
```
→ **1 phút sau** bot tự tắt (không chạy vô ích tới 23:59).

| Trường hợp | Tự tắt sau khi gửi? |
|---|---|
| Gửi timesheet **tuần này** vào **T6 / T7 / CN** (kể cả gửi trễ tối T7, CN) | ✅ Có — chúc cuối tuần + tắt sau 1 phút |
| **Chốt sớm** thứ 2 – thứ 5 (`gởi timesheet tới hôm nay`) | ❌ Không |
| Gửi **muộn** timesheet tuần trước, từ **thứ 2 tuần sau** trở đi | ❌ Không |
| **Gởi lại** bản sửa (`/resend`) | ❌ Không |
| Bật lại bot tay sau khi nó đã tự tắt | ❌ Không tự tắt nữa (chỉ tắt lúc 23:59 như thường) |

### 👀 Muốn XEM TRƯỚC file Excel rồi mới quyết định gửi?

**Không có gì tự gửi sếp** — bot luôn chờ bạn nhắn `ok` **2 lần**. Nên bạn có thể yên tâm tạo bản nháp, mở file Excel ra xem trước, rồi mới quyết định.

**Luồng 1 — Bình thường (để bot tự chạy 17:00, không cần mở thư mục):**
```
Mỗi ngày: nhắn ghi chú cho bot
        │
17:00 T6 ▼  weekly_run.py tự chạy
   soạn BẢN NHÁP + tạo file Excel xem trước (data\preview\)
   → nhắn Telegram: tóm tắt + GỬI KÈM FILE EXCEL xem trước (chỉ lịch 17:00 tự động)
        │
        ▼  bạn mở file Excel được gửi kèm trong Telegram để xem (hoặc mở trong data\preview\)
   ┌─ ổn ──────► nhắn  ok  → hiện EMAIL XEM TRƯỚC → nhắn  ok  → ĐÃ GỬI SẾP ✅
   └─ cần sửa ─► nhắn sửa như ghi chú → /createdraft → xem lại → ok → ok
```

> **Lưu ý — khi nào bot gửi kèm file Excel vào Telegram:** **chỉ lịch 17:00 tự động** (hoặc nhấp đúp `run_weekly.vbs`). Gõ lệnh `/weeklyrun` hay `/createdraft` thì bot **chỉ nhắn tóm tắt** (số ngày, tổng giờ, tên file) — file Excel xem trước nằm trong `data\preview\` (xem Luồng 2). Khi bạn nhắn `ok` lần 1, bot hiện **nội dung từng ngày (cột D / E / F) ngay trong chat** để bạn xem lại lần cuối trước khi `ok` lần 2.

**Luồng 2 — Tự tạo bản nháp sớm để xem trước** (vd 15:00 thứ 6 đã nhập xong cả tuần):
```
① Gõ  /createdraft
     → bot nhắn TÓM TẮT bản nháp (giờ từng ngày, tổng giờ)
     → file Excel xem trước được tạo trong thư mục:
         🪟 C:\timesheet\data\preview\
         🍎 ~/timesheet/data/preview/
       tên file ĐÚNG như file sẽ gửi sếp, vd:
         LiveReport Sept_2026 -TenBan (25 Sept).xlsx
② Mở file đó bằng Excel để xem  (🪟 Windows + R → dán  C:\timesheet\data\preview  → Enter)
   ⚠️ XEM XONG NHỚ ĐÓNG EXCEL (file đang mở thì bot không ghi / gửi được)
③ Quyết định:
   ┌─ Ổn, gửi luôn ─────► nhắn  ok  → EMAIL XEM TRƯỚC (From / To / nội dung / file đính kèm)
   │                       → nhắn  ok  → ĐÃ GỬI SẾP ✅
   ├─ Cần sửa ──────────► nhắn sửa như ghi chú bình thường, vd "thứ 5 đổi thành nghỉ phép"
   │                       → bot ghi bản sửa + báo "bản nháp CŨ đã HỦY"
   │                       → gõ lại  /createdraft  → mở file mới xem lại → ok → ok
   └─ Chưa muốn gửi ────► cứ để đó: bản nháp KHÔNG hết hạn.
                           (17:00 bot vẫn tự chạy, soạn lại bản nháp mới nhất + nhắn kèm file)
```

- File xem trước trông **y hệt** file sẽ gửi sếp (kể cả xuống dòng mỗi ticket ở cột F) — chỉ khác là **chưa gửi ai**.
- **Đã có bản nháp mà nhắn sửa** một ngày trong tuần đó → bot **tự hủy bản nháp cũ** và nhắc bạn `/createdraft` lại, để **không bao giờ gửi nhầm bản chưa sửa**.
- `/checkdraft` xem lại tóm tắt bản nháp đang chờ · `/deletedraft` xóa bản nháp · `khoan gởi` / `bỏ khoan` đánh dấu tạm giữ.

### 📋 Tóm tắt: chiều thứ 6 diễn ra thế nào — bot có tự tắt không?

**17:00 thứ 6**, máy tự chạy chương trình riêng **`weekly_run.py`** (*không phải bot* — xem mục 3e). Nó chạy **vài giây**:
1. Kiểm tra / soạn bản nháp timesheet cả tuần.
2. Kiểm tra **bot** (`bot.py`): bot **chưa chạy → tự bật bot lên**; đang chạy rồi → thôi.
3. Nhắn Telegram cho bạn (danh sách ngày còn thiếu, hoặc bản nháp).
4. **`weekly_run.py` tự thoát.** Đây là chương trình *kiểm tra* thoát — **bot vẫn chạy tiếp**.

| Tình huống | Chuyện gì xảy ra | Bot có tự tắt? |
|---|---|---|
| **Chưa đủ** timesheet cả tuần | Nhắn danh sách ngày còn thiếu → bạn điền bổ sung → gõ `/weeklyrun` | ❌ Không — bot vẫn chạy để bạn điền tiếp |
| **Đủ** timesheet | Nhắn **bản nháp** → chờ bạn trả lời | ❌ Không — bot chờ |
| **Chờ lâu** (vd 2 tiếng) không trả lời | Bản nháp **không có giờ hết hạn** — vẫn nằm chờ | ❌ Không — bot chạy tới **23:59** |
| Bạn nhắn **`ok`** (lần 1) | Hiện **email xem trước** (From / To / nội dung / file Excel) — **chưa gửi** | ❌ Không |
| Bạn nhắn **`ok`** (lần 2) | **Gửi** mail + file Excel cho sếp | ✅ T6 / T7 / CN: chúc cuối tuần + **tự tắt sau 1 phút** · ❌ chốt sớm T2–T5 / gửi muộn tuần trước: vẫn chạy tới 23:59 |
| Tới **23:59** vẫn chưa trả lời | Bot tự tắt theo lịch, nhưng **bản nháp KHÔNG mất** (lưu trong file trạng thái) → 16:00 hôm sau bot bật lại, nhắn `ok` là tiếp tục | Tắt lúc 23:59 (như mọi ngày) |

**Bot chỉ tắt khi:** tới **23:59** (tự tắt, 16:00 hôm sau tự bật lại) — hoặc **gửi xong timesheet tuần này vào T6 / T7 / CN** (tự tắt sau 1 phút) — hoặc bị tắt **từ bên ngoài** (tắt máy, máy ngủ, End task…). Chốt tuần hay gửi mail **chưa xong** thì bot không tắt.

> Bản nháp timesheet **không bao giờ tự hủy** vì chờ lâu — chỉ mất khi bạn nhắn `hủy` / `/deletedraft`, hoặc khi đã gửi.

---

## 6. Sửa timesheet đã gửi + gửi lại

Dùng cho ngày **đã gửi sếp** (tuần trước, tháng trước...) và cả ngày trong tuần này.

```
/edittimesheet
→ nhắn:  ngày 10/9: nghỉ phép 2 tiếng, 6 tiếng SDF PACSGASIA-7763
→ bot hiện bản sửa → ok   (hoặc nói sửa lại, lặp tới khi đúng; hủy để thoát)
```

Ví dụ khác:
- `sửa thứ 2 tới thứ 4 tuần trước nghỉ phép`
- `thứ 4 tuần trước làm giống thứ 2 tuần này`
- `xóa ngày 16/9`

Ngày **đã gửi** → bot sửa **cả file Excel** (có backup bản cũ) → sau đó gõ **`/resend`** (hoặc nhắn `gởi lại`) để gửi sếp bản mới — vẫn có **xem trước**, `ok` mới gửi.

- Bị chặn vì cảnh báo (vd vượt số ngày nghỉ bù) → sửa rồi `/resend` lại, hoặc nhắn `vẫn gởi` / gõ `/forcesendmail` để bỏ qua cảnh báo.
- ⚠️ **Không** dùng `/sendmail` hay `/createdraft` cho tuần đã gửi.

---

## 7. Email cho sếp (xin nghỉ...) + chọn mail gửi

### Soạn email bằng AI
```
/composemail
→ nhắn tiếng Việt, vd:  xin nghỉ chiều mai
→ AI viết tiếng Anh:    "... tomorrow afternoon, Friday 25/9 (halfday afternoon)"
```
- Ngày luôn có **thứ + ngày** (dạng 25/9). Bản xem trước có luôn **số ngày phép còn lại**.
- `ok` → gửi · nói sửa (vd *"thêm as communicated"*) → AI sửa · `hủy` hoặc `/resetmail` → không gửi.

### Tự gõ email
- `/composemanual` → tự gõ `Subject:` + nội dung.
- `/manualmail` → **lúc đang xem trước email timesheet** (thứ 6 hoặc gởi lại): tự gõ **100%** nội dung email. Bot gửi **nguyên văn**, giữ tiêu đề + file đính kèm, **không lưu lại ở đâu**. (Bot không tự thêm ghi chú nghỉ bù — cần thì tự viết vào.)

### Gửi bằng mail nào
| Chế độ | From | Bcc |
|---|---|---|
| **Mặc định: MAIL CÔNG TY** | `company_email` | `bcc_when_company` |
| `/personalmailon` → **Gmail cá nhân** | `GMAIL_ADDRESS` | `company_email` |
| `/personalmailoff` → về mail công ty | | |

Áp dụng cho **cả** timesheet lẫn email xin nghỉ.

**Chưa thiết lập Gmail** (để `chua_co` hoặc điền sai dạng) → bot **luôn gửi bằng mail công ty**, không báo lỗi. Gõ `/personalmailon` lúc đó thì bot chỉ **cảnh báo** *"⚠️ Chưa thiết lập Gmail cá nhân… → Bot VẪN gửi bằng MAIL CÔNG TY"* kèm cách thiết lập (Bước 7), không chuyển chế độ.

**Gửi lỗi** (sai mật khẩu, mạng chặn, server từ chối, file quá lớn...) → bot báo *"❌ MAIL CHƯA GỬI ĐƯỢC"* + lý do + cách xử lý. Email đang chờ **được giữ lại** → đổi mail (`/personalmailon`) → `ok` → bot hiện lại email → `ok` gửi.

> Bot **không tự đổi** mail. "📤 ĐÃ GỬI" nghĩa là server mail đã nhận; bot **không** dò thêm sếp có nhận được không.

---

## 8. Ngày phép

| Loại | Số ngày/năm | Ghi chú |
|---|---|---|
| Annual Leave | 17 | reset 1/1, phép dư **không** chuyển sang năm sau |
| Sick Leave | 14 | cần giấy MC |
| Special Leave | +1 cho **mỗi lễ rơi thứ 7** | dùng trong **3 tháng** từ ngày lễ; bot trừ ngày sắp hết hạn trước |

- Đổi số ngày/năm: trong `settings.json` thêm/sửa `"annual_leave_per_year": 18,` và `"sick_leave_per_year": 14,`. Báo trước cho năm sau: `"leave_entitlement_by_year": {"2027": {"annual": 18}},`
- Bot **tự tính lại** từ file Excel đã gửi mỗi lần xem / gửi (không trừ trùng). Nghỉ 4 tiếng = 0,5 ngày.

| Lệnh | Tác dụng |
|---|---|
| `/leavebal` | số dư: "đã chốt" (đã gửi) + "dự kiến" (tính cả tuần này chưa gửi), ngày bù + hạn dùng |
| `/leavelog` | từng ngày đã nghỉ trong năm (✅ đã gửi · 🕓 chưa gửi) |
| `/updateleave AL 10` | khai phép năm còn 10 ngày |
| `/updateleave SICK 14 SL 0` | nghỉ bệnh còn 14, nghỉ bù còn 0 |
| `/updateleave AL 9.5` | còn 9 ngày rưỡi |
| `/updateleave reset` | bỏ số tự khai, để bot tự tính |

- Sau khi khai `/updateleave`, **mọi thay đổi về sau** (kể cả sửa ngày cũ bằng `/edittimesheet`) đều được cộng/trừ vào con số đó.
- Nghỉ bù **không phải** do lễ thứ 7 (vd bù OT) → khai `/updateleave SL <số>` → bot chấp nhận theo số dư đó.
- Email timesheet có ngày nghỉ bù → bot **tự thêm câu báo sếp**, vd *"Please note I took a day of special leave on 25 Sept, in lieu of the public holiday which fell on Saturday 08/08/2026."* (nửa ngày → "half a day").
- Bot tự nhắc: ngày bù sắp hết hạn (≤ 14 ngày), xin nghỉ vượt số dư, ghi Sick Leave → nhớ gửi MC.

---

## 9. Khi AI bị lỗi mạng

- AI không kết nối được → bot **tự bóc câu bằng luật có sẵn** → **luôn hiện xem trước**, `ok` mới ghi.
- Luật dự phòng hiểu được: ngày, từ khóa từng loại task, số giờ, nửa ngày, nhiều task có ghi giờ, xóa cả ngày.
- Câu luật cũng không hiểu → tin vào **HÀNG CHỜ**, chưa ghi vào timesheet. Còn tin chờ → bot **chặn** tạo nháp & gửi (để không gửi sếp bản thiếu).

| Lệnh | Tác dụng |
|---|---|
| `/retrynotes` | xử lý lại tin đầu tiên trong hàng chờ (khi AI ổn lại) |
| `/retrynotes xem` | xem danh sách tin đang chờ |
| `/retrynotes bỏ` | bỏ tin đầu (khi bạn đã tự gõ lại câu khác) |

---

## 9b. Bot gọi AI thế nào

> Phần này giải thích **cơ chế bên trong** — không cần làm gì thêm. Đọc khi muốn hiểu vì sao bot đang dùng luật dự phòng, hay khi gặp lỗi AI.

**AI dùng gì:** **Google Gemini**, gọi bằng API key miễn phí của bạn (Bước 6). **Không bật thanh toán → không bao giờ mất tiền**; đổi lại Google giới hạn **số lượt gọi mỗi ngày cho từng model** (con số do Google quy định, có thể thay đổi). Giới hạn làm mới mỗi ngày theo giờ Mỹ (khoảng trưa – đầu giờ chiều giờ Việt Nam).

**Khi nào bot gọi AI:** khi bạn nhắn ghi chú / sửa timesheet (`/edittimesheet`), soạn email (`/composemail`), và tối thứ 6 nếu còn ghi chú cần AI tổng hợp. Các lệnh xem như `/status`, `/summary`, `/leavebal` **không** gọi AI.

**Thứ tự ưu tiên model** (nhẹ + nhanh trước, không dùng bản "pro" — thừa cho việc timesheet):
1. `gemini-flash-lite-latest` — model **chính**, luôn thử **đầu tiên**
2. Các bản lite dự phòng: `gemini-2.5-flash-lite` → `gemini-2.0-flash-lite`
3. `gemini-flash-latest` — dự phòng mức 1
4. Các bản flash dự phòng: `gemini-2.5-flash` → `gemini-2.0-flash`

Mỗi **ngày mới** bot tự quay về model chính (số 1).

**Không viết cứng tên model:** `settings.json` để `"gemini_model": "auto"`. Bot **tự hỏi Google danh sách model** đang có (việc này **không tốn lượt**), xếp hạng theo đặc điểm (có chữ *flash*, bản ổn định, phiên bản mới hơn) chứ không theo tên. Google khai tử model cũ → bot tự chuyển sang model khác, không cần sửa code.

**Bộ nhớ đệm (cache)** — 2 file trong `data\` (bot tự tạo, tự cập nhật):

| File | Lưu gì |
|---|---|
| `ai_model.json` | model **đang dùng tốt**, danh sách model ứng viên, model **đã hết lượt hôm nay**, cờ **"hôm nay dùng luật dự phòng"**, ngày của cache. Mỗi lần bot bật, bot kiểm tra cache và **dò lại danh sách model định kỳ** (khoảng mỗi tháng). |
| `ai_usage.json` | đếm số lượt đã gọi AI (hôm nay / tháng này) — `/status` hiển thị. `"ai_calls_per_month"` trong settings **chỉ để theo dõi, không chặn** (Google tự chặn bằng lỗi hết lượt). |

(`ai_model.json` bị hỏng hay bị xóa → bot coi như chưa có cache và tự tạo lại, không sao.)

**Bot xử lý từng loại lỗi AI:**

| Lỗi từ Google | Nghĩa | Bot làm gì |
|---|---|---|
| **429** — RESOURCE_EXHAUSTED | Model đó **hết lượt hôm nay** | Ghi nhận "model này hết lượt hôm nay" → **chuyển ngay** model kế (không thử lại, vì thử lại cũng tốn lượt vô ích) |
| **503** — UNAVAILABLE / quá thời gian | Server Google **quá tải tạm thời** | **Thử lại 3 lần**, mỗi lần cách **5 giây** → vẫn lỗi thì thử **1 model thuộc hệ server khác** (lite ↔ flash) |
| **404** — NOT_FOUND | Model **bị Google khai tử** | Chuyển model kế ngay |
| **401 / 403** | **API key sai** / bị thu hồi | Báo lỗi key (cách xử lý ở bảng dưới) |
| Trả lời **bị cắt** (quá dài) | Tin nhắn quá dài | Báo *"bị CẮT vì quá dài, chia nhỏ câu"* — không chuyển sang luật dự phòng |

**Khi mọi model đều không dùng được** (hết lượt hết, hoặc cả 2 hệ server cùng quá tải, hoặc mất mạng) → bot bật **chế độ luật dự phòng cho hết ngày hôm đó** (mục 9): vẫn ghi được timesheet, **luôn xem trước + `ok`**, câu khó thì vào hàng chờ.
- `/status` hiện dòng **"🔌 AI hôm nay đang LỖI → bot tự bóc bằng luật (rule)"**.
- **Sang ngày mới** → tự quay lại dùng AI từ model chính.
- Muốn AI thử lại ngay trong ngày (vd mạng đã có lại) → `/retrynotes` (bot gỡ cờ và cho AI 1 cơ hội; vẫn lỗi thì cờ tự bật lại).

**Lỗi AI thường gặp & cách xử lý:**

| Dấu hiệu | Nguyên nhân | Cách xử lý |
|---|---|---|
| *"Gemini từ chối API key"* | Key sai / bị xóa / SDK cũ không nhận key dạng `AQ.` | Chạy `python -m pip install --upgrade google-genai` → vẫn lỗi: tạo key mới (Bước 6), sửa `secrets.env`, **khởi động lại bot** (mục 3d) |
| *"Chạm giới hạn free tier của Google"* / nhiều ngày liền rơi vào luật dự phòng | Dùng hết lượt miễn phí | Không cần làm gì — luật dự phòng vẫn chạy; hôm sau AI tự hồi phục |
| *"Server Gemini đang quá tải tạm thời (503)"* | Sự cố phía Google | Tự hết sau vài phút; bot tự thử lại / dùng luật dự phòng |
| *"Thiếu gói google-genai"* | Thiếu thư viện | `python -m pip install -r requirements.txt` (trong thư mục timesheet) |
| Luật dự phòng cả ngày dù mạng tốt | Mạng công ty chặn Google AI, hoặc hết lượt | Kiểm tra bằng lệnh bên dưới; `/retrynotes` để thử lại |

**2 lệnh kiểm tra AI** (mở `cmd` → `cd /d C:\timesheet\src` · 🍎 Mac: `cd ~/timesheet/src` và thay `python` bằng `../.venv/bin/python`):
```
python ai_client.py --models
python ai_client.py
```
- `--models`: liệt kê model Google đang cho dùng — **không tốn lượt**. Không liệt kê được → mạng chặn hoặc API key sai.
- Không có `--models`: gọi AI thử **1 lượt** thật → thấy trả lời là AI hoạt động tốt.

---

## 10. Dữ liệu, backup và các lệnh xóa

| File / thư mục | Là gì |
|---|---|
| `data\parsed_days.json` | ⭐ **quan trọng nhất**: timesheet từng ngày. **Không xóa, không sửa tay.** |
| `data\notes.jsonl` | nhật ký tin nhắn; tự làm trống (có backup) sau mỗi lần gửi |
| `output\LiveReport_YYYY-MM.xlsx` | file Excel theo tháng đã gửi sếp — **giữ vĩnh viễn** (bot dùng để tính phép) |
| `data\backup\` | backup tự động (tự dọn theo hạn 30–90 ngày) |
| `backup\` | bản sao Excel trước mỗi lần sửa (giữ 90 ngày) |
| `data\logs\` | nhật ký kỹ thuật (gửi kèm khi báo lỗi) |

`parsed_days.json` bị hỏng → bot cất bản hỏng vào `data\backup\corrupt\` và báo ở `/status`. Khôi phục: chép bản mới nhất trong `data\backup\parsed_days_daily\` về `data\parsed_days.json` rồi khởi động lại bot.

### 📁 File Excel: đặt tên thế nào, nằm ở đâu, tạo / xóa khi nào

**Sếp nhận timesheet theo THÁNG.** Mỗi tuần bot gửi file của **tháng đó**, **cộng dồn** từ ngày 1 tới ngày gửi. Tên file theo mẫu trong `settings.json`:
```
LiveReport <Tháng>_<Năm> -TenBan (<ngày gửi> <tháng gửi>).xlsx
```

**Ví dụ tháng 9 – 10/2026:**

| Ngày gửi | Tuần | File gửi sếp (đính kèm email) | Trong file có |
|---|---|---|---|
| T6 18/09 | 14–18/09 | `LiveReport Sept_2026 -TenBan (18 Sept).xlsx` | 01/09 → 18/09 |
| T6 25/09 | 21–25/09 | `LiveReport Sept_2026 -TenBan (25 Sept).xlsx` | 01/09 → 25/09 (cộng dồn) |
| **T6 02/10** | **28/09–02/10 (vắt 2 tháng)** | **2 file trong CÙNG 1 email:** | |
| | | `LiveReport Sept_2026 -TenBan (2 Oct).xlsx` | 01/09 → **30/09** (đủ tháng 9) |
| | | `LiveReport Oct_2026 -TenBan (2 Oct).xlsx` | **01/10 → 02/10** |
| T6 09/10 | 05–09/10 | `LiveReport Oct_2026 -TenBan (9 Oct).xlsx` | 01/10 → 09/10 |

→ Tuần vắt qua 2 tháng: bot **tự tách** — ngày của tháng nào vào **file tháng đó**, cả 2 file được **đính kèm chung 1 email**. Tên file mang **tháng của dữ liệu** (Sept / Oct) + **ngày gửi** (2 Oct).

**File Excel nằm ở 3 thư mục (trong thư mục cài đặt `C:\timesheet` / 🍎 `~/timesheet`):**

| Thư mục / file | Là gì | Tạo khi nào | Giữ bao lâu |
|---|---|---|---|
| `data\preview\LiveReport Sept_2026 -TenBan (2 Oct).xlsx` | **File XEM TRƯỚC** — giống hệt file sẽ gửi, **chưa gửi ai** | Mỗi lần soạn bản nháp: 17:00 thứ 6, `/createdraft`, `/weeklyrun`, chốt sớm. Soạn lại → **ghi đè** | **Tự xóa sau 7 ngày** (tạo lại được bất cứ lúc nào) |
| `output\LiveReport_2026-09.xlsx` | **File làm việc của THÁNG** — sổ gốc bot giữ, cập nhật dần | Lần đầu gửi tháng đó; **cập nhật** mỗi lần gửi, và khi `/edittimesheet` sửa ngày đã gửi | **Giữ vĩnh viễn** — bot dùng để tính ngày phép, gửi lại. **Không xóa** |
| `output\LiveReport Sept_2026 -TenBan (25 Sept).xlsx` | **Bản ĐÃ GỬI sếp** — bản sao đúng từng lần gửi (tên có ngày gửi) | Lúc bạn nhắn `ok` lần 2 (gửi) hoặc `/resend` (gửi lại) | **Giữ vĩnh viễn** — làm lịch sử, mỗi tuần thêm 1 file |
| `backup\LiveReport_2026-09.before_20261002_170512.xlsx` | Bản sao file làm việc **ngay trước mỗi lần ghi** (phòng ghi hỏng) | Trước mỗi lần bot ghi đè `output\LiveReport_YYYY-MM.xlsx` | **Tự xóa sau 90 ngày** |

**Khác nhau giữa `data\preview\` và `output\`:**
- `data\preview\` = **nháp để xem** — có thể khác bản gửi nếu bạn sửa sau đó; bị ghi đè / tự xóa; **không bao giờ được gửi**.
- `output\` = **sản phẩm thật** — chỉ có file khi **đã gửi** (hoặc sửa ngày đã gửi); **không bao giờ tự xóa**.
- Muốn biết sếp **đã nhận đúng file nào** → mở `output\` tìm file có **ngày gửi** tương ứng (vd `(25 Sept)`).

**Lệnh xóa (từ nhẹ tới mạnh):**

| Lệnh | Tác dụng |
|---|---|
| `/resetstatus` | gỡ trạng thái bị kẹt (nháp / câu hỏi treo). **Không** xóa dữ liệu |
| `/deletedraft` | xóa bản nháp đang chờ gửi |
| `/clearnotes` | làm trống nhật ký tin nhắn (có backup), **giữ** timesheet. Hiếm khi cần |
| `/resetnotes` | ⚠️ xóa **cả** nhật ký lẫn timesheet (có backup). Chỉ khi muốn làm lại từ đầu |

---

## 11. Bảng TẤT CẢ lệnh

| Lệnh | Tác dụng |
|---|---|
| `/start` · `/help` | xem hướng dẫn |
| `/status` | tình trạng: đang nhập / có nháp / đã gửi, từng ngày T2–T6, tin chờ, ngày phép, mail đang dùng, AI |
| `/summary` · `/summaryweek` | toàn bộ công việc theo ngày / tuần này |
| `/edittimesheet` | sửa timesheet (cả ngày đã gửi) |
| `/weeklyrun` | chạy việc chốt tuần bằng tay |
| `/createdraft` · `/forcedraft` | tạo bản nháp / tạo dù còn lỗi |
| `/checkdraft` · `/deletedraft` | xem / xóa bản nháp |
| `/sendmail` · `/forcesendmail` | gửi bản nháp / gửi dù còn lỗi |
| `/resend` | gửi lại tháng vừa sửa (có xem trước) |
| `/manualmail` | tự gõ nội dung email timesheet (lúc đang xem trước) |
| `/resetmailts` | hủy email timesheet đang chờ |
| `/composemail` · `/composemanual` | soạn email cho sếp bằng AI / tự gõ |
| `/resetmail` | hủy email đang soạn |
| `/personalmailon` · `/personalmailoff` | gửi bằng Gmail cá nhân / về mail công ty |
| `/leavebal` · `/leavelog` · `/updateleave` | ngày phép (mục 8) |
| `/retrynotes` | hàng chờ khi AI lỗi (mục 9) |
| `/checknotes` · `/checkexcel` | kiểm tra dữ liệu D/E/F · kiểm tra file Excel tháng |
| `/resetstatus` · `/clearnotes` · `/resetnotes` | lệnh xóa (mục 10) |

---

## 12. Sự cố thường gặp

**❓ Nhắn mà bot không trả lời**
- Bot chỉ chạy từ **16:00 tới 23:59** (hoặc khi bạn bật tay). Ngoài giờ đó → nhấp đúp `C:\timesheet\start_bot.vbs`, chờ 10 giây, nhắn lại.
- **Tối thứ 6 / cuối tuần sau khi đã gửi xong timesheet tuần** → bot **tự tắt** (bình thường, xem mục 5). Cần dùng → nhấp đúp `start_bot.vbs`.
- Máy tắt / ngủ / khởi động lại sau 16:00 → bot không tự bật lại → nhấp đúp `start_bot.vbs`.
- Nhấp đúp `start_bot.vbs` nhiều lần **không sao** — bot tự chặn chạy trùng.
- 🍎 Mac: bật tay bằng `start_bot.command`; lỗi (nếu có) nằm trong `~/timesheet/data/logs/bot_console.log`.
- Vẫn im → mở `cmd`, chạy tay để xem lỗi:
  ```
  cd /d C:\timesheet\src
  python bot.py
  ```
  (dừng bằng **Ctrl + C**). Chụp màn hình lỗi gửi người chia sẻ.

**❓ Nhận được tin tối thứ 6 nhưng gõ lệnh không thấy bot trả lời**
Việc chốt thứ 6 là **chương trình riêng**, tự nhắn Telegram rồi thoát — tin vẫn tới **kể cả khi bot đang tắt**. Muốn dùng lệnh → bật bot (`start_bot.vbs`).

**❓ Đổi `settings.json` (vd đổi email sếp) mà bot vẫn dùng cái cũ**
Bot chỉ đọc cấu hình **lúc khởi động** → **khởi động lại bot**: nhấp đúp `restart_bot.bat` (🍎 Mac: `restart_bot.command`). Chi tiết mục **3d**.

**❓ Báo lỗi khi ghi Excel / "file đang mở"**
Đóng file Excel `LiveReport...` đang mở (bot không ghi được khi Excel đang mở file đó), rồi thử lại.

**❓ AI hay lỗi, hoặc báo hết lượt**
Gói AI miễn phí có giới hạn theo ngày. Bot tự chuyển sang luật dự phòng (mục 9); sáng hôm sau AI tự hồi phục. `/status` cho biết AI đang dùng được hay không.

**❓ Mail công ty báo sai mật khẩu / không kết nối được**
Kiểm tra `COMPANY_MAIL_PASSWORD` (secrets.env) và `company_mail_host` (settings.json), rồi chạy `python company_mailer.py --check`. Cần gửi gấp → `/personalmailon` gửi bằng Gmail.

**❓ Kiểm tra lịch tự động có chạy không**
Xem mục **3b** (Windows: Task Scheduler · Mac: `launchctl list | grep timesheet`). Windows, cách nhanh bằng lệnh — mở `cmd` và gõ:
```
schtasks /Create /TN "Timesheet Bot" /TR "wscript.exe \"C:\timesheet\start_bot.vbs\"" /SC DAILY /ST 16:00 /F
schtasks /Create /TN "Timesheet Weekly" /TR "wscript.exe \"C:\timesheet\run_weekly.vbs\"" /SC WEEKLY /D FRI /ST 17:00 /F
```
(đổi `C:\timesheet` nếu bạn cài ở chỗ khác).

**❓ Muốn biết bot đã làm gì**
`C:\timesheet\data\audit.log` ghi mọi việc quan trọng (bật/tắt bot, ghi, gửi mail...). Nhật ký kỹ thuật chi tiết trong `data\logs\`.

---

## 13. Bảo mật — điều tuyệt đối không làm

- ❌ **Không** gửi / chụp màn hình / đưa lên mạng file `config\secrets.env`.
- ❌ **Không** chia sẻ TOKEN bot, API key, mật khẩu cho bất kỳ ai (kể cả người chia sẻ bot).
- ❌ **Không** đưa thư mục `C:\timesheet` (có dữ liệu của bạn) lên GitHub.
- ❌ Kho GitHub của bot để **công khai (public)** — **ai cũng xem được**. Tuyệt đối **không** đưa lên GitHub (kể cả trong comment, issue, ảnh chụp, hay file cấu hình): **email sếp**, **email công ty** của bạn, **`company_mail_host`** (địa chỉ server mail công ty), cùng mọi nội dung `settings.json` / `secrets.env` thật. Muốn góp ý / báo lỗi trên GitHub → che hết các thông tin này trước.
- ✅ Lỡ để lộ TOKEN → vào @BotFather gõ `/revoke` để đổi token mới, dán vào secrets.env, khởi động lại bot.
- ✅ Lỡ để lộ API key → xóa key cũ ở https://aistudio.google.com/apikey, tạo key mới.

---

## 14. Cập nhật phiên bản mới

Khi có bản mới trên GitHub:
1. Tải ZIP mới (Bước 2), giải nén ra thư mục tạm **mới**.
2. Chép **file** mới (bước 3) trước, rồi ở bước 5 dùng `restart_bot` để tắt + bật lại (không cần tắt tay).
3. Chép **đè** các file trong `src\` của bản mới vào `C:\timesheet\src\` (🍎 Mac: `~/timesheet/src/`).
   ⚠️ **Chỉ** chép thư mục `src\` — **không** đè `config\`, `data\`, `output\` (dữ liệu và cấu hình của bạn).
   (Không dùng `CAI_DAT.bat` để cập nhật — nó sẽ dừng lại vì thấy bot đã cài, để bảo vệ dữ liệu của bạn.)
4. Kiểm tra: `cd /d C:\timesheet\src` → `python selfcheck.py` (🍎 Mac: `cd ~/timesheet/src` → `../.venv/bin/python selfcheck.py`).
5. Nhấp đúp `restart_bot.bat` (🍎 `restart_bot.command`) — tắt bot cũ, bật bot mới.

---

## 15. Bot có nặng máy không?

**Kết quả đo thực tế** trên laptop Windows **Intel Core i5-6300U, RAM 8 GB**, trong lúc **đang dùng bot bình thường** (có nhắn **nhiều tin** cho bot trong lúc đo, đo 1 phút):

```
PID 4008  - đang nằm trong RAM  12 MB - bot đã dùng tổng cộng   6 MB
PID 19072 - đang nằm trong RAM 101 MB - bot đã dùng tổng cộng 189 MB
Bot PID 19072 - RAM 96 MB - CPU trung bình 1 phút 0.06%
```

**Ý nghĩa từng thông số:**

| Thông số | Nghĩa |
|---|---|
| **PID** | Số hiệu Windows đặt cho mỗi chương trình đang chạy. Có **2 PID** cho 1 bot: **4008** là **tiến trình mồi** (chỉ để khởi động Python, rất nhỏ), **19072** là **bot thật** |
| **Đang nằm trong RAM** | Phần bộ nhớ **thật sự chiếm RAM** lúc đo. Bot thật: **~100 MB** ≈ **1,2% RAM 8 GB** |
| **Đã dùng tổng cộng** | Toàn bộ bộ nhớ bot đã **xin** (kể cả phần chưa cần, Windows để tạm ra ngoài RAM). Con số này lớn hơn nhưng **không chiếm RAM thật** toàn bộ. (Tiến trình mồi có "tổng" nhỏ hơn "trong RAM" vì phần lớn là thư viện hệ thống **dùng chung** với chương trình khác) |
| **CPU trung bình 1 phút** | Phần sức xử lý bot dùng: **0,06%** — gần như **không dùng gì** |

**So với ứng dụng quen thuộc** (mức thường gặp, tùy máy):

| Ứng dụng | RAM | CPU lúc để yên |
|---|---|---|
| Notepad | ~5–15 MB | 0% |
| Calculator | ~20–40 MB | 0% |
| **Bot timesheet** (đang dùng, có nhắn tin) | **~100 MB** | **~0,06%** (trung bình 1 phút) |
| Word / Excel (mở 1 file trống) | ~100–200 MB | ~0–1% |
| Microsoft Teams | ~300–800 MB | vài % |
| Chrome (vài tab) | ~500 MB – 1,5 GB | vài % |

→ Bot nhẹ **ngang việc để mở 1 file Word / Excel trống**, nhẹ hơn nhiều so với Teams hay Chrome. Chạy cả buổi chiều không làm máy chậm.

**Lưu ý:** số đo trên là lúc **đang nhắn tin dùng bot** (gồm cả lúc bot gọi AI, ghi Excel) mà CPU trung bình vẫn chỉ **0,06%**. Khi **không ai nhắn** (chế độ chờ), bot còn **nhẹ hơn nữa**: CPU gần như 0%, RAM có thể còn thấp hơn vì Windows tạm cất bớt phần chưa dùng. Mỗi lần bạn nhắn (gọi AI, ghi Excel, gửi mail) RAM / CPU chỉ **nhích lên 1–2 giây** rồi trở lại — phần lớn thời gian đó là **chờ AI / mạng trả lời**, không tốn sức máy. Chương trình chốt tuần thứ 6 (`weekly_run.py`) chỉ chạy **vài giây** rồi thoát.

**Tự đo trên máy bạn** (khi bot đang chạy) — mở `cmd`, dán lệnh, chờ 60 giây:
```
powershell -NoProfile -Command "$p = Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*\src\bot.py*' } | ForEach-Object { Get-Process -Id $_.ProcessId } | Sort-Object WorkingSet64 -Descending | Select-Object -First 1; $c1 = $p.CPU; Start-Sleep 60; $p.Refresh(); 'Bot PID {0} - RAM {1:N0} MB - CPU trung binh 1 phut {2:N2}%' -f $p.Id, ($p.WorkingSet64/1MB), (($p.CPU-$c1)/60/[Environment]::ProcessorCount*100)"
```

