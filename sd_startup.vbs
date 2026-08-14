Set WshShell = CreateObject("WScript.Shell")
' start Stable Diffusion WebUI (--api 7860)
WshShell.Run "cmd /c cd /d E:\sd-forge && webui-user.bat", 0, False
' start tunnel daemon (server 17860 -> local 7860)
WshShell.Run """E:\python\pythonw.exe"" ""E:\qq-bili-bot\local_draw_daemon.py""", 0, False
