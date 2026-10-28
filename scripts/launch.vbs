' WorkHub 静默启动（Windows）：后台起服务并打开浏览器，不留黑窗。
' 用法：双击本文件，或把它做成桌面快捷方式（目标填 wscript.exe "<路径>\launch.vbs"）。
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
sh.CurrentDirectory = root
sh.Run "pythonw.exe -m workhub --open", 0, False
