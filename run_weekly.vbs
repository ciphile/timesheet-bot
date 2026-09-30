' run_weekly.vbs - Chay job chot timesheet thu 6 (weekly_run.py), an cua so.
' Tu tim thu muc chua file nay -> cai o o dia nao cung chay.
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = base & "\src"
sh.Run "python.exe """ & base & "\src\weekly_run.py""", 0, False
