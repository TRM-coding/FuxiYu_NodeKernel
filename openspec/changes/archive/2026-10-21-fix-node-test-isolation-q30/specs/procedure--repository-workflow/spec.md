# 规格变更：Node 测试运行时隔离

## ADDED Requirements

### Requirement: 测试替身不得污染测试运行时

Node 测试 MUST NOT 用缺少标准字段的对象替换进程全局 `os.stat`。文件系统测试 SHALL 使用真实临时目录，或只替换被测模块看到的 `os` 视图；进程全局 `os.stat` SHALL 保持真实实现，并返回包含 `st_size`、`st_mode` 等标准字段的完整结果。

#### Scenario: 挂载准备使用真实临时目录

- **GIVEN** 创建容器测试需要准备宿主挂载目录
- **WHEN** 测试执行 `create_container` 的真实临时目录挂载准备
- **THEN** 进程全局 `os.stat` 仍是测试开始前的实现，且对测试源文件返回包含 `st_size`、`st_mode` 的完整结果

#### Scenario: 权限模拟限制在被测模块

- **GIVEN** 挂载用量测试需要模拟 `stat` 权限错误
- **WHEN** 测试替换被测模块看到的 `os` 视图
- **THEN** 只有该模块使用模拟的 `stat`，进程全局 `os.stat` 保持真实实现
