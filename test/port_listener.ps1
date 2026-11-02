# 测试专用监听器，供端口释放测试创建和终止。
param([int]$Port)
$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port) # 独立测试端口。
$listener.Start()
try { while ($true) { Start-Sleep -Seconds 1 } } # 保持监听直到测试结束。
finally { $listener.Stop() }
