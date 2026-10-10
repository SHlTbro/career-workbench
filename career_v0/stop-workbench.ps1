param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 18380
)

# Career Workbench STOP：基于端口直查，不依赖 PID 文件或父进程链。
# 验收：18380 不再 LISTENING 才算 PASS。
$ErrorActionPreference = 'Stop'
# 与 start-workbench.ps1 中 $dshPath 保持一致的 DSH 内核路径
$dshPath = '<YOUR_DSH_RUNTIME>\node_modules\@deepseek-ai\dsh\lib\bin.js'

function Get-PortListenerPids([int]$PortNumber) {
    return @(Get-NetTCPConnection -LocalPort $PortNumber -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
}

function Test-IsCareerDshNode([int]$ProcessId) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if (-not $proc -or $proc.Name -ne 'node.exe') { return $false }
    $cmd = [string]$proc.CommandLine
    return ($cmd.IndexOf($dshPath, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and $cmd -match '(?i)--profile\s+web' -and $cmd -match ('(?i)--port\s+' + [regex]::Escape([string]$Port) + '(?:\s|$)'))
}

$listenerPids = Get-PortListenerPids $Port
if ($listenerPids.Count -eq 0) {
    Write-Host "STOP PASS：端口 $Port 当前无监听，Career 服务未在运行。" -ForegroundColor Green
    return
}

foreach ($listenerId in $listenerPids) {
    if (-not (Test-IsCareerDshNode ([int]$listenerId))) {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $listenerId" -ErrorAction SilentlyContinue
        $desc = if ($proc) { "$($proc.Name) PID $listenerId" } else { "PID $listenerId（进程已退出但连接未释放）" }
        throw "STOP FAIL：端口 $Port 的占用者 $desc 不是本项目 DSH Web 进程，为避免误停未结束它。"
    }
}

foreach ($listenerId in $listenerPids) {
    Write-Host "结束本项目 DSH Web 进程树（node PID $listenerId）..."
    & (Join-Path $env:SystemRoot 'System32\taskkill.exe') /PID $listenerId /T /F | Out-Null
}

$deadline = (Get-Date).AddSeconds(15)
while ((Get-Date) -lt $deadline) {
    if ((Get-PortListenerPids $Port).Count -eq 0) {
        Write-Host "STOP PASS：端口 $Port 已释放，Career 前后端已停止。" -ForegroundColor Green
        return
    }
    Start-Sleep -Milliseconds 250
}
throw "STOP FAIL：已发送停止命令，但 15 秒后端口 $Port 仍在监听。"
