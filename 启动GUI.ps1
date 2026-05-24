# 自动定位项目根目录（脚本所在目录）
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

# 检查 Python 是否可用
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "[错误] 未找到 Python，请先安装 Python 3.10+" -ForegroundColor Red
    Read-Host "按回车键退出"
    exit 1
}

# 启动 GUI
Write-Host "正在启动 NovalPie GUI..." -ForegroundColor Cyan
python -m novalpie.gui

# 如果启动失败，显示错误信息
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[错误] GUI 启动失败，请检查：" -ForegroundColor Red
    Write-Host "  1. 是否已安装依赖：pip install -e ." -ForegroundColor Yellow
    Write-Host "  2. 是否已安装浏览器：playwright install chromium" -ForegroundColor Yellow
    Read-Host "按回车键退出"
}
