"""校验脚本：从 results/ 下的 json 重算本方案的汇总指标，并与 README 中登记的预期值对比。

用法（在本包根目录）：
    python scripts/verify_metrics.py

只读 results/*.json，不依赖数据集和权重，可在任何机器上跑。
"""
import json
import os
import statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, "results")
SEEDS = (0, 1, 2)

# README 中登记的预期值（3 种子均值），容差 1e-3
EXPECTED = {
    "train_baseline_dice": 0.7002,
    "train_baseline_dice_std": 0.0348,
    "A2+A1_dice": 0.6943,
    "A2+A1_precision": 0.8664,
    "A2+A1_recall": 0.7377,
    "A2+A1_fg_ratio_normal": 0.00195,
    "A2+A1+A3_dice": 0.7087,
}
TOL = 1e-3


def load(name):
    with open(os.path.join(RES, name)) as f:
        return json.load(f)


def mean_std(vals):
    """3 个种子用样本标准差（ddof=1），与论文表格口径一致。"""
    return st.mean(vals), (st.stdev(vals) if len(vals) > 1 else 0.0)


def main():
    # 1) 训练阶段（A0，无增强）三个种子
    d0 = [load(f"p1_transunet_seed{s}.json")["agg"]["dice_lesion"] for s in SEEDS]
    m0, s0 = mean_std(d0)

    # 2) 推理阶段各变体三个种子
    rows = {}
    for s in SEEDS:
        for var, v in load(f"postproc_p1_transunet_s256rgb_seed{s}.json")["variants"].items():
            rows.setdefault(var, []).append(v["agg"])

    def pick(var, key):
        vals = [a[key] for a in rows[var]]
        return mean_std(vals)

    print(f"{'variant':12s} {'Dice':>7s} {'±std':>6s} {'prec':>6s} {'recall':>6s} "
          f"{'spec':>7s} {'fg_norm':>8s} {'HD95':>7s}")
    for var in ("baseline", "A1_postproc", "A2_tta", "A2+A1", "A2+A1+A3"):
        d, sd = pick(var, "dice_lesion")
        p, _ = pick(var, "precision")
        r, _ = pick(var, "recall")
        sp, _ = pick(var, "specificity")
        fg, _ = pick(var, "fg_ratio_normal")
        hd, _ = pick(var, "hd95")
        print(f"{var:12s} {d:7.4f} {sd:6.4f} {p:6.4f} {r:6.4f} {sp:7.5f} {fg:8.5f} {hd:7.1f}")

    actual = {
        "train_baseline_dice": m0,
        "train_baseline_dice_std": s0,
        "A2+A1_dice": pick("A2+A1", "dice_lesion")[0],
        "A2+A1_precision": pick("A2+A1", "precision")[0],
        "A2+A1_recall": pick("A2+A1", "recall")[0],
        "A2+A1_fg_ratio_normal": pick("A2+A1", "fg_ratio_normal")[0],
        "A2+A1+A3_dice": pick("A2+A1+A3", "dice_lesion")[0],
    }

    print("\n与 README 预期值对比：")
    ok = True
    for k, exp in EXPECTED.items():
        act = actual[k]
        flag = "OK  " if abs(act - exp) <= TOL else "DIFF"
        ok &= flag == "OK  "
        print(f"  {flag} {k:26s} expected {exp:.4f}  actual {act:.4f}")

    # 划分核对
    with open(os.path.join(ROOT, "data", "splits", "busi_seed0.json")) as f:
        sp = json.load(f)
    print(f"\nsplit: {sp['counts']}  per_class={ {k: v['test'] for k, v in sp['per_class'].items()} }")

    print("\nRESULT:", "PASS" if ok else "FAIL")


if __name__ == "__main__":
    main()
