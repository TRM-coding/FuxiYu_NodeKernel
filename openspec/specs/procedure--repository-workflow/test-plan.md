# 仓库工作流程测试覆盖

规格：[spec.md](spec.md)

本台账只覆盖 `procedure--repository-workflow`。当前共 18 个 Requirement、40 个 Scenario：已覆盖 2、部分覆盖 0、待复核 38。本轮是 `fix-node-test-isolation-q30` 归档前的主规格同步，只核对新增的“测试替身不得污染测试运行时”两个场景；主规格既有场景未在本轮重新审计，统一标记待复核，不能拿本 change 的整套测试数字推断它们已覆盖。

## 当前场景映射

| Requirement | Scenario | 覆盖状态 | 测试位置与 nodeid/参数 | 验证范围或缺口 |
| --- | --- | --- | --- | --- |
| 提交信息采用真实变更条目 [githooks/commit-msg] | 多项变更 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| 提交信息采用真实变更条目 [githooks/commit-msg] | 自造关键字或缺空格被拒绝 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| 提交信息采用真实变更条目 [githooks/commit-msg] | 没有真实条目被拒绝 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| 禁止工具署名与生成标记 [githooks/commit-msg] | 署名尾注被拒绝 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| 禁止工具署名与生成标记 [githooks/commit-msg] | 末行不合法仍受检 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| 真实合并提交豁免 [githooks/commit-msg] | 真实合并 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| 真实合并提交豁免 [githooks/commit-msg] | 标题写 Merge 不获豁免 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| 钩子随仓库交付并显式启用 [githooks/pre-commit] | 新克隆启用 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| 钩子随仓库交付并显式启用 [githooks/pre-commit] | 安装前核对既有钩子 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| 钩子保持 LF 与执行位 [.gitattributes] | 检出换行为 LF | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| 钩子保持 LF 与执行位 [.gitattributes] | 核对执行位 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| 新增 capability 使用门类前缀 [githooks/pre-commit] | 新增页面规格 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| 新增 capability 使用门类前缀 [githooks/pre-commit] | 叠加前缀被拒绝 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| 新增 capability 使用门类前缀 [githooks/pre-commit] | 缺少门类前缀被拒绝 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| 新增 capability 使用门类前缀 [githooks/pre-commit] | 修改既有规格不强制改名 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| 新增 capability 使用门类前缀 [githooks/pre-commit] | 旧 capability 首次增加 delta | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| 业务能力组织边界 [README.md] | Node 保持 8 个能力单元 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| 业务能力组织边界 [README.md] | 前缀不成为删细节的理由 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| 仓库入口与规格质量 [README.md] | 入口唯一 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| 仓库入口与规格质量 [README.md] | 格式通过不等于语义完整 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| 规范各仓库独立 [README.md] | 不依赖外部规范 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| 问题集中记录并区分证据等级 [Global/QUESTIONS.md] | 新问题带证据等级 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| 问题集中记录并区分证据等级 [Global/QUESTIONS.md] | 修复后标注状态 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| 流程通过不代表业务问题已修复 [README.md] | 待办不写成已修复 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| 流程通过不代表业务问题已修复 [README.md] | 钩子通过不等于业务通过 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| PR 正文采用四类中英双语栏目 [.github/pull_request_template.md] | 只有一栏交付 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| PR 正文采用四类中英双语栏目 [.github/pull_request_template.md] | 只有计划不通过 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| PR 正文采用四类中英双语栏目 [.github/pull_request_template.md] | 交付栏写“无” | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| PR 正文采用四类中英双语栏目 [.github/pull_request_template.md] | 原样保留模板不通过 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| PR 标题与正文结构分离 [.github/pull_request_template.md] | 自然描述标题 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| PR 标题与正文结构分离 [.github/pull_request_template.md] | 检查器不校验标题 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| PR 栏目与提交关键字相互独立 [scripts/ci/check_pr.py] | AMEND 提交不改写 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| PR 栏目与提交关键字相互独立 [scripts/ci/check_pr.py] | 旧栏目仍被接受 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| PR 正文重验与工作流信任边界 [.github/workflows/pr-format.yml] | 修改正文后重验 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| PR 正文重验与工作流信任边界 [.github/workflows/pr-format.yml] | 首次接入先校验摘要 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| PR 正文重验与工作流信任边界 [.github/workflows/pr-format.yml] | 正文只作数据 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| 检查能力边界不得夸大 [README.md] | 不夸大自动检查 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| 规范入口不使用代理说明文件 | 生成代理说明文件 | 待复核 | — | 主规格既有场景；本轮未审计测试覆盖 |
| 测试替身不得污染测试运行时 | 挂载准备使用真实临时目录 | 已覆盖 | [tests/test_create_container.py](../../../tests/test_create_container.py)::test_create_container_mount_setup_keeps_global_os_stat_real | 断言挂载准备未替换全局 `os.stat`（对象身份不变），且对测试源文件返回 `st_size > 0`、`S_ISREG(st_mode)`；定向回归与 Windows/WSL 默认套件均通过 |
| 测试替身不得污染测试运行时 | 权限模拟限制在被测模块 | 已覆盖 | [tests/test_mount_usage_cache.py](../../../tests/test_mount_usage_cache.py)::test_path_gate_maps_permission_error_without_stat；补充 [tests/test_mount_usage_cache.py](../../../tests/test_mount_usage_cache.py)::test_invalid_not_found_and_permission_never_start_du | 断言权限错误映射为 `permission_denied`，且全局 `os.stat` 仍是真实对象；补充用例断言多个错误路径不启动 `du`，用途是防止第二个权限模拟重新引入全局替换 |

