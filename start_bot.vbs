' start_bot.vbs - Khoi dong bot Telegram (an cua so den).
' Tu tim thu muc chua file nay -> cai o o dia nao cung chay.
' Dung python.exe (co console) nhung an cua so (0 = hidden):
' pythonw.exe lam asyncio tren Windows chet ngam.
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = base & "\src"
sh.Run "python.exe """ & base & "\src\bot.py""", 0, False
