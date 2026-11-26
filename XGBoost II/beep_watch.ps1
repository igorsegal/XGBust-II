$f = "D:\AHexaTrader\XGBoost-edge-git\READY.txt"
while ($true) {
  if (Test-Path $f) {
    [console]::Beep(1000,500)
    Remove-Item $f -Force -ErrorAction SilentlyContinue
  }
  Start-Sleep -Seconds 2
}
