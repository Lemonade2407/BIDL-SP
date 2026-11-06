#requires -Version 5.1
<#
.SYNOPSIS
    BIDL-SP 一键启动：生成环境变量、构建前端、构建并启动 Docker Compose。

.DESCRIPTION
    在仓库根目录或 deploy 目录执行均可。脚本会自行定位仓库根，不依赖当前工作目录。

.EXAMPLE
    .\start.ps1
    .\start.ps1 -SkipFrontend
    .\start.ps1 -NoDemo
    .\start.ps1 -ModelRoot D:\BIDL-assets
    .\start.ps1 -DatasetDir D:\Dataset_BUSI_with_GT
    .\start.ps1 -Down
#>
[CmdletBinding()]
param(
    [switch]$SkipFrontend,
    [switch]$Build,
    [switch]$NoDemo,
    [switch]$Down,
    [switch]$WithMinio,
    [string]$ModelRoot = "",
    [string]$DatasetDir = ""
)

$ErrorActionPreference = "Stop"

# ---------- 路径定位 ----------
$DeployDir = $PSScriptRoot
$RepoRoot = Split-Path -Parent $DeployDir
$EnvFile = Join-Path $DeployDir ".env"
$ComposeFile = Join-Path $DeployDir "docker-compose.yml"
$ComposeProfile = @()
if ($WithMinio) {
    $ComposeProfile = @("--profile", "minio")
}

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok([string]$Message) {
    Write-Host "    $Message" -ForegroundColor Green
}

function Write-Warn([string]$Message) {
    Write-Host "    $Message" -ForegroundColor Yellow
}

function Require-Command([string]$Name, [string]$Hint) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "缺少命令: $Name。$Hint"
    }
}

function Invoke-Compose {
    param([string[]]$ComposeArgs)
    & docker compose --env-file $EnvFile -f $ComposeFile @ComposeProfile @ComposeArgs
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose 执行失败（退出码 $LASTEXITCODE）：$($ComposeArgs -join ' ')"
    }
}

function Show-Diagnostics {
    Write-Warn "最近 40 行服务日志："
    & docker compose --env-file $EnvFile -f $ComposeFile @ComposeProfile logs --tail 40 init api worker 2>&1 | ForEach-Object { Write-Host "    $_" }
    Write-Host ""
    Write-Host "常用排查命令：" -ForegroundColor Yellow
    Write-Host "  docker compose --env-file deploy/.env -f deploy/docker-compose.yml ps"
    Write-Host "  docker compose --env-file deploy/.env -f deploy/docker-compose.yml logs --tail 100 api worker"
}

