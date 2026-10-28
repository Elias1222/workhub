# 开发用重启脚本（Windows）：杀掉旧的 WorkHub 进程再起一个新的。
# 直接用 Start-Process 起新的而不杀旧的，端口会被旧进程占着 —— 新代码根本不生效，
# 表现就是"改了没变化 / 探测还是错"。在仓库根目录执行：
#   powershell -ExecutionPolicy Bypass -File scripts\restart.ps1
param(
    [int]$Port = 8770,
    [string]$Python = "pythonw.exe"
)
$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like '*-m workhub*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

Start-Sleep -Milliseconds 800
Start-Process $Python -ArgumentList '-m', 'workhub', '--port', "$Port" `
    -WorkingDirectory $root -WindowStyle Hidden
Start-Sleep -Seconds 2

try {
    $r = Invoke-RestMethod "http://127.0.0.1:$Port/api/ping" -TimeoutSec 5
    Write-Host "WorkHub 已重启：PID $($r.pid)  启动于 $($r.started)"
    Write-Host "打开：http://127.0.0.1:$Port/"
} catch {
    Write-Host "启动失败：$Port 没响应。前台跑 python -m workhub 看报错。"
}
