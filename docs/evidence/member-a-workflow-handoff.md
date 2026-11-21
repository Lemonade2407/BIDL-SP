# 成员 A 流程回程交付与联调

日期：2026-11-21。基线：队长 master 的 b523e23（已包含 PR #4 的 CI 修复）。

## 交付范围

- WP-13：通知迁移、通知 API、真实待办、业务事件去重；人工任务预警与宽限期回收；停用账号释放任务并吊销令牌。
- WP-14：冻结 422 DATASET_GAP、完整计数与前 100 个样本、缺失掩膜检测、草稿版本批量补标、重复请求去重。
- WP-15：报告驳回留档、新修订版、管理员作废、原 PDF 保留、数据库禁止修改历史证据、严格禁止自签。
- WP-16：筛查退回与三种重做分支、原领取人/admin 处理、强制重新推理、失败仅重投失败项、原历史保留、工作列表和时间线。
- WP-20 配套：质量统计 API（带分子分母和口径），供 B 复核、C 展示。
- WP-21：接口规范、详细设计、分工、需求与部署说明同步。

前端本次只做接口兼容：补充状态枚举/状态标签、现有驳回入口明确人工重做、报告页面以服务端响应为准且历史状态只读。WP-19 页面功能与 WP-20 页面 E2E 仍由 C 主责，不能用本次后端测试替代团队的页面验收。

## C 联调步骤

1. 通知：调用 `/notifications/unread-count`、`/notifications?unread=true`；点击以返回的 link 导航，再调用 read。通知已读不等于任务完成，待办以 `/todos` 为准。
2. 缺口：冻结遇到 422 DATASET_GAP 展示 details 中两种计数及样本；按 dataset_version_id 调 `/annotation-tasks/batch`，不要只提交前 100 个样本 ID，否则会漏补。补标全部审核通过后手动再次冻结。
3. 报告：rejected/voided 只读。显示 review_comment/rejected_at 或 void_reason/voided_at；点击 revisions（可传新 content）获得新 ID，跳转新报告再编辑/提交。signed 的作废只给 admin，理由必填。voided 的 PDF 是原签发证据，页面必须明显展示已作废。
4. 筛查：工作列表支持 returned，展示 return_reason/follow_up；manual 重新 claim 后人工 modify；transfer 由 admin reassign；re_infer 调 claim 得到 202 和 retry_task_ids，轮询推理，成功后再次 claim。409 运行中不可继续复核；失败后 claim 只重投失败项。重复任务由数据库唯一约束阻止。
5. 统计：`/stats/quality` 返回 numerator/denominator/rate；空分母为 0。B 确认统计口径后，C 展示质量页。

## 部署与历史数据

迁移 0006 为新增表/字段；旧报告正文、快照、签发时间、PDF 键不重写。旧 study_review.follow_up 布尔值保留，新 return_action 用于 re_infer/manual/transfer，API 返回对应枚举。历史字段没有的信息返回 null，return_count 默认为 0。

部署前保留数据库备份；正常执行 `alembic -c backend/alembic.ini upgrade head`。Compose init 自动升级，随后重新构建/启动 api、worker、beat。不得删除现有数据库卷。
新变量：ANNOTATION_SLA_HOURS=48、SCREENING_SLA_HOURS=24、TASK_RELEASE_GRACE_HOURS=24；Beat 每 60 秒检查。宽限期从首次预警时间开始，双人已提交内容不会被释放。停用账号时处于 returned 的筛查仍保留退回门禁，管理员继续处理。

## 验证方法

本地验证结果（2026-11-21）：后端与算法共 68 passed、2 skipped；其中新增回程集成用例 15 项。Ruff、前端 type-check/build、登记指标 verify_metrics.py 均通过。迁移用例验证原有 signed 报告升级后正文、快照、签发信息、PDF 字节保持一致，作废时混入正文修改会被数据库拒绝。

- `python -m pytest backend/tests algo/tests -q`：迁移、权限、存储、正常链路与回程集成。
- `python -m ruff check backend/app backend/tests backend/alembic/versions/0006_workflow_loops.py`。
- `npm --prefix frontend run type-check`、`npm --prefix frontend run build`。
- GitHub Backend A：PostgreSQL 16 全套后端测试、local/minio 两种 Compose 启动、异步导入、私有下载和现有页面 Playwright 冒烟。

新增集成测试见 backend/tests/test_workflow_loops.py，推理重做使用明确测试替身，不作为真实权重效果或性能证据。无真实模型权重时不宣称验证实际 Dice/P95。
团队验收还需非作者评审，B 复核口径，C 完成五条回程页面 E2E 与演示证据。
