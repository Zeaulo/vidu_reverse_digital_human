# 从项目根目录启动访客采集器和 Studio，所有运行脚本集中在 test。
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot # 根据脚本位置确定根目录。
Set-Location -LiteralPath $projectRoot
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe' # 固定使用项目虚拟环境，避免误用系统 Python。
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw '未找到 .venv 虚拟环境，请先在项目根目录执行 python -m venv .venv 并安装 requirements.txt。'
}
$collectorPath = Join-Path $projectRoot 'test/tools/douyin/douyinLive.exe' # 已验证的官方发布包。
$collectorConfig = Join-Path $projectRoot 'test/tools/douyin/config.yaml' # 不含登录 Cookie 的访客配置。
if (-not (Test-Path -LiteralPath $collectorPath)) {
    throw '请先按 README 下载并校验 douyinLive v2.3.2 到 test/tools/douyin。'
}
if (-not (Test-Path -LiteralPath $collectorConfig)) {
    throw '未找到采集器配置文件，请按 README 配置 test/tools/douyin/config.yaml。'
}
. (Join-Path $PSScriptRoot 'release_port.ps1') # 加载端口释放函数。
Clear-ListeningPort -Port 8795 # 启动前强制清除 Studio 端口的监听进程。
if (-not (Get-NetTCPConnection -LocalPort 1088 -State Listen -ErrorAction SilentlyContinue)) {
    # 后台采集服务不弹终端，Vidu Chrome 由用户明确选择有头运行。
    Start-Process -FilePath $collectorPath -ArgumentList @('--config', ('"' + $collectorConfig + '"')) -WorkingDirectory $projectRoot -WindowStyle Hidden
}
& $pythonPath -m uvicorn app.main:app --host 127.0.0.1 --port 8795
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } # 将服务启动失败状态传递给双击入口。
