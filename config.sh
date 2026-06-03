# SciLink37 模型别名表
# 用法：MODEL=4b ./sort.sh / digest.sh / collect.sh
# 默认走 2B；若选了空别名，调用会失败（先填好模型字符串再用）

MODEL_2B="mlx-community/gemma-4-e2b-it-4bit"
MODEL_26B="mlx-community/gemma-4-26b-a4b-it-4bit"   # MoE：26B 总参 / 4B 激活

# 各任务默认模型（仅在未显式指定 MODEL 时生效）
MODEL_DEFAULT_COLLECT=26b
