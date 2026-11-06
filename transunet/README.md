# TransUNet + CE+Dice + A2+A1 —— 训练好模型的使用包

目标只有一个：**用现成的权重跑通「看图 → 出掩膜」的完整推理链路**，并保证结果可核对。
训练相关脚本已移出（需要重训时见 [code/train_supervised.py](code/train_supervised.py) 里的命令）。

---

## 1. 用起来最少需要这 6 样

| # | 路径 | 作用 | 来源 |
|---|---|---|---|
| 1 | `results/p1_transunet_seed{0,1,2}.pth` | 训练好的权重（150 ep，3 个种子） | ✅ 已在包内 |
| 2 | `TransUNet/` | 网络定义，commit `02ef001` | ✅ 已在包内 |
| 3 | `code/models.py` | 构建 TransUNet（`in_ch=3, n_cls=2, size=256`） | ✅ 已在包内 |
| 4 | `code/busi_common.py` | 图像索引、预处理、A1 后处理、指标 | ✅ 已在包内 |
| 5 | `code/eval_postproc.py` + `code/train_supervised.py` | 推理入口（A2 TTA + A1）；后者仅被 import 复用三个函数 | ✅ 已在包内 |
| 6 | `data/Dataset_BUSI_with_GT/` | 待推理的图像（780 张） | ✅ 已在包内 |

其余文件（`data/splits/`、`results/*.json`、`env/`、`scripts/verify_metrics.py`）是**核对用**，
不参与模型前向，但删掉就无法验证数值是否对得上，建议保留。

---

## 2. 三步跑通

### 2.1 装环境

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r env/requirements.txt                  # torch / torchvision / numpy / scipy / Pillow / ml_collections
```

`ml_collections` 是 TransUNet 配置的硬依赖，缺了会直接 `ModuleNotFoundError`。

### 2.2 放数据

按 `data/DATASET.md` 把 BUSI 解压到 `data/Dataset_BUSI_with_GT/`，三类目录 `benign / malignant / normal`，共 780 张。

自检：

```bash
cd code
python -c "from busi_common import build_index, load_split; print(len(build_index()), load_split()['counts'])"
# 期望 780 {'train': 546, 'val': 118, 'test': 116}
```

### 2.3 推理

```bash
cd code
python -u eval_postproc.py --ckpt ../results/p1_transunet_seed0.pth \
    --model transunet --size 256 --rgb --seed 0 --tta --scales 1.0 \
    --out-tag rerun_s256rgb
