# BIDL-SP · 乳腺影像数据湖与辅助筛查平台

> Breast Imaging Data Lake & Screening Platform
>
> 面向乳腺超声影像的「数据接入 — 标注 — 训练评估 — 辅助筛查 — 报告审计」一体化平台原型。
>
> **本平台仅供科研/教学使用，不作为临床诊断依据。**

---

## 1. 项目简介

BIDL-SP 试图解决乳腺影像落地中的四个问题：

1. **数据分散**：影像散落在工作站与网盘，命名不统一、缺少元数据与质量校验。
2. **标注无沉淀**：掩膜以图片形式散落，无版本、无审核、无法直接用于训练。
3. **模型难落地**：训练脚本与业务系统割裂，模型版本与推理参数无法追溯。
4. **过程不可审计**：报告无法回溯到影像、模型版本、复核人与签发人。

平台在现有 TransUNet + BUSI 复现包之上，补齐数据湖、标注与筛查业务三层，形成可演示、可追溯的完整闭环。

---

## 2. 项目状态

| 部分 | 状态 | 说明 |
|---|---|---|
| 需求分析 | 已完成 | [需求分析.md](需求分析.md) |
| 详细设计 | 已完成 | [详细设计.md](详细设计.md) |
| 接口规范 | 已完成 | [接口规范.md](接口规范.md)，63 个接口 |
| 分工文档 | 已完成 | [分工.md](分工.md) |
| 算法复现包 | 已完成 | 代码、冻结划分、指标与核验脚本已入库；BUSI 与 3 个权重因体积不入 Git，见 [transunet/data/DATASET.md](transunet/data/DATASET.md) |
| 算法服务（成员 B） | 已完成 | `algo/`：模型注册、推理适配、离线评估、Celery Worker、CLI；`python -m algo.cli --help` |
| 平台后端（成员 A） | 已实现，待交叉验收 | `backend/`：63 个 API、数据库迁移、数据湖、标注/筛查/报告、JWT/RBAC、审计、Worker 对接 |
| 平台前端（成员 C） | 待实现 | `frontend/`；当前 deploy/html 为后端交接入口 |
| 部署编排 | 已提供 | `deploy/`：Compose、初始化、健康检查、Nginx；见 [部署说明](deploy/README.md) |

成员 A 后端已实现，启动与测试见 [backend/README.md](backend/README.md)，贡献和验收例外见 [docs/A交付与验收.md](docs/A交付与验收.md)。真实 BUSI 严格去重为 779 张，原文 780 张验收目标存在跨类别重复冲突；详见验收证据。真实权重仍需另外提供。

---

## 3. 核心能力

- **数据湖**：原始层 / 标准化层 / 数据集版本三层分离，sha256 去重，冻结划分可复现。
- **标注闭环**：标注任务、掩膜编辑器、模型预标注、审核仲裁、版本与唯一性约束。
- **算法服务**：复用 TransUNet 权重与推理口径，异步任务、结果缓存、质量标记、模型启停。
- **筛查工作台**：患者/检查建档、工作列表、影像查看器、模型结果复核、操作时间线。
- **报告与审计**：模板化报告、双人审核签发、PDF 归档、全链路审计与统计看板。

---

## 4. 系统架构

```mermaid
flowchart TB
  subgraph L1["展示层"]
    WEB["Vue 3 SPA<br/>Element Plus + Pinia + ECharts"]
  end
  subgraph L2["接入层"]
    NGX["Nginx<br/>静态资源 / 反向代理"]
  end
  subgraph L3["服务层"]
    API["FastAPI<br/>JWT / RBAC / 审计"]
    SCH["任务调度"]
  end
  subgraph L4["计算层"]
    CW["Celery Worker"]
    PRED["推理适配层<br/>TransUNet"]
    EVAL["评估适配层<br/>eval_postproc"]
  end
  subgraph L5["数据层"]
    PG[("PostgreSQL 16")]
    RD[("Redis 7")]
    S3[("MinIO")]
  end
  WEB --> NGX --> API
  API --> PG
  API --> RD
  API --> S3
  API --> SCH --> CW
  CW --> PRED
  CW --> EVAL
  PRED --> S3
  EVAL --> S3
  CW --> PG
```

技术栈：Vue 3 + TypeScript + Element Plus / FastAPI + SQLAlchemy + Alembic / PostgreSQL 16 / Redis 7 / MinIO / Celery / PyTorch 2.5.1 + TransUNet。

---

