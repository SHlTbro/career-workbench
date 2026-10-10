param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 18380,
    [string]$StateDir = (Join-Path $env:USERPROFILE 'career-v0-state'),
    [switch]$NoOpen
)
# ── 按你的机器填写以下常量（README「安装」第 4 步）──────────────────────
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$masterPath = '<YOUR_MASTER_RESUME_PATH>'
$dshPath = '<YOUR_DSH_RUNTIME>\node_modules\@deepseek-ai\dsh\lib\bin.js'
$pythonPath = '<YOUR_PYTHON_EXE>'
$webProfile = '<YOUR_DSH_WEB_PROFILE>\package.json'
$env:DSH_HOME = '<YOUR_DSH_HOME>'
$env:CAREER_DSH_BIN = '<YOUR_DSH_RUNTIME>\node_modules\.bin\dsh.cmd'
# ──────────────────────────────────────────────────────────────

# Career Workbench START：
#   1. 若 18380 被本项目旧实例占用，端口直查验证后停止
#   2. 后台启动 DSH Web（含 career-v0-web-plugin），stdout/stderr 落盘
#   3. 从 DSH 官方启动输出解析本次 authenticated URL（dsh web: <url>?token=...）
#   4. 验证端口监听 + HTTP 认证应答（200/303）
#   5. 默认浏览器打开 authenticated 工作台，并清晰打印 URL
$ErrorActionPreference = 'Stop'
# Windows PowerShell 5.1 默认不加载 System.Net.Http；不预载则
# [Net.Http.HttpClientHandler]::new() 抛"找不到类型"，HTTP 自检永远失败。
Add-Type -AssemblyName System.Net.Http
$nodeCandidates = @(
    'C:\Program Files\nodejs\node.exe'
)
if (Get-Command node.exe -ErrorAction SilentlyContinue) {
    $nodeCandidates += (Get-Command node.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
}
$nodePath = $null
$nodeVersion = $null
foreach ($candidate in $nodeCandidates | Select-Object -Unique) {
    if (-not (Test-Path -LiteralPath $candidate)) { continue }
    $versionText = (& $candidate --version 2>$null | Select-Object -First 1).Trim().TrimStart('v')
    $parsedVersion = $null
    if (-not [version]::TryParse($versionText, [ref]$parsedVersion)) { continue }
    $supported = ($parsedVersion.Major -eq 22 -and $parsedVersion -ge [version]'22.19.0') -or $parsedVersion.Major -ge 24
    if ($supported) {
        $nodePath = $candidate
        $nodeVersion = $versionText
        break
    }
}
if (-not $nodePath) {
    throw 'Career web plugins require Node.js 22.19+ or 24+. The prior pinned 22.18 runtime is unsupported; install a compatible Node.js version or add it to PATH.'
}

function Get-PortListenerPids([int]$PortNumber) {
    return @(Get-NetTCPConnection -LocalPort $PortNumber -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
}

function Test-IsCareerDshNode([int]$ProcessId) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if (-not $proc -or $proc.Name -ne 'node.exe') { return $false }
    $cmd = [string]$proc.CommandLine
    return ($cmd.IndexOf($dshPath, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and $cmd -match '(?i)--profile\s+web' -and $cmd -match ('(?i)--port\s+' + [regex]::Escape([string]$Port) + '(?:\s|$)'))
}

function Stop-ExistingCareerInstance {
    $listenerPids = Get-PortListenerPids $Port
    if ($listenerPids.Count -eq 0) { return }
    foreach ($listenerId in $listenerPids) {
        if (-not (Test-IsCareerDshNode ([int]$listenerId))) {
            $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $listenerId" -ErrorAction SilentlyContinue
            $desc = if ($proc) { "$($proc.Name) PID $listenerId" } else { "PID $listenerId" }
            throw "端口 $Port 被 $desc 占用，且不是本项目 DSH Web 进程；为避免误停未结束它。"
        }
    }
    foreach ($listenerId in $listenerPids) {
        Write-Host "检测到本项目旧实例（node PID $listenerId），先停止以释放端口..." -ForegroundColor Yellow
        & (Join-Path $env:SystemRoot 'System32\taskkill.exe') /PID $listenerId /T /F | Out-Null
    }
    $deadline = (Get-Date).AddSeconds(15)
    while ((Get-Date) -lt $deadline) {
        if ((Get-PortListenerPids $Port).Count -eq 0) { return }
        Start-Sleep -Milliseconds 250
    }
    throw "旧实例 15 秒内未释放端口 $Port。"
}

function Get-LastAuthenticatedUrlFromLog([string]$LogPath) {
    if (-not (Test-Path -LiteralPath $LogPath)) { return $null }
    # DSH 启动早期可能重派生进程并打印新的 token，因此只认最后一条。
    $match = Select-String -LiteralPath $LogPath -Pattern 'dsh web:\s+(http://[^\s]+)' -ErrorAction SilentlyContinue | Select-Object -Last 1
    if ($match) { return $match.Matches[0].Groups[1].Value }
    return $null
}

function Test-AuthenticatedUrl([string]$Url) {
    # 303 = token 换 cookie 成功；200 = 已认证；401 = token 属于已退出的旧进程。
    # UseProxy=false：本机有系统代理时 HttpClient 会把 127.0.0.1 也路由进代理导致误判。
    try {
        $handler = [Net.Http.HttpClientHandler]::new()
        $handler.AllowAutoRedirect = $false
        $handler.UseProxy = $false
        $client = [Net.Http.HttpClient]::new($handler)
        $client.Timeout = [TimeSpan]::FromSeconds(10)
        $resp = $client.GetAsync($Url).GetAwaiter().GetResult()
        $code = [int]$resp.StatusCode
        $client.Dispose()
        return ($code -eq 200 -or $code -eq 303)
    } catch { return $false }
}

foreach ($required in @($projectRoot, $masterPath, $nodePath, $dshPath, $pythonPath, $webProfile)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Career V-0 startup requirement missing: $required"
    }
}

$profile = Get-Content -LiteralPath $webProfile -Raw | ConvertFrom-Json
if ('career-v0-web-plugin' -notin $profile.dsh.profile.bundles) {
    throw 'Career Web plugin is not enabled in the DSH Web profile.'
}

Stop-ExistingCareerInstance

$env:CAREER_STATE_DIR = $StateDir
$env:CAREER_MASTER_PATH = $masterPath
$env:CAREER_PROJECT_ROOT = $projectRoot
$env:CAREER_PYTHON = $pythonPath
$env:CAREER_NODE_BIN = $nodePath

$logDir = Join-Path $StateDir 'logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$outLog = Join-Path $logDir 'dsh-web-last.out.log'
$errLog = Join-Path $logDir 'dsh-web-last.err.log'
$urlFile = Join-Path $logDir 'workbench-url.txt'

Write-Host "启动 DSH Web（Node $nodeVersion，--profile web --port $Port，含 career-v0-web-plugin）..."
$dshProc = Start-Process -FilePath $nodePath -ArgumentList @('"' + $dshPath + '"', '--profile', 'web', '--no-open', '--port', [string]$Port) -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru
Write-Host "node PID：$($dshProc.Id)"
Write-Host "日志：$outLog"

# 等待“当前存活进程”的认证 URL：
# DSH 启动早期可能重派生进程（旧 token 随旧进程失效），所以循环里反复取日志最后一条 URL
# 并直接做 HTTP 认证验证，只有 200/303 才算数；期间进程树重启不会误判。
$authenticatedUrl = $null
$candidate = $null
$deadline = (Get-Date).AddSeconds(150)
while ((Get-Date) -lt $deadline) {
    $listenerPids = Get-PortListenerPids $Port
    $candidate = Get-LastAuthenticatedUrlFromLog $outLog
    if ($candidate -and $listenerPids.Count -gt 0 -and (Test-AuthenticatedUrl $candidate)) {
        $authenticatedUrl = $candidate
        break
    }
    if ($listenerPids.Count -eq 0 -and $dshProc.HasExited -and -not $candidate) {
        throw "DSH Web 进程提前退出（exit code $($dshProc.ExitCode)）。错误日志：$errLog"
    }
    Start-Sleep -Milliseconds 1000
}
if (-not $authenticatedUrl) {
    throw "150 秒内未获得通过 HTTP 验证的认证 URL。最后候选：$candidate；日志：$outLog / $errLog"
}

# 稳定性复验：4 秒后同 URL 仍 200/303，排除刚好落在进程重派生间隙。
Start-Sleep -Seconds 4
if (-not (Test-AuthenticatedUrl $authenticatedUrl)) {
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        $candidate = Get-LastAuthenticatedUrlFromLog $outLog
        if ($candidate -and (Test-AuthenticatedUrl $candidate)) { $authenticatedUrl = $candidate; break }
        Start-Sleep -Milliseconds 1000
    }
    if (-not (Test-AuthenticatedUrl $authenticatedUrl)) {
        throw "认证 URL 在复验中失效且未能恢复。日志：$outLog / $errLog"
    }
}

$authenticatedUrl | Set-Content -LiteralPath $urlFile -Encoding UTF8
Write-Host ''
Write-Host '================ Career 工作台已就绪 ================' -ForegroundColor Green
Write-Host '本次认证 URL（勿手抄 token，直接用下面链接或自动打开）：' -ForegroundColor Green
Write-Host "  $authenticatedUrl" -ForegroundColor Cyan
Write-Host "URL 已保存：$urlFile"
Write-Host 'HTTP 认证验证（200/303）：PASS'

if (-not $NoOpen) {
    Start-Process $authenticatedUrl
    Write-Host '已在默认浏览器打开认证工作台。' -ForegroundColor Green
}

Write-Host ''
Write-Host '说明：关闭本窗口不会停止服务；停止请双击 Career-Workbench-停止.cmd。'
Write-Host 'G0/G1/G2/G3 需要你本人在网页里操作。'