```

输出 `results/rerun_s256rgb_seed0.json`：含 `baseline / A1_postproc / A2_tta / A2+A1 / A2+A3 / A2+A1+A3` 各变体的
逐图与汇总指标；本方案的读数取 `variants["A2+A1"]`。

`--scales 1.0` 不能省：TransUNet 用固定位置编码，多尺度会破坏位置编码，只做水平翻转 TTA。

---

## 3. 权重身份与已验证状态

包内 3 个权重是 **150 epoch 的正式权重**（`p1_transunet_seed{0,1,2}.pth`）。

**2026-10-30 已完成端到端验证（seed 0，纯 CPU）**：

| 变体 | 本次重跑 Dice | 记录值 Dice | 差值 |
|---|---|---|---|
| baseline | 0.7293 | 0.7293 | 0.0000 |
| A2_tta | 0.7341 | 0.7341 | 0.0000 |
| **A2+A1** | **0.7240** | **0.7240** | **0.0000** |
| A2+A1+A3 | 0.7318 | 0.7318 | 0.0000 |

精确率、正常图前景占比也逐位一致 → **数据 + 划分 + 代码 + 权重这条链路完全对得上**，
且 CPU 与原始 GPU 结果一致。证据文件：`results/rerun_s256rgb_seed0.json`、`results/rerun_seed0.log`。

权重自查（可随时重跑）：

```bash
cd code
python -c "import torch, models; \
m=models.build_model('transunet', in_ch=3, n_cls=2, size=256); \
sd=torch.load('../results/p1_transunet_seed0.pth', map_location='cpu'); \
sd=sd.get('state_dict', sd); print(m.load_state_dict(sd, strict=False)[:2])"
# 期望 (missing=[], unexpected=[])
```

说明：文件内容是**裸 `state_dict`**（无 `model/size/loss` 元数据），`eval_postproc.py` 两种格式都兼容。
sha256 见 `results/weights.sha256`；身份细节见 [MANIFEST.json](MANIFEST.json)。

---

## 4. 文件说明

| 路径 | 是否必需 | 说明 |
|---|---|---|
| `TransUNet/` | ✅ | 官方仓库，锁定 commit `02ef0010b36eb8328b5e689eadaf613602edf9b8`，换版本会导致 `state_dict` 键名不匹配 |
| `code/models.py` | ✅ | 模型工厂；`transunet` 分支从 `TransUNet/` 导入，可用 `TRANSUNET_ROOT` 覆盖 |
| `code/busi_common.py` | ✅ | `postprocess_mask` 即 A1；根目录可用 `BUSI_ROOT` 覆盖 |
| `code/eval_postproc.py` | ✅ | 推理入口：A2（翻转 TTA）、A1、A3 阈值搜索都在这里 |
| `code/train_supervised.py` | ✅ | 只被 `eval_postproc` import（`aggregate / predict_logits / prob_to_original`），**不必运行** |
| `data/splits/busi_seed0.json` | 核对用 | 冻结划分，决定测试集是哪 116 张 |
| `results/p1_transunet_seed{0,1,2}.pth` | ✅ | 150 ep 权重 + `weights.sha256` |
| `results/rerun_s256rgb_seed0.json` + `rerun_seed0.log` | 证据 | 本次 CPU 端到端重跑输出（与记录值逐位一致） |
| `results/postproc_p1_transunet_s256rgb_seed{0,1,2}.json` | 核对用 | 已记录的推理输出，`verify_metrics.py` 的数据源 |
| `results/p1_transunet_seed{0,1,2}.json` | 核对用 | 每个种子的训练摘要与测试 Dice |
| `results/env.json` | 参考 | 原始运行环境 |
| `scripts/verify_metrics.py` | 核对用 | 不需要数据与权重，直接重算登记值 |
| `MANIFEST.json` | 参考 | 包内自研文件 sha256（不含第三方 `TransUNet/` 与数据集） |

---

## 5. 核对数值

```bash
python scripts/verify_metrics.py     # 期望 RESULT: PASS
```

它只读 `results/*.json`，确认包内记录的 A2+A1 = **0.6943**、A2+A1+A3 = **0.7087** 与登记值一致。

已登记的 150 ep 权重结果（3 种子）：

| 变体 | Dice | 精确率 | 召回率 | 正常图 fg | HD95 |
|---|---|---|---|---|---|
| baseline | 0.7002 ± 0.0348 | 0.8416 | 0.7405 | 0.00365 | 106.8 |
| A2+A1 | 0.6943 ± 0.0322 | 0.8664 | 0.7377 | 0.00195 | 115.4 |
| A2+A1+A3 | 0.7087 ± 0.0371 | 0.7896 | 0.7929 | 0.00573 | 96.2 |

> 单种子参考（seed 0，已实跑核对）：baseline 0.7293 / A2+A1 0.7240 / A2+A1+A3 0.7318。
> 三个种子的离散度较大（±0.03），单看某个种子容易误判，引用请用上面的 3 种子均值。

---

## 6. 已知坑

1. **`TransUNet/` 版本必须锁死**：换 commit 后 `patch_embeddings` 等键名可能变化，加载会报 missing/unexpected。
2. **`--scales 1.0` 不能改**：多尺度 TTA 对固定位置编码无效。
3. **`code/train_supervised.py` 不能删**：它是 `eval_postproc` 的依赖模块，删了推理直接 ImportError。
4. **A1 会抬高 HD95**（106.8 → 115.4）：面积闸门把小病灶判空后，空预测按图像对角线上限计罚。
5. **只有 20 张正常图**时，正常图假阳率只能作点估计，不能做统计判定。
6. 显存：256 输入 + 105.3M 参数，batch 8 需 ≥20 GB；不够就减 `--batch`，结果会轻微偏离。
