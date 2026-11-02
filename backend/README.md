# 成员 A 后端

FastAPI + SQLAlchemy + Alembic，实现接口规范的 63 个端点。生产部署用 PostgreSQL、Redis、MinIO 和独立 Celery Worker；本地 SQLite/文件存储用于开发与可重复测试。

## 本地启动（PowerShell，仓库根目录）

推荐 Python 3.11。不要把生成的密码或 `.env` 提交到 Git。

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r backend/requirements-dev.txt
$env:PYTHONPATH='backend;.'
$env:JWT_SECRET = .venv/Scripts/python -c "import secrets; print(secrets.token_urlsafe(48))"
$env:DATABASE_URL='sqlite:///./bidlsp.db'
$env:STORAGE_BACKEND='local'
$env:RATE_LIMIT_BACKEND='memory'
$env:TASK_EAGER='true'
.venv/Scripts/python -m alembic -c backend/alembic.ini upgrade head
.venv/Scripts/python -m app.cli init-storage
.venv/Scripts/python -m app.cli seed-demo
.venv/Scripts/python -m uvicorn app.main:app --port 8000
```

`seed-demo` 交互输入至少 12 字符密码，为 `admin/data_engineer/annotator/screener/reviewer` 创建对应角色账号。已有账号不重置密码。生产环境只执行 `seed-admin`。

浏览器打开 `http://localhost:8000/docs`。先调用 `/api/v1/auth/login`，再在 Authorize 中填入 `access_token`。本地任务不会在 Web 请求中同步执行；提交导入/推理后，在同一配置的另一终端执行 `python -m app.cli dispatch-once`。真实推理需另装 `algo/requirements.txt` 并放置真实权重。Compose 自动调度，无需手动执行。

Linux/macOS 用 `source .venv/bin/activate`、`export PYTHONPATH=backend:.`、`export VAR=value` 设置相同变量。

## 数据与模型初始化

```powershell
# 目录导入仅由服务器管理员执行，不允许远程 API 指定任意服务器路径
.venv/Scripts/python -m app.cli import-directory 'D:/datasets/Dataset_BUSI_with_GT' --dataset BUSI

# 将 registry.json 对应的三份真实权重导入对象存储并逐份验证 SHA256
.venv/Scripts/python -m app.cli seed-models --root 'D:/BIDL-assets'
```

`--root` 下应包含 `transunet/results/p1_transunet_seed{0,1,2}.pth`。也可先通过 MinIO 上传，再调用模型注册 API；服务端再次计算 SHA256。注册后 API 的版本 UUID、参数、权重摘要传给 B 的 `Predictor`，不依赖 B 的本地 JSON 启用状态，不修改算法包。

## 数据质量与版本口径

真实 BUSI 有一对跨类别完全相同图像：`benign (433).png` / `malignant (145).png`。本实现严格执行 SHA256 唯一约束，导入顺序固定，保留 benign 首份，重复及类别冲突写入导入报告。实测为 **779 张 = 437/209/133**；保留官方清单中其余成员原划分，得到 **545/118/116**，验证/测试集不变。详见 [A 交付与验收](../docs/A交付与验收.md)。不能把这一结果写成“780 张且重复 0”。

当输入覆盖原始冻结清单（含已记录重复项），默认 `split_seed=0` 表示复用 `busi_seed0.json`；manifest 记录 `effective_seed=42`、`split_source` 和 `excluded_duplicates`。其他数据集按请求种子分层、按文件名稳定排序划分。冻结保存当时的 approved 标注 ID、版本与掩膜对象键，后续审核不会改变旧 manifest。

公共 BUSI 参考掩膜导入为 `source=import,status=approved`，备注明确这不是人工审核。人工编辑另建版本，必须领取任务、提交并由其他账号审核。筛查复核生成的人工掩膜保持 draft，不会自动混入训练集。

## 事务与任务恢复

- 任务与 outbox 在同一数据库事务中提交，Beat 每 5 秒调度；Broker 暂停不丢失已接受的请求。
- 推理/评估用条件更新保证单次领取，结果写数据库与私有对象存储；GET 查询读取数据库，不依赖 Celery 临时 result backend。
- 推理缓存键包括图像 SHA256、权重 SHA256、完整模型配置和本次参数；结果仍有独立任务记录。
- Worker 超时会落库为 failed。修复依赖后重新提交；复用相同幂等键会返回原失败任务，重试应使用新键。
- 领取使用条件 UPDATE；审核、签发、冻结使用 PostgreSQL 行锁，唯一索引兜底；生产必须用 PostgreSQL。
- 审计表数据库触发器拒绝 UPDATE/DELETE；签发报告、冻结版本及其成员不可改写。数据库超级用户仍是运维信任边界。

## 报告与安全

报告先完成筛查复核，再起草/保存新版本、提交、签发。审核人和起草人分离；管理员自签必须提供理由并单独审计。报告保存模板及血缘快照，已签发 PDF 不重新渲染。草稿预览有“未签发”水印。HTML 模板只接受白名单文本标签和简单变量，禁止执行 Jinja 循环、函数或属性访问。

PDF 使用 ReportLab，Compose 内嵌文泉驿字体；Windows 自动使用系统宋体；可用 `PDF_FONT_PATH` 指向授权 TrueType 字体。无字体的极简开发环境才回退 CID 字体，正式归档应使用 Compose。

JWT 8 小时，登出吊销 jti，改密/角色变更吊销旧令牌；接口权限从数据库实时读取。原图仅 admin/data_engineer，manifest 导出仅 admin；预览/掩膜走 300 秒签名 URL。DICOM 不在首版范围内。

## 验证

```powershell
.venv/Scripts/python -m pytest backend/tests -q
.venv/Scripts/python -m pytest algo/tests -q
.venv/Scripts/python transunet/scripts/verify_metrics.py
.venv/Scripts/python -m ruff check backend/app backend/tests backend/scripts
```

后端测试使用随机合成图、真实数据库迁移和真实 PDF 渲染；算法推理在业务集成测试中注入测试结果，不能据此声称真实模型准确率或 P95 达标。真实权重回归由 B 在权重到位后执行。真实 BUSI 验证脚本为 `backend/scripts/verify_busi.py`，请在独立新数据库运行，输出证据无需包含影像或个人信息。

归档冻结版本（管理员服务器 CLI）：`python -m app.cli archive-version <UUID>`。归档只改变生命周期状态，manifest、成员和标注引用保持不变且不可删除。归档版本不再接受新的标注任务/批量推理/评估。