## 最近验证

- 时间：2026-10-21 02:53:44 +08:00（提交 `6805b50` 的提交时间；套件运行本身未保留独立时间戳，结果取自该提交的 `verify.md` 与 change `test-plan.md`）
- 版本：`6805b505ea754816919edb5957bc9771a4701c34`（HEAD；本轮同步前工作树干净，源与测试无改动）
- 主 spec SHA256：`92e02962d9953dd9cd26d092d1b05a556552e211d073889b5a905fcba09e9e51`
- 命令与环境：
  - Windows Python 3.11.15 / pytest 9.1.1 / docker 7.2.0：`E:\Miniconda3\envs\lianjue\python.exe -m pytest tests -q --no-header -rs` → `362 passed, 5 skipped, 16 deselected in 6.23s`
  - WSL Ubuntu Python 3.10.20 / pytest 9.1.1 / docker 7.2.0：`cd /mnt/e/AI/Fuxi/FuxiYu_NodeKernel && /home/chest/miniconda3/envs/fuxi/bin/python -m pytest tests -q --no-header -rs` → `367 passed, 16 deselected in 5.95s`
  - 定向回归：`pytest tests/test_create_container.py::test_create_container_mount_setup_keeps_global_os_stat_real tests/test_mount_usage_cache.py::test_path_gate_maps_permission_error_without_stat tests/test_mount_usage_cache.py::test_invalid_not_found_and_permission_never_start_du -q --no-header -rs` → `3 passed`
- 结果：上述 Windows/WSL 数字是 change 范围内整套默认安全套件的真实结果，只用于两个新增场景及其补充断言；38 个主规格既有场景仍为待复核，未因本轮套件通过而被证明覆盖。
- 限制或尚未运行项：
  - Windows 的 5 个 skip 为 2 个 `du unavailable`（`tests/test_mount_usage_api.py:276`、`tests/test_mount_usage_cache.py:378`）和 3 个 `symlink not permitted`（`tests/test_clean_mount.py:80`、`tests/test_mount_usage_cache.py:174`、`tests/test_mount_usage_cache.py:807`）。skip 不计为通过。
  - 16 个 deselected 为真实 Docker/GPU 测试，按默认策略排除且未执行；不宣称真实 Docker/GPU 验证。
  - WSL 默认套件无 skip，但同样未执行 16 个被排除的 Docker/GPU 测试。
  - 本轮只做文档同步与归档，未重跑业务套件；证据来自提交 `6805b50` 已有的真实记录，源代码和测试代码未发生变化。
