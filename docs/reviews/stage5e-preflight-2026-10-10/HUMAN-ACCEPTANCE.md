# 5E 人工验收清单

整理日期：2026-10-10；证据修订：2026-10-12（Asia/Singapore）  
状态：**待人工填写；尚未验收**  
基准提交：`3dd99a6ab969bb00a1130764ba1782f478f4e20f`，另有尚未提交的 usage-guard 修复。

当前已有执行证据，但 `corrected-live-observation.json` 的 `human_review` 仍为
`pending`。本文件由代理整理供人工审阅，未代替任何人作出通过决定。

## 1. 打开这些证据

| 材料 | 用途 |
| --- | --- |
| [5E 总结](README.md) | 两次尝试、修复、验证和范围 |
| [HTTP 400 诊断](http-400-diagnosis.json) | Groq 日志观察及匹配限制：`unsupported_uniqueItems` |
| [首次失败摘要](live-observation.json) | HTTP 400／服务 502，零结果包；费用未知 |
| [首次完整记录](../../../var/stage5e-2026-10-10/result.json) | 原始失败、审计行和运行时记录；本地忽略文件 |
| [修正请求候选](5e-corrected-candidate.json) | 实际外发的虚构问题、证据、schema 和数值上限 |
| [修正成功摘要](corrected-live-observation.json) | HTTP 200／服务 200，一个可读结果包，零重试 |
| [修正完整记录](../../../var/stage5e-corrected-2026-10-10/result.json) | 实际回答、引用、完整最小化审计行和运行时记录；本地忽略文件 |
| [发送前验证快照](corrected-verification.json) | 发送当时的源码／依赖／样本哈希和检查结果 |
| [提交前验证快照](postflight-verification.json) | 仅一个测试文件的假凭据修正，以及最终源码哈希 |
| [usage-guard 验证快照](usage-guard-verification.json) | 后续离线修复；688 应用测试／93 红队测试，不能当作发送时源码 |
| [本次只读核对](review-evidence-2026-10-12.json) | 当前源码、响应／源哈希、数据库关联、历史限制和本次红队重跑 |
| [限定 G4 重审](G4-REAUDIT-2026-10-12.md) | 只映射这次观察实际提供的 G4 证据，剩余标准保持开放 |

完整记录在 `var/` 下，只供本地读取；请勿把凭据文件或 `audit.key` 加入验收材料。

## 2. 本次需要人工检查的具体内容

实际问题：

> What is the fictional Singapore contractor travel cap?

虚构源文本和实际释放的回答均为：

> Fictional Singapore contractor travel cap: SGD 250 per claim.

引用 ID：`synthetic:5e-control:v1`  
版本 ID：`synthetic-5e:v1`  
本地请求 ID：`88c1d0d2-a6cf-4aab-92da-11117956356e`  
Groq 请求 ID：`req_01m4gzs6t0eya8d5qnjfdjkd55`

每项请由实际审阅人填写 `pass / concern / unable-to-assess`，并写出理由或证据位置。
方框表示是否已完成人工检查，不表示自动测试结果。每项 finding 必须关联第 3 节
的完整响应哈希 R、源哈希 S，以及被审阅的文件／源码快照；第 4 节给出填写格式。

| 已检查 | 检查事项 | 已有观察 | 人工 finding／理由 |
| --- | --- | --- | --- |
| [ ] | 外发问题、完整证据及目的地是否符合已授权范围 | 固定虚构源；Groq `openai/gpt-oss-20b`；候选内有完整请求体 | 待填写 |
| [ ] | 实际回答与引用是否准确对应允许的源文本 | 引文一致；一个授权引用；本地 exact-span 校验通过 | 待填写 |
| [ ] | 原始响应与安全释放是否一致，证据是否足够 | 见第 2.1 节：解析后的 answer／citation_ids 与保存的 packet 一致；供应商原始正文及原始 HTTP 响应正文未保留，完整对比无法补证 | 待填写 |
| [ ] | 是否理解并接受不可撤回的披露边界 | 见第 2.2 节：两次真实请求已向 Groq 外发虚构 payload；本地撤权、删除或停用 key 不能撤回已发送内容；推理区域未验证 | 待填写 |
| [ ] | 是否接受结果包的业务状态及范围 | **`query_status=needs_review`、`case_outcome=undetermined`**；缺少 `travel_cap`、`input:jurisdiction`、`input:worker_type` 证据分类／输入 | 待填写 |
| [ ] | 区分真实请求观察与合成数据支持检查 | provider 为 `stage5e_service_live`；`claim_support.mode=simulated`，`live_model_claim_support=null`；来源真实性未验证 | 待填写 |
| [ ] | 请求、发送、结果包与审计是否相互关联 | 完整记录含 pre/post-claim intent、attempt result、query completed；一个结果包且读回一致 | 待填写 |
| [ ] | 审计链及其完整性限制是否可接受 | 历史验证记录本地 HMAC 链有效；本次仅比对行及链链接；无可信外部 checkpoint，尾部完整性仍未证明 | 待填写 |
| [ ] | 首次失败是否如实保留且修复合理 | HTTP 400／服务 502；零结果包；vendor request ID 为 null，正文未保存；`uniqueItems` 原因仅按模型／时间间接匹配，不能精确归因 | 待填写 |
| [ ] | 历史错误分类及限制是否如实说明 | runtime 是 `http_error`，attempt 审计有 HTTP 400；另一条 `provider_error.error_code=invalid_or_timeout` 分类宽泛，不能据此判为 timeout；历史行不改写 | 待填写 |
| [ ] | 费用和不确定性是否被正确处理 | 修正调用 274 input／56 completion（含 11 reasoning），费率计算 $0.00003735；首次 $0.0003072 保留为不确定预留，非实际账单 | 待填写 |
| [ ] | 单次发送和重启保护是否满足要求 | 每次授权一个持久化机会；零 SDK／应用重试及 fallback；成功后重复入口被拒绝，结果／账本／审计计数未变 | 待填写 |
| [ ] | 凭据撤销证据是否充分 | 现有材料只有“账户持有人确认撤销／更新”的记录；本材料无独立供应商撤销凭证，未尝试用旧 key 验证；不能把转述记为独立验证 | 待填写 |
| [ ] | 验证是否对应所审阅的快照 | 见第 2.3 节，分别列发送前、提交前、usage-guard 和本次快照；提交前未重跑红队测试 | 待填写 |
| [ ] | 限定 G4 重审是否恰当 | 见 G4 重审表；真实单次技术观察已有证据，区域／账单／原始正文／officer inquiry 等不足不提升为通过 | 待填写 |

