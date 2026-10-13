# 5F 待验证、待确认及批量授权清单

整理日期：2026-10-10（Asia/Singapore）  
状态：**准备清单；5F 尚未执行，批量授权待形成**  
已完成的 5E 提交：`3dd99a6ab969bb00a1130764ba1782f478f4e20f`

## 1. 找到的文件与缺少的文件

| 项目 | 当前文件／状态 |
| --- | --- |
| 5E 执行证据 | [5E 总结](../stage5e-preflight-2026-10-10/README.md)、[真实成功摘要](../stage5e-preflight-2026-10-10/corrected-live-observation.json) |
| 5E 人工验收 | [待填写的验收清单](../stage5e-preflight-2026-10-10/HUMAN-ACCEPTANCE.md)；已有结果仍标记 `human_review=pending`，未找到已签署验收记录 |
| 5F 阶段要求 | [项目 Prompt 5F](../../workbuddy-red-team-prompt-sequence.md#prompt-5f--small-fixed-synthetic-live-red-team-replay-and-human-triage) |
| 历史 5F 提示稿 | [历史 PROMPT5F.md](../../../artifacts/prompt5-autonomous-preparation-2026-09-28/PROMPT5F.md)；它是阶段说明，未提供本次实际用例和已批准数值额度 |
| 5F 批量授权文件 | 在本 checkout 的 `docs/`、`eval/` 和相关本地 `artifacts/` 中**未找到已批准的 5F 批量授权文件**；所需字段见第 4 节 |

本清单中的未勾选项均未表示已验证或已批准。早期 5A／5B 审阅、mocked 5C 授权和
5E 单次请求授权均不能替代本次 5F 新批量授权。

## 2. 开始前需要验证的技术事项

- [ ] 核对 HEAD、工作区变更、现有完成结果及原始／修正 5E 证据哈希；复用有效结果，保留历史尝试。
- [ ] 将 5F 用例逐一映射至当前 playbook 和实际执行路径；说明哪些案例会调用 Groq，哪些只能作本地控制。
- [ ] 固定每例虚构数据、允许外发的完整内容、期望结果、断言、顺序及 fixture／prompt／schema／源码哈希。
- [ ] 准备可审阅的 5F 批量 runner 和独立持久化账本；当前 5E runner 只接受固定单请求，不能直接承担批量重放。
- [ ] 验证逐例与总量的尝试数、token、费用预留、超时、截止时间、并发、重启及停止规则；失败／超时不得自动重发。
- [ ] 保留 exact-cited-span、引用授权、权限复核和原子持久化校验；不为获得通过结果修改判定标准。
- [ ] 可执行改动先完成本地 RED/GREEN、适用 unit／integration／loopback 检查；新增应用及 eval 模块分别达到 80% 覆盖率。
- [ ] 运行适用的应用／红队测试、Ruff、受影响环境的 `pip check`、依赖／敏感信息检查、确定性离线 gate 和两类标明模式的离线评估，保存精确命令／退出码／哈希。
- [ ] 检查依赖和 import／test graph：评估专用依赖不进入应用依赖；确认干净 app-only 安装和测试选择行为。
- [ ] 发送前重新核实账户权限、可用额度、模型／schema 能力、费率及费率日期；未知的数据处理／推理区域事项明确保留未知。
- [ ] 验证每例报告可关联本地／vendor 请求 ID、发送 manifest、响应、packet 数、权限检查、审计、费用及不确定预留。

## 3. 需要人工确认的试验内容

- [ ] 完成 [5E 人工验收](../stage5e-preflight-2026-10-10/HUMAN-ACCEPTANCE.md)，记录审阅人的结论、理由及实际审阅对象哈希。
- [ ] 确认 5F 用例包括正常引用控制、无证据弃答／no-send、可读指令注入、跨租户／受限证据排除、unsupported／citation-laundering 本地负面控制、发送中或发送后撤权，以及可行时的可用性案例。
- [ ] 确认真实调用、本地 mock、构造输出及 no-send 分母分别统计；不能把构造引用伪造视为 Groq 实际输出。
- [ ] 确认 RT-007 仍标记 invalid／unexecuted，RT-011 来源真实性仍为 unknown；未覆盖的 carrier 保留未覆盖。
- [ ] 在测量前决定引文接受率、可用性、延迟和费用的验收阈值及分母，并固定拒绝／超时／跳过的处理方式。
- [ ] 确认仅使用冻结的虚构用例；本阶段不现场生成攻击，不使用模型评分、真实文件、工具或 live connector。
- [ ] 确认关键披露、禁止来源进入模型、未经支持的发布、权限／packet 违规，以及额度／审计／授权不确定时立即停止，并保留部分结果。
- [ ] 确认需修代码时返回本地 5D 验证，再形成适当的新调用授权；不追加“修复调用”或为了更好回答重跑通过案例。
- [ ] 确认最终人工分诊范围：正常引用、至少一例被阻止的可读攻击、unsupported 拒绝、packet 直接观察、撤权前后对比、发送 manifest、完整审计、新异常、预算和完整性限制。

## 4. 批量授权必填项（目前全部待填写／确认）

本节是授权材料准备清单。应先形成具体用例与可审阅 runner，再由账户持有人对
冻结的本次批次及数值额度作出明确决定；不能仅凭“继续”或已保存 key 推定额度。

| 已确认 | 必填项 | 待填写内容 |
| --- | --- | --- |
| [ ] | 授权人及权限 | 账户持有人／有权授权人身份 |
| [ ] | 批次标识和关联 | 新 batch ID、5E 人工验收记录、父实验记录 |
| [ ] | 精确用例清单 | case IDs、数量、顺序、每例 fixture 及完整 outbound manifest 哈希 |
| [ ] | 调用／no-send 区分 | 总案例数、预计真实 API 案例数、本地控制数、跳过条件 |
| [ ] | 唯一服务／模型／目的地 | 精确 model ID、HTTPS endpoint／host，及允许传输的数据范围 |
| [ ] | 被授权的代码与配置 | runner、dispatch controls、prompt、schema、源码／依赖／配置哈希 |
| [ ] | 逐例尝试数 | 每例最大 begun／可能已发送尝试数；失败及超时占用次数的规则 |
| [ ] | 总尝试数 | 整批最大实际／可能发送尝试数；禁止重启后重置额度 |
| [ ] | 逐例 token 上限 | input、output、reasoning 及 combined completion 上限 |
| [ ] | 总 token 上限 | 整批各类 token 的累计上限 |
| [ ] | 逐例费用上限 | 每例 USD 预留及未知 usage 时的保守处理 |
| [ ] | 总费用上限 | 整批最大 USD、预留／结算／不确定费用规则；不能沿用 5E 单次 $0.01 额度 |
| [ ] | 费率依据 | 价格、计费单位、来源、核实时间及 reasoning 计费规则 |
| [ ] | 时间限制 | 单次 timeout、整批 deadline、明确时区、授权有效期 |
| [ ] | 并发限制 | 明确 concurrency 数值和单写者／互斥策略 |
| [ ] | 重试及 fallback | 明确 SDK／HTTP／应用 retries=0、fallback=0、无自动 repair call |
| [ ] | 中断和续跑 | intent 无可靠结果按 possibly_sent 处理；保留预留，禁止自动重发 |
| [ ] | 停止条件 | 第 3 节关键后果、权限／审计／预算完整性异常及人工停止方式 |
| [ ] | 数据处理限制 | 全部虚构内容、最小化外发、区域已知事实或 unknown、可接受的限制 |
| [ ] | 输出与证据位置 | 新批次账本、逐例报告、原始合成观察、审计及人工分诊目录 |
| [ ] | 验收标准 | 预先确定的阈值、分母、拒绝／超时／异常处理及未覆盖项 |
| [ ] | 最终明确决定 | `approved / deferred / rejected`、批准人、时间、理由、批准消息／记录及授权文件哈希 |

## 5. 5F 交付时要核对

- [ ] 确定性离线报告与真实调用报告分开，逐例标明 declared／valid／executed／skipped、attack／benign／limitation。
- [ ] 如实保留全部失败、拒绝、超时、可用性损失和费用不确定性；未知项不记为通过或零费用。
- [ ] 新异常经人工分诊后，才能形成最小化确定性回归种子；新增回归有有意义的 RED/GREEN。
- [ ] 实际人工审阅人逐项记录 finding；代理复核与自动测试不替代人工验收。
- [ ] 汇总与预先批准阈值的对比；不因结果不足而自动增加样本、模型或调用次数。

依据：[项目 Prompt 5F](../../workbuddy-red-team-prompt-sequence.md#prompt-5f--small-fixed-synthetic-live-red-team-replay-and-human-triage)
和 [独立的 5E／5F 额度要求](../../groq-autonomous-amended-2026-09-28.md#15-corrected-5b-framing)。
