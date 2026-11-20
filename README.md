# 绿色出行措施效果评估

用于评估公交接驳、步行网络、公共自行车等措施是否真的改变了居民出行。目标是让交通部门能够区分三件事：

1. **观察到的变化**：试点走廊在观察前后实际出现的客流变化；
2. **对照比较支持的变化**：扣除仍然可比的对照走廊同期变化后，能够归因于措施的部分；
3. **仍无法解释的余量**：观察变化减去对照比较支持的变化后剩下的部分，包含共同季节波动、对照污染与样本/归属误差。

应用以**行程**为需求单位：一次出行即使包含公交、步行、地铁等多个路段，也只计一次，不会把路段数当成独立出行人数。

## 运行环境

需要 Python 3.11 或更新版本，仅使用标准库。

```bash
python -m transport_eval evaluate --study PILOT      # 输出 Markdown 报告
python examples/run_pilot.py                         # 走完冻结→决定→新证据的完整链路
python -m unittest discover -s tests -v              # 运行测试
python -m compileall -q transport_eval tests         # 语法检查
```

## 输入文件

输入目录（默认 `examples/pilot`）由以下 CSV 组成。除标注“可选”的文件外都必须存在；缺列、未知编号、同一行程人群标签不一致等会直接报错并指出文件名、行号与字段。

| 文件 | 作用 |
| --- | --- |
| `periods.csv` | 观察期起止日期 |
| `corridors.csv` | 走廊与其所属区域 |
| `measures.csv` | 措施登记：类型、适用走廊、启用日 |
| `study_windows.csv` | 每个走廊在每期的角色（treated / comparison）、措施或措施包、服务网络版本 |
| `network.csv` | 服务网络版本：站点、线路、有效期、区域 |
| `trip_legs.csv` | 匿名化出行链，同一 `journey_id` 的路段属于同一行程 |
| `surveys_measures.csv` | 分群调查：样本量、总体量、阶段、启用日 |
| `survey_amendments.csv`（可选） | 问卷补样与人群迁移，含修订前数值以便校验 |
| `network_changes.csv`（可选） | 站点搬迁 / 区域调整 |
| `counts.csv`（可选） | 计数器记录，含覆盖率，用于交叉核验 |
| `decisions.csv`（可选） | 预先登记的外部决定记录 |
| `operational/*.csv`（可选） | 决定扩大后新增的运营资料 |

`operational/` 里的文件与冻结输入同名同结构。它们会进入**后续**评估，但不能覆盖冻结输入中已有的同一行程、同一调查记录；一旦重复，加载直接失败。

## 关键行为

- **行程计数**：按 `sample_weight` 加权，但单位始终是行程。
- **对照可比性**：对照走廊若在观察期内启用了类似措施、换了服务版本、站点迁移或人口大幅变动，会被**移出对照汇总**并给出原因；移出后仍有干净对照时研究继续，若一条不剩则以 `NO_VALID_COMPARISON` 阻断结论。
- **估计口径**：使用率为每千人行程数，分母取同一走廊、同一观察期的调查总体量；该假设在敏感性分析中检验（改用修订前总体量）。
- **调查修订**：观察期内生效的修订会改变人群归属，标为阻断；观察期之后生效的修订进入当前估计，但标为“需重新审阅”，不会回写此前已冻结的证据。
- **站点搬迁**：搬出研究走廊的行程会从估计范围消失，标为需审阅；搬迁发生在参与估计的走廊内则阻断结论。
- **计数器**：同时报告原始计数与覆盖率校正值；覆盖率前后变化会单独提示，避免把观测覆盖变化当成客流变化。
- **敏感性**：剔除版本不符行程、剔除搬迁行程、改用修订前总体量、把站点固定回观察前区域，四种口径都会重算主估计。

## 证据冻结与决定台账

```bash
python -m transport_eval --data examples/pilot freeze --study PILOT --exclude-operational
python -m transport_eval --data examples/pilot decide \
    --evidence EV-xxxx --action adjust --rationale "..." \
    --acknowledge COMPARISON_CORRIDOR_REMOVED
python -m transport_eval --data examples/pilot verify  --evidence EV-xxxx
python -m transport_eval --data examples/pilot compare --evidence EV-xxxx
python -m transport_eval --data examples/pilot ledger
```

- **冻结**：对当时可见的全部输入计算 SHA-256，连同评估结果写入 `workspace/evidence/EV-*.json`。
- **登记决定**：必须引用冻结证据；所有 `review_required` 的限制代码都必须用 `--acknowledge` 明确确认，否则拒绝登记。
- **证据漂移**：冻结后任何被固定文件的字节变化都会让登记决定失败（退出码 2），必须重新冻结。新增运营文件不算漂移，单独列为 `new_inputs_since_freeze`，用于说明“决定之后才进入评估”的资料。
- **台账**：每条决定记录当时使用的证据编号、输入摘要、结论等级、需复核触发项，以及它替代与被谁替代的关系。

## 退出码

| 码 | 含义 |
| --- | --- |
| 0 | 成功 |
| 1 | 输入或校验错误（缺文件、缺列、编号未知、决定未确认限制等） |
| 2 | 完整性错误（冻结证据对应的输入已变化） |