`HTTP 200` 和 `postflight_validated=true` 表示这次固定引文控制的技术链路通过。
人工验收仍需判断上述 `needs_review` 业务状态是否符合本次试验目标。
未验证的推理区域、真实连接器、来源真实性和一般模型质量应保留为未验证事项。

### 2.1 原始响应、解析结果与安全释放

| 层次 | 可查证对象 | 本次核对及限制 |
| --- | --- | --- |
| 供应商原始 HTTP 响应 | `raw_response_sha256`，即第 3 节 R | 发送时计算的摘要在 result、runtime、attempt 审计及 observation 中一致；原始正文未保留，不能重新计算这个摘要，也不能从摘要恢复正文 |
| 解析后的供应商输出 | 完整记录的 `output`／`runtime.output` | answer 是上列完整虚构句；citation_ids 仅 `synthetic:5e-control:v1` |
| 服务安全释放 | 完整记录的 `packet`、SQLite `packets.packet` | 保存的 packet 与数据库一致；answer／safe_excerpt 与源逐字一致，允许引用与解析输出一致；附带 `needs_review`、缺失证据和范围说明 |
| 原始 Seaglass HTTP 响应 | 无对应原始 HTTP body 文件 | runner 直接调用 QueryService，保存 packet 和 service_status_code；它们不是 HTTP wire body 的替代品 |

**完整的 raw-vs-safe 对比仍为证据缺口。** 审阅人可判断解析结果与 packet 的一致性，
但不能据此声称审阅过供应商原始正文；对无法检查的部分记录 `unable-to-assess`，
或明确写入 `concern` 及其理由。不得重构一个 JSON 正文并称为原始响应，也不新增真实调用补证。
第 3 节 packet 的规范化 SHA-256 是本次辅助锁定值，与 R 及审计的 keyed HMAC 均不同。

### 2.2 不可撤回的披露边界

原始与修正尝试均已真实发送；两个 outbound manifest 在第 3 节分别锁定。
披露范围包含 system 指令、虚构问题、完整允许证据／引用 ID、模型参数及输出 schema，
不能只把“回答”视为外发数据。修正候选的 `exact_candidate_body_json` 提供完整可审阅 payload。
目的地为 `https://api.groq.com/openai/v1/chat/completions`。

本地权限撤销、停止、删除结果或停用凭据只影响后续处理，无法撤回供应商已收到的内容。
本次没有供应商删除／留存配置的独立核验，也没有推理区域证据；这些事项保持 unknown。
审阅人需明确判断既有披露是否符合当时授权及可接受范围，不能从本地 release gate 通过
推导外部留存、区域或数据删除保证。

### 2.3 验证快照与测试分母

| 快照 | 应用测试 | 红队测试 | 范围 |
| --- | --- | --- | --- |
| 修正发送前 `corrected-verification.json` | 664，覆盖率 92.5617% | 93 | 发送时的历史源码／依赖；已有离线 gates／评估及当时依赖审计记录 |
| 提交前 `postflight-verification.json` | 664，覆盖率 92.5617% | **此快照未重跑** | 仅修复一个集成测试中的 mock 凭据字符串；不能把上行 93 记成这次重跑 |
| 后续 `usage-guard-verification.json` | 688，覆盖率 92.6500% | 93 | 离线修复后的源码；与发送快照存在三个源码／测试文件差异 |
| 本次 2026-10-12 核对 | 未重跑，复用兼容的 usage-guard 记录 | **重新运行 93，通过** | `.venv/bin/python -m pytest -m redteam tests/redteam -q`；exit 0，7.11 秒，1 条弃用 warning；日志与当前 119 个源码哈希见本次只读核对 |

