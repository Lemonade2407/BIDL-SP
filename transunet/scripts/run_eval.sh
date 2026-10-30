#!/bin/bash
# 推理 A2(TTA) + A1(后处理)，3 个种子
# 注意：TransUNet 用固定位置编码，--scales 必须是 1.0（只做水平翻转）
set -e
cd "$(dirname "$0")/../code"

PY="${PY:-python}"
# 权重前缀：包内现成的是 ab_transunet；换成 150ep 权重时设为 p1_transunet
CKPT_PREFIX="${CKPT_PREFIX:-ab_transunet}"
OUT_TAG="${OUT_TAG:-postproc_ab_transunet_s256rgb}"

for s in 0 1 2; do
  echo "=== infer A2+A1 seed${s} (${CKPT_PREFIX}) ==="
  $PY -u eval_postproc.py --ckpt ../results/"${CKPT_PREFIX}"_seed"$s".pth \
      --model transunet --size 256 --rgb --seed "$s" --tta --scales 1.0 \
      --out-tag "${OUT_TAG}"
done

echo "done. -> results/${OUT_TAG}_seed{0,1,2}.json"