try {
    # ---------- 0. 环境自检 ----------
    Write-Step "环境检查"
    if (-not (Test-Path (Join-Path $RepoRoot "backend/app/main.py"))) {
        throw "未找到仓库根（$RepoRoot）。请把 start.ps1 放在仓库根目录或 deploy 目录下。"
    }
    if (-not (Test-Path $ComposeFile)) {
        throw "未找到 $ComposeFile"
    }
    Require-Command "docker" "请安装 Docker Desktop 并确保 docker 在 PATH 中。"
    Require-Command "python" "请安装 Python 3.11+ 并勾选 Add to PATH。"
    if (-not $SkipFrontend) {
        Require-Command "npm" "请安装 Node.js 20+ 并确保 npm 在 PATH 中。"
    }

    & docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker 守护进程未运行，请先启动 Docker Desktop。"
    }
    & docker compose version *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "当前 Docker 未提供 compose v2 插件，请升级 Docker Desktop。"
    }
    Write-Ok "docker / python$(if (-not $SkipFrontend) { ' / npm' }) 就绪"

    # ---------- 1. 停止 ----------
    if ($Down) {
        Write-Step "停止并移除容器"
        Invoke-Compose -ComposeArgs @("down")
        Write-Ok "已停止。数据卷保留，如需清空：docker compose --env-file deploy/.env -f deploy/docker-compose.yml down -v"
        return
    }

    # ---------- 2. 生成 .env ----------
    Write-Step "准备 deploy/.env"
    if (Test-Path $EnvFile) {
        Write-Ok "已存在，保持不变（不会打印任何密钥）"
    } else {
        & python (Join-Path $DeployDir "generate_env.py")
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $EnvFile)) {
            throw "生成 deploy/.env 失败。"
        }
        Write-Ok "已生成。管理员演示账号：admin / DemoPassword!123"
    }

    # 对象存储：默认本地共享卷；-WithMinio 时切到 MinIO
    $envContent = Get-Content $EnvFile -Raw
    if ($WithMinio) {
        if ($envContent -match "(?m)^STORAGE_BACKEND=minio\s*$") {
            Write-Ok "对象存储：MinIO"
        } else {
            if ($envContent -match "(?m)^STORAGE_BACKEND=") {
                $envContent = $envContent -replace "(?m)^STORAGE_BACKEND=.*$", "STORAGE_BACKEND=minio"
            } else {
                $envContent = $envContent.TrimEnd() + "`nSTORAGE_BACKEND=minio`n"
            }
            Set-Content -Path $EnvFile -Value $envContent -NoNewline
            Write-Ok "已将 .env 的 STORAGE_BACKEND 设为 minio"
        }
    } elseif ($envContent -match "(?m)^STORAGE_BACKEND=minio\s*$") {
        throw "deploy/.env 使用 MinIO 对象存储，请加 -WithMinio 重新运行。"
    } else {
        Write-Ok "对象存储：本地共享卷"
    }

    # ---------- 3. 构建前端 ----------
    if ($SkipFrontend) {
        Write-Step "构建前端（已跳过）"
    } else {
        Write-Step "构建前端并同步到 deploy/html"
        $frontendArgs = @()
        if (Test-Path (Join-Path $RepoRoot "frontend/node_modules")) {
            $frontendArgs += "--skip-install"
            Write-Ok "复用已有 node_modules"
        }
        & python (Join-Path $DeployDir "build_frontend.py") @frontendArgs
        if ($LASTEXITCODE -ne 0) {
            throw "前端构建失败。可先手动执行：cd frontend; npm install; npm run build"
        }
        Write-Ok "前端产物已就绪（源码无变化时自动复用）"
    }

    # ---------- 4. 构建并启动 ----------
    $requiredImages = @(
        "bidlsp-init:latest",
        "bidlsp-api:latest",
        "bidlsp-worker:latest",
        "bidlsp-scheduler:latest",
        "bidlsp-dispatcher:latest"
    )
    $missing = @()
    foreach ($image in $requiredImages) {
        & docker image inspect $image *> $null
        if ($LASTEXITCODE -ne 0) { $missing += $image }
    }
    $doBuild = $Build -or ($missing.Count -gt 0)

    if ($doBuild) {
        $reason = if ($Build) { "指定了 -Build" } else { "缺少镜像: $($missing -join ', ')" }
        Write-Step "构建镜像并启动服务（$reason；首次构建需下载依赖）"
    } else {
        Write-Step "启动服务（镜像已存在，跳过构建；需要重建请加 -Build）"
    }

    $upArgs = @("up", "-d")
    if ($doBuild) { $upArgs += "--build" }
    $upArgs += @("--wait", "--wait-timeout", "300")
    try {
        Invoke-Compose -ComposeArgs $upArgs
    } catch {
        Show-Diagnostics
        throw
    }
    Write-Ok "容器已启动"

    # ---------- 5. 等待 API 就绪 ----------
    Write-Step "等待 API 就绪"
    $deadline = (Get-Date).AddSeconds(120)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing "http://localhost:8080/api/v1/readyz" -TimeoutSec 5
            if ($response.StatusCode -eq 200) {
                $ready = $true
                break
            }
        } catch {
            Write-Host "." -NoNewline
            Start-Sleep -Seconds 3
        }
    }
    if (-not $ready) {
        Show-Diagnostics
        throw "API 在 120 秒内未就绪。"
    }
    Write-Host ""
    Write-Ok "http://localhost:8080/api/v1/readyz 返回 200"

    # ---------- 6. 演示数据 ----------
    if ($NoDemo) {
        Write-Step "初始化演示账号（已跳过）"
    } else {
        Write-Step "初始化演示账号"
        Invoke-Compose -ComposeArgs @("run", "--rm", "init", "python", "-m", "app.cli", "seed-demo")
        Write-Ok "演示账号已就绪"
    }

    # ---------- 7. 可选：模型权重 ----------
    if ($ModelRoot) {
        $resolvedModels = (Resolve-Path $ModelRoot).Path
        Write-Step "注册模型权重：$resolvedModels"
        Invoke-Compose -ComposeArgs @(
            "run", "--rm", "-v", "${resolvedModels}:/assets:ro",
            "init", "python", "-m", "app.cli", "seed-models", "--root", "/assets"
        )
        Write-Ok "模型已注册"
    }

    # ---------- 8. 可选：数据集 ----------
    if ($DatasetDir) {
        $resolvedDataset = (Resolve-Path $DatasetDir).Path
        Write-Step "导入 BUSI 数据集：$resolvedDataset"
        Invoke-Compose -ComposeArgs @(
            "run", "--rm", "-v", "${resolvedDataset}:/dataset:ro",
            "init", "python", "-m", "app.cli", "import-directory", "/dataset"
        )
        Write-Ok "数据导入完成"
    }

    # ---------- 9. 完成 ----------
    Write-Host ""
    Write-Host "BIDL-SP 已启动" -ForegroundColor Green
    Write-Host "  应用入口:     http://localhost:8080"
    Write-Host "  API 文档:     http://localhost:8080/docs"
    Write-Host "  健康检查:     http://localhost:8080/api/v1/readyz"
    if ($WithMinio) {
        Write-Host "  MinIO 控制台: http://localhost:9001"
    } else {
        Write-Host "  对象存储:     本地卷 runtime-data（如需 MinIO：.\start.ps1 -WithMinio）"
    }
    Write-Host ""
    Write-Host "常用命令：" -ForegroundColor Yellow
    Write-Host "  .\start.ps1 -Down"
    Write-Host "  docker compose --env-file deploy/.env -f deploy/docker-compose.yml ps"
    Write-Host "  docker compose --env-file deploy/.env -f deploy/docker-compose.yml logs -f api worker"
} catch {
    Write-Host ""
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