## 5. 目录结构

```text
BIDL-SP/
├─ README.md                 # 本文件
├─ 需求分析.md                # 需求、角色、FR/NFR、验收标准
├─ 详细设计.md                # 架构、模块、数据模型、算法、前端、部署、测试
├─ 接口规范.md                # REST API 契约、对象模型、错误码、示例
├─ 分工.md                    # 3 人团队 WBS、归属、里程碑、协作规范
├─ transunet/                 # 现有算法复现包（可直接运行）
│  ├─ README.md
│  ├─ code/                   # models / busi_common / eval_postproc / train_supervised
│  ├─ data/
│  │  ├─ Dataset_BUSI_with_GT/ # benign 437、malignant 210、normal 133
│  │  ├─ DATASET.md
│  │  └─ splits/busi_seed0.json
│  ├─ results/                # 3 个种子权重、指标 JSON、sha256
│  ├─ scripts/verify_metrics.py
│  ├─ env/                    # 环境记录与依赖
│  └─ TransUNet/              # 官方仓库，commit 02ef001
├─ algo/                      # 算法服务（成员 B，已实现）
│  ├─ adapter/                # registry / predictor / metrics / RLE / config
│  ├─ worker/                 # Celery tasks + 离线评估适配
│  ├─ models/registry.json    # 3 个种子、权重 sha256 与指标
│  ├─ tests/                  # pytest
│  └─ cli.py                  # 模型/推理/评估/回归命令
├─ backend/                  # 成员 A：API、迁移、测试、验收脚本
├─ deploy/                   # 成员 A：Compose、Nginx、初始化和运维
└─ frontend/                 # 成员 C：待实现
```

> BUSI 数据与 3 个权重已在本地工作区，但被根目录 `.gitignore` 排除，不随 Git 分发；新环境请按 [transunet/data/DATASET.md](transunet/data/DATASET.md) 放置数据，并从课程提交包/网盘获取权重后放入 `transunet/results/`。

---

## 6. 快速开始

### 6.1 复现算法指标（当前可运行）

前置：Python 3.10–3.12（推荐 3.11；如使用 3.13 需确认 PyTorch 轮子可用），磁盘预留 ≥ 6 GB。

> 从 Git 克隆的仓库不含 BUSI 与权重，请先按上一节说明放置数据与权重；当前本地工作区已具备。

**Windows PowerShell**

```powershell
cd transunet
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r env/requirements.txt
python scripts/verify_metrics.py
```

**Linux / macOS**

```bash
cd transunet
python -m venv .venv
source .venv/bin/activate
pip install -r env/requirements.txt
python scripts/verify_metrics.py
```

期望输出最后一行：`RESULT: PASS`。

数据自检：

```powershell
cd transunet\code
python -c "from busi_common import build_index, load_split; print(len(build_index()), load_split()['counts'])"
```

期望：`780 {'train': 546, 'val': 118, 'test': 116}`。

单图完整推理：

```powershell
cd transunet\code
python -u eval_postproc.py --ckpt ..\results\p1_transunet_seed0.pth `
    --model transunet --size 256 --rgb --seed 0 --tta --scales 1.0 `
    --out-tag rerun_s256rgb
```

输出 `transunet/results/rerun_s256rgb_seed0.json`。CPU 模式耗时较长，属正常现象。

> `--scales 1.0` 不能改：TransUNet 使用固定位置编码，多尺度 TTA 会破坏位置编码。

### 6.2 算法服务 CLI（成员 B，当前可运行）

```powershell
pip install -r algo/requirements.txt

# 列出注册模型（3 个种子）
python -m algo.cli models

# 校验 3 个权重的 sha256
python -m algo.cli verify

# 启用/回滚模型版本（本地 registry.json）
python -m algo.cli activate --model s256rgb-seed1

# 单图推理：输出 mask / overlay / result.json 到 algo/outputs/
python -m algo.cli predict `
  --image "transunet/data/Dataset_BUSI_with_GT/benign/benign (1).png"

# 指标回归：期望 RESULT: PASS，可同时写入证据文件
python -m algo.cli verify-metrics --output algo/reports/regression.json

