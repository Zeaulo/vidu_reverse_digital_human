# 在临时端口创建独立监听进程，验证强制释放功能。
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'release_port.ps1')
$probe = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0) # 由系统分配可用端口。
$probe.Start()
$port = $probe.LocalEndpoint.Port
$probe.Stop()
$listenerScript = Join-Path $PSScriptRoot 'port_listener.ps1' # 测试专用监听器。
$child = Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $listenerScript + '"'), "$port") -WindowStyle Hidden -PassThru # 监听器的进程号与启动进程一致。
try {
    $found = $false # 是否已观察到测试监听。
    for ($attempt = 0; $attempt -lt 30; $attempt++) { # 等待测试进程开始监听。
        $listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
        if (@($listeners | Where-Object { $_.OwningProcess -eq $child.Id }).Count -gt 0) { $found = $true; break }
        Start-Sleep -Milliseconds 200
    }
    if (-not $found) { throw '测试监听进程未能启动。' }
    Clear-ListeningPort -Port $port
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) { throw '测试端口仍被监听。' }
    Clear-ListeningPort -Port $port # 端口已空闲时也应成功。
    Write-Host '端口释放测试通过。'
} finally {
    if (-not $child.HasExited) { Stop-Process -Id $child.Id -Force -ErrorAction SilentlyContinue } # 只清理测试创建的进程。
}
