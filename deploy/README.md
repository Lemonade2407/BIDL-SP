# 部署与交接（成员 A）

## 一键启动

Docker 24+、Compose v2，建议 8 vCPU / 16 GB RAM / 50 GB SSD；在仓库根目录执行：

```bash
python deploy/generate_env.py
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --build
docker compose --env-file deploy/.env -f deploy/docker-compose.yml ps
```

`init` 等待 PostgreSQL/MinIO 健康后执行 Alembic、建私有桶、初始化 admin。`api`、worker 与调度器等待初始化成功。首次 Worker 镜像需下载 PyTorch CPU 包，耗时取决于网络。

- API 文档：`http://localhost:8080/docs`
- 就绪检查：`http://localhost:8080/api/v1/readyz`
- MinIO 控制台：`http://localhost:9001`
- admin 密码：本地 `deploy/.env` 的 `ADMIN_PASSWORD`，不输出到日志。

首版服务只绑定本机。局域网演示时同时调整 Nginx/MinIO 端口绑定、`MINIO_PUBLIC_ENDPOINT` 和 `CORS_ORIGINS`，MinIO 签名 URL 必须使用浏览器可达的地址。外网部署应在入口加 HTTPS；不要公开 PostgreSQL/Redis 端口。Nginx 后的 API 不信任客户端转发 IP，因此登录限流按直接连接地址保守计数；如果部署可信代理 IP 白名单，再配置 Uvicorn proxy headers。

## 演示初始化

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml run --rm init python -m app.cli seed-demo
```

生成五角色账号。默认使用 `.env` 的同一演示密码，正式环境创建独立账号并改密。算法权重不入 Git、不打入镜像。挂载只读资产目录后初始化：

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml run --rm -v /absolute/assets:/assets:ro init python -m app.cli seed-models --root /assets
docker compose --env-file deploy/.env -f deploy/docker-compose.yml run --rm -v /absolute/Dataset_BUSI_with_GT:/dataset:ro init python -m app.cli import-directory /dataset
```

也可在 `/docs` 通过 ZIP 上传。单图最多 20 MB，ZIP 压缩及解压总量各不超过 2 GB，最多 2000 个文件；超大批次可拆分。目录导入适合 BUSI 完整数据。

## B/C 交接与演示顺序

1. A/admin 初始化数据、模型和模板；A/data_engineer 创建冻结版本、生成标注任务。
2. C/annotator 领取→保存原始尺寸列优先 RLE→提交；B/reviewer 驳回或通过。
3. C/screener 创建脱敏患者和检查、关联影像，创建筛查任务并领取。
4. C/screener 提交推理，轮询任务成功，接受或修改掩膜，起草并提交报告。
5. B/reviewer 签发；下载 PDF 检查免责声明、签发人和血缘；A/admin 查看审计。

前端构建产物由 C 放入 `deploy/html/`，Nginx 已配置 SPA 路由和 `/api` 代理。当前首页只是后端交接入口。前端 RLE `counts` 为整数数组，与 `algo.adapter.rle` 一致；多图检查修改掩膜必须传 `image_id`。

## 故障处理

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml logs --tail 100 api worker dispatcher scheduler
docker compose --env-file deploy/.env -f deploy/docker-compose.yml restart worker
docker compose --env-file deploy/.env -f deploy/docker-compose.yml run --rm init python -m app.cli dispatch-once
```

任务 queued：检查 scheduler/dispatcher/Redis；running 长时间无结果：检查 worker 和内存；failed：查对应 task_id 日志。修复后新建推理任务，不复用原幂等键。模型回滚调用旧版本的 activate；历史结果参数不改变。重新运行 init 不重置已有账号。

## 备份与恢复

暂停写请求和 Worker 后进行一致性备份；保留数据库、六个 MinIO 桶及配置密钥，Redis 不是唯一任务事实来源。示例在 Linux shell 执行：

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec -T db pg_dump -U bidl -d bidlsp -Fc > bidlsp.dump
```

MinIO 用 `mc mirror` 备份各私有桶，凭据在运维端交互配置，不写脚本或仓库。校验备份文件 SHA256，保存与当前代码 commit 对应的清单。

恢复时先启动空 PostgreSQL/MinIO，恢复桶对象，再用 `pg_restore -U bidl -d bidlsp --clean --if-exists` 恢复数据库，执行迁移并启动 API/Worker。`--clean` 仅用于明确选定的恢复目标库。验收至少检查：readyz、登录、1 张原图、冻结 manifest、1 份历史 PDF 与审计。未经实机恢复演练，不标记“备份恢复已验证”。