# 完整离线评估（CPU 较慢，输出 A2+A1 / A2+A1+A3 并自动比对登记值）
python -m algo.cli evaluate --model s256rgb-seed0 --device cpu
```

CLI 输出的 `result` 字段与 [接口规范.md](接口规范.md) 5.5.5 对齐（`mask_rle`、`prob_mean`、`lesion_area_ratio`、`quality_flags`、`elapsed_ms`）。批量/异步调用使用 `algo.worker.tasks:execute_inference`，Celery 启动方式见 6.3。

### 6.3 启动平台（成员 A 后端）

前置：Docker 24+、Docker Compose v2，建议 8 vCPU / 16 GB RAM / 50 GB SSD。

```bash
python deploy/generate_env.py
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --build
# init 服务自动完成迁移、私有桶和 admin 初始化；密码见本地 deploy/.env
```

本地开发：

```bash
# 后端
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 算法 Worker（当前仓库可直接运行；Windows 需 -P solo）
celery -A algo.worker.tasks:app worker -Q inference.cpu,eval,default -c 1 -P solo -l info

# 前端
cd frontend
npm install
npm run dev
```

接口文档（开发环境）：`http://localhost:8000/docs`。

> 后端本地开发请完整执行 [backend/README.md](backend/README.md) 的环境配置和迁移；平台 Worker 用 `celery -A app.worker:app worker -Q default,inference.cpu,eval -c 1`，配合 Beat/dispatcher；B 的独立 CLI Worker 不负责平台数据库回写。`frontend/` 尚待 C 完成。

---

## 7. 使用流程

1. **数据接入**：上传 BUSI ZIP，系统校验命名、掩膜配对、尺寸与 sha256，输出导入报告。
2. **数据集版本**：按 seed=0 分层抽样，冻结为 546/118/116，生成 manifest。
3. **标注**：生成标注任务，模型预标注 → 人工修正 → 提交 → 审核通过。
4. **模型**：注册 3 个种子权重，离线评估并登记指标，启用 seed 0 为在线版本。
5. **筛查**：建档 → 工作列表领取 → 查看影像 → 触发推理 → 医生复核。
6. **报告**：起草 → 提交审核 → 签发 → 导出 PDF；全程写审计日志。

---

## 8. 算法基线

3 个种子（150 epoch）在测试集 116 张上的均值：

| 变体 | Dice | 精确率 | 召回率 | 正常图前景占比 | HD95(px) |
|---|---|---|---|---|---|
| baseline | 0.7002 ± 0.0348 | 0.8416 | 0.7405 | 0.00365 | 106.8 |
| A2+A1 | 0.6943 ± 0.0322 | 0.8664 | 0.7377 | 0.00195 | 115.4 |
| A2+A1+A3 | 0.7087 ± 0.0371 | 0.7896 | 0.7929 | 0.00573 | 96.2 |

单种子参考（seed 0，CPU 已实跑核对）：baseline 0.7293 / A2+A1 0.7240 / A2+A1+A3 0.7318。

说明：

- A1（后处理）降低正常图假阳、提高精确率，但会把小病灶判空，导致 HD95 上升（106.8 → 115.4）。
- 测试集仅 20 张正常图，正常图指标只能作点估计，不做统计显著性结论。
- 引用请使用 3 种子均值；单种子波动约 ±0.03。

---

## 9. 文档索引

| 文档 | 内容 |
|---|---|
| [需求分析.md](需求分析.md) | 背景、角色、场景、用例、约 50 条功能需求、14 条非功能需求、验收标准 |
| [详细设计.md](详细设计.md) | 架构、模块、24 张表、接口摘要、算法、前端、安全、部署、测试、追踪矩阵 |
| [接口规范.md](接口规范.md) | `/api/v1` 通用约定、63 个接口、对象模型、错误码、请求示例 |
| [分工.md](分工.md) | 3 人角色、12 个工作包、模块归属、里程碑、协作规范、交叉备份 |
| [transunet/README.md](transunet/README.md) | 算法包使用说明、权重身份、已知坑 |

---

## 10. 配置项

| 变量 | 说明 | 示例 |
|---|---|---|
| `DATABASE_URL` | PostgreSQL 连接串 | `postgresql+psycopg://bidl:****@db:5432/bidlsp` |
| `REDIS_URL` | Celery Broker/缓存 | `redis://redis:6379/0` |
| `MINIO_ENDPOINT` | 对象存储地址 | `minio:9000` |
| `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` | 对象存储凭据 | 部署时生成 |
| `JWT_SECRET` | JWT 签名密钥 | 随机 32 字节 |
| `MODEL_CACHE_DIR` | 权重缓存目录 | `/models` |
| `DEVICE` | 推理设备 | `cpu` / `cuda` |
| `MAX_UPLOAD_MB` | 上传大小上限 | `20` |
| `TRANSUNET_ROOT` | 官方仓库路径 | `/opt/bidl/transunet/TransUNet` |
| `PYTHONPATH` | 复用 `busi_common` | `/opt/bidl/transunet/code` |
| `BIDLSP_MODEL_REGISTRY` | 模型注册表路径 | `algo/models/registry.json` |
| `BIDLSP_ALGO_OUTPUT_DIR` | 推理产物目录 | `algo/outputs` |

