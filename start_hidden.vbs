Option Explicit
Dim shell, fso, folder, python, script
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
python = fso.BuildPath(folder, ".venv\Scripts\pythonw.exe")
script = fso.BuildPath(folder, "server.py")
shell.CurrentDirectory = folder
shell.Run Chr(34) & python & Chr(34) & " " & Chr(34) & script & Chr(34), 0, False
