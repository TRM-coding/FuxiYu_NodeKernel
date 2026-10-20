# 设计

创建容器测试通过 autouse fixture 提供临时挂载根，恢复测试使用真实目录和 `samefile`。挂载用量测试将模块内 `os` 替换为委托真实模块视图，仅拦截被测模块的 `stat`。增加回归断言，确保 traceback 生成期间全局 `os.stat` 保持真实实现。
