param(
    [string]$Version = '0.3.0',
    [string]$OutputDirectory = '',
    [string]$SeedPath = '.runtime/release/seed.db',
    [switch]$SkipBackendBuild,
    [switch]$SkipSeed,
    [switch]$NoArchive
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $projectRoot
$python = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not $OutputDirectory) { $OutputDirectory = "release/Wangzha-$Version-win-x64" }
$output = [IO.Path]::GetFullPath((Join-Path $projectRoot $OutputDirectory))
if (Test-Path -LiteralPath $output) { throw "输出目录已存在，请使用新目录：$output" }
$electron = Join-Path $projectRoot 'desktop/node_modules/electron/dist'
if (-not (Test-Path -LiteralPath (Join-Path $electron 'electron.exe'))) { throw '请先在desktop执行npm ci' }
if (-not $SkipBackendBuild) {
    Push-Location (Join-Path $projectRoot 'frontend')
    try { & npm.cmd run build; if ($LASTEXITCODE -ne 0) { throw '前端构建失败' } } finally { Pop-Location }
    $arguments = @('-m','PyInstaller','--noconfirm','--clean','--name','wangzha-backend',
        '--distpath','.runtime/release/backend-dist','--workpath','.runtime/release/backend-build',
        '--specpath','.runtime/release','--paths',$projectRoot,'--add-data',"$projectRoot/frontend/dist;frontend/dist",
        '--collect-all','pypinyin','--collect-all','uvicorn','--hidden-import','baostock','desktop/backend_entry.py')
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw '内置服务构建失败' }
}
$backend = Join-Path $projectRoot '.runtime/release/backend-dist/wangzha-backend'
if (-not (Test-Path -LiteralPath (Join-Path $backend 'wangzha-backend.exe'))) { throw '缺少内置服务，请重新构建' }
New-Item -ItemType Directory -Path $output | Out-Null
Copy-Item -Path (Join-Path $electron '*') -Destination $output -Recurse
Rename-Item -LiteralPath (Join-Path $output 'electron.exe') -NewName '王炸.exe'
& node (Join-Path $projectRoot 'desktop/stamp.cjs') (Join-Path $output '王炸.exe') $Version
if ($LASTEXITCODE -ne 0) { throw '客户端图标/版本资源写入失败' }
$resources = Join-Path $output 'resources'
$appDirectory = Join-Path $resources 'app'
New-Item -ItemType Directory -Path $appDirectory | Out-Null
foreach ($file in @('main.cjs','preload.cjs','url-policy.cjs','storage.cjs','tooltip.html','startup.html','startup.cjs','startup-preload.cjs','icon.ico')) {
    Copy-Item -LiteralPath (Join-Path $projectRoot "desktop/$file") -Destination $appDirectory
}
@{ name='wangzha-desktop';version=$Version;main='main.cjs';description='王炸股票研究客户端' } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $appDirectory 'package.json') -Encoding utf8
Copy-Item -LiteralPath $backend -Destination (Join-Path $resources 'backend') -Recurse
Copy-Item -LiteralPath (Join-Path $projectRoot 'docs/THIRD-PARTY-NOTICES.md') -Destination $output
Copy-Item -LiteralPath (Join-Path $projectRoot 'desktop/使用说明.txt') -Destination $output
Copy-Item -LiteralPath (Join-Path $projectRoot 'desktop/配置模型示例.cmd') -Destination $output
& $python -m scripts.collect_licenses (Join-Path $output 'licenses/python')
if ($LASTEXITCODE -ne 0) { throw '依赖许可收集失败' }
if (-not $SkipSeed) {
    $seed = [IO.Path]::GetFullPath((Join-Path $projectRoot $SeedPath))
    if (-not (Test-Path -LiteralPath $seed)) { throw '缺少发行行情数据库' }
    & $python -m scripts.release_manifest --database $seed --destination (Join-Path $resources 'seed.db') --manifest (Join-Path $output 'history-manifest.json')
    if ($LASTEXITCODE -ne 0) { throw '发行数据核验失败' }
}
if (-not $NoArchive) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = "$output.zip"
    [IO.Compression.ZipFile]::CreateFromDirectory($output,$archive,[IO.Compression.CompressionLevel]::Optimal,$true)
    $hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $([IO.Path]::GetFileName($archive))" | Set-Content -LiteralPath "$archive.sha256" -Encoding ascii
    Write-Output $archive
}
Write-Output $output
