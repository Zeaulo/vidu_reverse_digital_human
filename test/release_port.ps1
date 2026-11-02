# 强制释放指定的 TCP 监听端口，供启动脚本和隔离测试共用。
function Clear-ListeningPort {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port # 需要释放的 TCP 端口。
    )
    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) # 当前监听进程。
    $processIds = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique) # 一个进程可能同时监听 IPv4 和 IPv6。
    foreach ($processId in $processIds) { # 按进程去重，避免重复结束。
        if ($processId -le 4 -or $processId -eq $PID) {
            throw "端口 $Port 由系统或当前启动进程占用，无法安全释放（PID：$processId）。"
        }
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue # 获取占用进程名称。
        if ($process) {
            Write-Host "正在强制结束占用端口 ${Port} 的进程：$($process.ProcessName)（PID：$processId）"
            try { Stop-Process -Id $processId -Force -ErrorAction Stop }
            catch { throw "无法结束占用端口 ${Port} 的进程（PID：$processId）：$($_.Exception.Message)" }
        }
    }
    for ($attempt = 0; $attempt -lt 20; $attempt++) { # 最多等待十秒让监听端口释放。
        if (-not (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) {
            if ($processIds.Count -gt 0) { Write-Host "端口 $Port 已释放。" }
            return
        }
        Start-Sleep -Milliseconds 500
    }
    throw "端口 $Port 仍被占用，请检查进程权限或端口状态后重试。"
}
