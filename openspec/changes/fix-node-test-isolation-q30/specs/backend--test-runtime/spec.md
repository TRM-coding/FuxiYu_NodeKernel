# 规格变更：Node 测试运行时隔离

## ADDED Requirements

### Requirement: 测试替身不得污染测试运行时

Node 测试 MUST NOT 以缺少标准字段的对象替换进程全局 `os.stat`。文件系统测试 SHALL 使用真实临时目录或仅替换被测模块的视图。

#### Scenario: 测试断言失败

- **WHEN** 挂载准备测试抛出断言并由 pytest 生成 traceback
- **THEN** traceback 正常生成并保留原始异常，不因 `st_size`、`st_mode` 等字段缺失而触发内部错误

#### Scenario: 权限模拟

- **WHEN** 挂载用量测试模拟 `stat` 权限错误
- **THEN** 只有被测模块使用模拟函数，进程全局 `os.stat` 保持真实实现