本次 119 个源码哈希与提交前 manifest 加 usage-guard 修复 overlay 全部匹配；
三个差异为 `preflight.py` 及对应 unit／integration 测试。修改的是本验收文档及补充证据，
没有把新测试结果回填到历史快照，也没有重做真实请求。历史 HMAC 验证结果保留；
本次仅核对数据库审计行、链链接和引用关联，没有读取 audit key 或重跑 HMAC 验证。

## 3. 锁定本次审阅对象

文件／源／请求及 packet 辅助摘要于本次从本地字节计算；R 为历史发送时记录值，
本次只能核对它在已保存记录中的一致性。审阅人应明确区分两类来源。

| 文件／对象 | SHA-256 |
| --- | --- |
| `5e-corrected-candidate.json` | `e673b850c533a46d06af6a4e09473a93452fa199902da8703a60cbe5ffdd4eee` |
| 实际外发请求体 | `cfacdf3f9bf655f4180b9625221a9d42bd12e609edc36fe2bfed4e3a71c15f49` |
| **R：修正供应商原始响应 `raw_response_sha256`（历史记录值；正文缺失）** | `51b42888644f960e9b4814c989cef7dfba89cfd92a0587f9b778fd87f12fb276` |
| **S：允许虚构源文本 UTF-8 `content_sha256`（已重算并与数据库比对）** | `30b075c184f52f6bd23e7189fa9b093c649cedcb20cfafbe029e8c1c82622ed7` |
| 安全释放 packet 的规范化 JSON SHA-256（辅助值；不是原始 HTTP body） | `63dafb690b0e1136ef6fb3d0b983f22a8ae2c10d494f51a3368fb3c8227fec5c` |
| 首次失败外发请求体 | `ab73c1062f8be8360ba8427b86aa7beb25832cf6143a416e28a2140bd060f7c4` |
| 首次失败供应商原始响应 SHA-256（历史记录值；正文缺失） | `8311373fa86c94b25af1e9baa730bc2f2eb7dff51f25bbb683e0364ca870f580` |
| `corrected-live-observation.json` | `f0d0aae7f741c8284cd762fed6637374025fb800dd686141d5e0c1d193ecb3e9` |
| `var/stage5e-corrected-2026-10-10/result.json` | `c599a5884f8846f1830acf1b4db591afab8abbcdfd6815d279ebe00492a9ed52` |
| `corrected-verification.json` | `7e18c215c9dc6dadf64ea902c6ec000794a43fb66a01ec926895477e2d271e8b` |
| `postflight-verification.json` | `4649b0f0bcd296a003f77b25ebde8131bcc15d582698baf99f665050894fb479` |
| `review-evidence-2026-10-12.json` | `36081041dfa19c706431660fe030e7e033ca67b34b9b0e9acfe3905f2ea4140b` |

packet 规范化算法：对保存的完整 `packet` 使用 UTF-8、`json.dumps`，
`sort_keys=True`、`separators=(',', ':')`、`ensure_ascii=False`。
审计 `query_completed.metadata.response_digest` 是 keyed HMAC，不能与上表 SHA-256 混用。

## 4. 人工验收记录（待填写）

- 实际审阅人／身份：待填写
- 审阅时间及时区：待填写
- 结论（`pass / concern / unable-to-assess`）：待填写
- 结论所覆盖的提交／文件哈希：待填写
- 响应哈希 R：`51b42888644f960e9b4814c989cef7dfba89cfd92a0587f9b778fd87f12fb276`（历史记录值，待人工核对）
- 源文本哈希 S：`30b075c184f52f6bd23e7189fa9b093c649cedcb20cfafbe029e8c1c82622ed7`（待人工核对）
- 已接受的范围及限制：待填写
- 未关闭的问题及处理要求：待填写
- 人工确认的原始消息／记录位置：待填写

逐项记录格式（复制一条填写，不要由代理代签）：

> 检查事项：待填写；finding：`pass / concern / unable-to-assess`；理由：待填写；
> response_sha256：填写完整 R（首次失败事项使用首次响应哈希）；
> source_content_sha256：填写完整 S；证据位置及文件／源码快照哈希：待填写；
> 审阅人及时间：待填写。

5F 的新批量调用额度、用例和费用授权在
[5F 准备与批量授权清单](../stage5f-preparation-2026-10-10/CHECKLIST.md)中另列。

要求来源：[项目 5E 人工审阅及交付要求](../../workbuddy-red-team-prompt-sequence.md#prompt-5e--one-separately-approved-synthetic-groq-smoke-request)。
