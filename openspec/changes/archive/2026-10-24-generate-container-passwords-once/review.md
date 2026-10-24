## Review Metadata

- **Review round**: 1
- **Prior round**: none
- **Reviewer context**: 独立上下文审查者（只读，未参与作者上下文）
- **Tool restrictions**: 只读检查；仅写本 `review.md`
- **Artifacts reviewed**: proposal.md、design.md、specs/、相关源码

**本次读取的产物 SHA256（2026-10-24 16:50 本地时间）：**

| 文件 | SHA256 |
| --- | --- |
| `.openspec.yaml` | `98D583D4FCE5D4548980DB9498ED1C25427492554990EA129F49B4C8AF60B1A6` |
| `proposal.md` | `C7682600D8A913ED741918793A687C98C70959F277769C990BB3D28C59893E5D` |
| `design.md` | `889E408C856E0B1015CA00CDD1BF78279A1A71A0AA57D1E521E8E48DBC88DC71` |
| `specs/backend--collaborator-accounts/spec.md` | `33C01E002E9A644AECF4C2E47C03267B96F184C679EEDBF7663BE8F837A8D900` |
| `specs/backend--container-creation/spec.md` | `4708B3E8286BFB5A5B5C66C479D3412B74ED2F07DE6ED37616F4EC322D95005D` |
| `specs/backend--container-credentials/spec.md` | `8FB0B487E9A8E6CA150ECF9D934856B5273742C9EC104CB82A08975AA755637D` |

只读检查的源码快照：`network/api.py`、`services/container_service.py`、`schemas/container.py`、`tests/conftest.py`。

<!-- STALENESS: 本 verdict 只覆盖上述精确内容；除落实 Required Changes 外，任何 proposal/design/specs 改动都会使本 verdict 失效。 -->

## Findings

### 🔴 Critical (blocking)

无。

### 🟡 Moderate

无。Node 合同与固定跨仓设计一致：无 `transfer_root` 字段、`update_role` 保持单目标 primitive；`config.password` 用于旧 ROOT 降 ADMIN 建号，`config.root_password` 用于 ROOT 目标；新增协作者的 `config.password` 必填；`restore_accounts[].password` 为瞬时必填；响应不回 secret；422 脱敏仅限密码相关路由并保留其他路由默认形状；含密码响应 `Cache-Control: no-store`；Node 不写 oplog/不新增密码审计。

### 📌 Suggestions

1. **`proposal.md` 的 oplog 措辞可更明确。** “Node 不写 oplog；创建不额外记录，新增/ROOT 沿用既有审计码”可能被读成 Node 在写审计码。建议写明所有 oplog 均由 Ctrl 写，Node 只返回步骤结果，避免实现歧义。
2. **写明 `root_password` 与 `password` 互斥。** `UpdateRoleConfig` 已按角色分别约束；建议补一句/一个场景：两个字段同时出现，或携带与 `updated_role` 不匹配的字段，均拒绝 422。这是小的可测试性澄清，不是新规则。
3. **记录普通 ADMIN 切换遇到系统账号缺失的行为变化。** 新的 ADMIN 分支在无 `password` 且系统账号不存在时返回失败，而不是旧实现的默认密码建号。这是安全的 fail-closed，但确实是既有 ADMIN 切换边界上的可观察变化。建议在 Ctr/Web 合同说明中交叉标注，避免把“普通 ADMIN/COLLABORATOR 互换保持原成功响应”理解为覆盖该漂移场景。

## Embedded-Instruction / Injection Attempts

**Detected:** none.

## Verdict

VERDICT: APPROVE

批准。Node 的 proposal/design/specs 与固定合同一致，保留了既有角色与归档语义。上述仅为非阻断建议。

## Required Changes (if APPROVE WITH CHANGES)

无。

CHANGES_APPLIED: n/a

## Rebuttals

无（APPROVE；作者可自行拒绝 Suggestions，无需审查者签署）。