---

## 11. 测试与验收

```bash
# 算法服务单测（当前可运行）
python -m pytest algo/tests -q

# 慢速一致性测试：适配层输出需与已记录 A2+A1 单图 Dice 一致
$env:RUN_SLOW_TESTS='1'; python -m pytest algo/tests/test_predictor.py -q

# 算法回归（当前可运行）
cd transunet && python scripts/verify_metrics.py        # 期望 RESULT: PASS

# 后端与前端（交付后）
cd backend && pytest
cd frontend && npm run test:e2e
```

验收要点：

- 数据入湖 780 张，计数 437/210/133，重复 0。
- 数据集版本复现 546/118/116。
- seed 0 单图 A2+A1 Dice = 0.7240（容差 1e-3）。
- 筛查—报告—PDF 全链路可演示，RBAC 与审计通过。
- 全站与报告固定展示免责声明。

完整清单见 [需求分析.md](需求分析.md) 第 8 章与 [分工.md](分工.md) 第 10 章。

---

## 12. 常见问题

**Q1：为什么 A2+A1 的 Dice 比 baseline 低？**
A1 会丢弃面积占比 < 0.1% 的预测，能降低正常图假阳并提高精确率，但小病灶被误判为空时 Dice 下降、HD95 上升。因此平台同时保留原始掩膜与后处理掩膜，指标分开登记。

**Q2：为什么不能做多尺度 TTA？**
TransUNet 使用固定位置编码，多尺度输入会破坏位置编码；本方案只做水平翻转，命令中 `--scales 1.0` 不能省。

**Q3：CPU 能跑吗？**
可以。2026-10-30 已在纯 CPU 环境完成 seed 0 端到端复跑，结果与 GPU 记录值逐位一致；速度较慢，平台采用异步任务与结果缓存。

**Q4：为什么正常图指标波动大？**
测试集只有 20 张正常图，只能作点估计；请引用 3 种子均值与标准差。

**Q5：数据和权重为什么不建议进 Git？**
BUSI 约 2 GB、单权重约 421 MB。当前本地工作区为便于复现已包含数据与权重，但根目录 `.gitignore` 已排除，不随 Git 分发；正式仓库建议放对象存储/网盘，仓库仅保留 manifest 与 sha256。

**Q6：TransUNet 可以换版本吗？**
不可以直接换。权重依赖 commit `02ef0010b36eb8328b5e689eadaf613602edf9b8`，换版本可能导致 `state_dict` 键名不匹配；升级必须重跑指标回归。

---

## 13. 数据与合规

- 数据：BUSI（Al-Dhabyani et al., Data in Brief 2020），公开科研数据。
- 平台不存储姓名、证件号、联系方式等直接身份标识；预留 DICOM 接入时先做脱敏。
- 界面、报告与演示材料必须保留「仅供科研/教学使用，不作为临床诊断依据」。
- 第三方资产遵循其原始许可：BUSI 数据集许可、TransUNet 仓库 LICENSE。

---

## 14. 贡献与分工

3 人团队分工、工作包、评审矩阵与交叉备份见 [分工.md](分工.md)。协作约定：

- `main` 受保护，`dev` 集成，`feat/<模块>-<描述>` 开发；
- PR 至少 1 人评审，接口变更先改 [接口规范.md](接口规范.md)；
- 数据与权重不进 Git，文档与代码同 PR 更新；
- 完成定义：代码 + 测试 + 文档 + 评审 + 可演示。

---

## 15. 致谢

- BUSI 数据集作者与公开镜像维护者。
- TransUNet 官方仓库（Beckschen/TransUNet）。
- 课程指导教师与评审人。


### 成员 A 交付入口

- [后端运行与接口说明](backend/README.md)
- [部署、初始化、备份和 B/C 交接](deploy/README.md)
- [A 的任务完成情况与验收限制](docs/A交付与验收.md)
- [真实 BUSI 导入与冻结证据](docs/evidence/busi-acceptance.json)
