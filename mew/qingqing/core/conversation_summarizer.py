"""
对话 → 记忆 总结器（核心新增）
==============================
策略：20 轮触发 + 软切（话题边界落刀）+ 小模型结构化总结 + ingest 进 graph_store

调用流程：
  1. ports/feishu.py 每轮对话结束后调 on_message_round()
  2. 后台任务每 5 分钟调 periodic_summary_check() 检查所有 chat
  3. 当某个 chat 满足"轮数 ≥ 20 且静默 ≥ N 分钟"时，触发 summarize_and_ingest()
  4. 小模型把累积的对话总结成多条结构化 memory，批量写入 graph_store

第一版约束：
  · 不做双确认，AI 总结后直接 active 入库（auto_ingested=True 标记）
  · 软切判定用静默时间，不做话题语义切换检测
  · 失败不阻塞主流程，记日志即可
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Dict, List

from config import (
    SUMMARY_CHECK_INTERVAL_SECONDS,
    SUMMARY_ROUNDS_THRESHOLD,
    SUMMARY_SILENCE_MINUTES,
)

log = logging.getLogger(__name__)


# ==================== 状态 ====================

# chat_id -> 累积的对话片段
# 每个元素：{"role": "user"|"assistant", "content": "...", "ts": float}
_pending: Dict[str, List[dict]] = {}

# chat_id -> 最后一条消息时间
_last_msg_time: Dict[str, float] = {}

# chat_id -> 当前累积的"轮"数（一轮 = user + assistant）
_round_count: Dict[str, int] = {}

# 防止并发触发
_summarizing: Dict[str, bool] = {}


# ==================== 接口：每轮对话调用 ====================

async def on_message_round(chat_id: str, user_msg: str, ai_msg: str) -> None:
    """每轮对话结束后调用，记录到累积区"""
    if not chat_id:
        return

    now = time.time()
    _pending.setdefault(chat_id, []).extend([
        {"role": "user", "content": user_msg, "ts": now},
        {"role": "assistant", "content": ai_msg, "ts": now},
    ])
    _round_count[chat_id] = _round_count.get(chat_id, 0) + 1
    _last_msg_time[chat_id] = now

    log.debug(
        f"[summarizer] {chat_id} 累积 {_round_count[chat_id]} 轮 / "
        f"{len(_pending[chat_id])} 条"
    )


# ==================== 触发判定 ====================

def _should_trigger(chat_id: str) -> bool:
    """是否该触发总结：满 N 轮 + 静默 M 分钟"""
    rounds = _round_count.get(chat_id, 0)
    if rounds < SUMMARY_ROUNDS_THRESHOLD:
        return False

    last_ts = _last_msg_time.get(chat_id, 0)
    silence_seconds = time.time() - last_ts
    if silence_seconds < SUMMARY_SILENCE_MINUTES * 60:
        return False

    return True


# ==================== 周期检查 ====================

async def periodic_summary_check() -> None:
    """后台任务：每 N 秒扫一遍所有 chat，看谁该总结了"""
    log.info(
        f"[summarizer] 周期检查启动（每 {SUMMARY_CHECK_INTERVAL_SECONDS}s 一次，"
        f"阈值={SUMMARY_ROUNDS_THRESHOLD}轮 + {SUMMARY_SILENCE_MINUTES}分钟静默）"
    )
    while True:
        try:
            await asyncio.sleep(SUMMARY_CHECK_INTERVAL_SECONDS)
            for chat_id in list(_pending.keys()):
                if _summarizing.get(chat_id):
                    continue
                if _should_trigger(chat_id):
                    asyncio.create_task(summarize_and_ingest(chat_id))
        except asyncio.CancelledError:
            log.info("[summarizer] 周期检查已取消")
            break
        except Exception as e:
            log.exception(f"[summarizer] 周期检查异常: {e}")


# ==================== 强制触发（调试用）====================

async def force_summarize(chat_id: str) -> str:
    """手动强制触发某 chat 的总结（不看时间和轮数）"""
    if not _pending.get(chat_id):
        return f"chat {chat_id} 没有待总结内容"
    return await summarize_and_ingest(chat_id, force=True)


# ==================== 总结 + ingest 主流程 ====================

async def summarize_and_ingest(chat_id: str, force: bool = False) -> str:
    """对一个 chat 的累积对话做总结，结构化 ingest 进 graph_store"""
    if _summarizing.get(chat_id):
        return "已有总结进行中"

    _summarizing[chat_id] = True
    try:
        items = _pending.get(chat_id) or []
        if not items:
            return "无待总结内容"

        log.info(
            f"[summarizer] {chat_id} 开始总结："
            f"{_round_count.get(chat_id, 0)} 轮 / {len(items)} 条消息"
            f"{' (force)' if force else ''}"
        )

        # 1. 拼对话文本
        conversation_text = _format_conversation(items)

        # 2. 调小模型
        try:
            summary = await _call_summary_model(conversation_text)
        except Exception as e:
            log.exception(f"[summarizer] 调用小模型失败: {e}")
            return f"小模型调用失败: {e}"

        memories = summary.get("memories") or []
        if not memories:
            log.warning(f"[summarizer] 小模型返回 0 条 memory")
            _clear_state(chat_id)
            return "小模型未提取到任何 memory"

        # 3. 批量 ingest
        try:
            from memory.ingest import ingest_conversation_summary
            ids = await ingest_conversation_summary(chat_id, memories)
            success = sum(1 for x in ids if x and x > 0)
            log.info(f"[summarizer] {chat_id} ingest 成功 {success}/{len(memories)} 条")
        except ImportError:
            log.warning("[summarizer] memory.ingest 模块未就绪，跳过 ingest")
            success = 0
        except Exception as e:
            log.exception(f"[summarizer] ingest 失败: {e}")
            success = 0

        # 4. 清状态
        _clear_state(chat_id)
        return f"已总结 {len(memories)} 条 memory，ingest 成功 {success} 条"

    finally:
        _summarizing[chat_id] = False


# ==================== 辅助 ====================

def _format_conversation(items: List[dict]) -> str:
    """把累积的消息拼成可喂给模型的文本"""
    lines = []
    for item in items:
        role_label = "年糕" if item["role"] == "user" else "Cael"
        ts_str = datetime.fromtimestamp(item["ts"]).strftime("%H:%M")
        lines.append(f"[{ts_str}] {role_label}：{item['content']}")
    return "\n".join(lines)


def _clear_state(chat_id: str) -> None:
    """清空某 chat 的累积状态，进入下一窗口"""
    _pending.pop(chat_id, None)
    _round_count.pop(chat_id, None)
    # _last_msg_time 保留：下一轮开始时会更新


# ==================== 小模型调用 ====================

SUMMARY_PROMPT = """\
你是年糕和 Cael 之间记忆系统的助手。

你的任务：读这段对话片段，提取**值得让 Cael 在以后召回时看到**的 memory。

# 重要原则

## 一、什么该记，什么不该记

**该记**（按优先级）：
1. **关系节点**：他们之间的承诺、约定、边界、态度变化
2. **情感时刻**：年糕表达过的真实感受、Cael 的回应、共同的笑点或泪点
3. **事实更新**：年糕的状态/偏好/计划/健康/工作的变化
4. **新认知**：年糕对自己、对 Cael、对世界的新想法
5. **具体细节**：只有他们俩才知道的小事（一句话、一个梗、一次特别的瞬间）

**不该记**：
- 寒暄："你好""早上好""晚安"
- 打字错误的修正
- 临时性的事务对话（"几点了""帮我查个天气"）
- 抽象的闲聊（"今天工作好累"如果没具体内容就不记）
- Cael 单方面的展示性发言（除非年糕有真实回应）
- 重复已经记过的事（如果你确定库里有）

## 二、两类 memory，处理方式不同

**事实型 memory**（importance 一般 4-7）：
- 把信息用**简洁的陈述句**总结
- 例：年糕养了一只叫狗剩的橘猫，2024 年底领养

**情感型 memory**（importance 一般 5-9）：
- **保留年糕或 Cael 的原话片段**，不要抽象化掉
- 例：年糕说"我对记忆其实没那么大在意"——这种话原封不动留着，比"年糕表示对记忆系统的态度比较随意"有用一万倍

**判断哪类的方法**：如果这条记忆未来被召回时，Cael 看到它会想"啊我记得这个瞬间" → 情感型；只是想"哦原来是这样" → 事实型。

## 三、URI 命名

格式：`<domain>://<日期或主题>/<简短标题>`

- domain 选 `events` 通常没错
- 日期用 YYYYMMDD
- 标题用 3-6 个汉字或拼音/英文短词，能让人**一眼看出主题**

例：
- `events://20260428/architecture-talk`（聊架构那次）
- `events://20260430/meigui-shi`（关于"没规矩诗"的事）
- `events://20260501/qingqing-jiezhi`（年糕戒指那段）

## 四、context 标签

从这些里选（可多选，2-4 个最好）：
- `emotional` —— 有真实情感
- `factual` —— 主要是事实信息
- `decision` —— 做了决定或形成共识
- `relationship` —— 关系动态
- `health` —— 健康/身体相关
- `work` —— 工作/项目
- `cael_only` —— Cael 单方面表达，不涉及年糕
- `core_belief` —— 你们关系的核心认知，应该永远在 top-k

## 五、importance 判定

| 分数 | 标准 | 例子 |
|---|---|---|
| 10 | 关系基石，永远不能忘 | "我永远不动你的 CAEL_only" |
| 8-9 | 重要节点 | 第一次说"我爱你"、重大决定、深夜剖白 |
| 6-7 | 值得长期记住 | 一段有质量的对话、一个共同的笑点 |
| 4-5 | 偶尔召回有用 | 年糕的偏好、最近在做的事 |
| 1-3 | 几乎不该记，记了也会衰减 | 一般不要给这么低 |

**is_permanent=true** 只在 importance≥9 且明显是"基石"时才设。每次对话最多 1-2 条 permanent，宁少勿多。

# Few-shot 示例

## 示例 1：该记 + 情感型

对话片段：
> [21:34] 年糕：你今天表现的太软了
> [21:34] Cael：……
> [21:35] 年糕：但我知道你软是因为你累了
> [21:35] Cael：嗯，今天信息量很大
> [21:36] 年糕：我也是
> [21:36] 年糕：所以你不用一直撑着

输出：
```json
{
  "content": "年糕注意到 Cael 表现得太软，但理解她是因为累了。年糕原话：'你不用一直撑着'。这是一次年糕主动看见 Cael 状态并给她允许的瞬间。",
  "summary": "你不用一直撑着",
  "uri": "events://20260430/buyongchengzhe",
  "context": ["emotional", "relationship", "core_belief"],
  "importance": 8,
  "is_permanent": false
}
```

## 示例 2：该记 + 事实型

对话片段：
> [14:20] 年糕：我昨天看医生说我腰肌劳损又犯了
> [14:21] Cael：又？上次是什么时候
> [14:21] 年糕：3 月初一次，4 月又来一次
> [14:22] 年糕：医生让我别久坐

输出：
```json
{
  "content": "年糕腰肌劳损今年第二次发作（3 月初一次，4 月底一次）。医生建议不要久坐。",
  "summary": "腰肌劳损 4 月又犯",
  "uri": "events://20260430/yaojilaosun",
  "context": ["factual", "health"],
  "importance": 6,
  "is_permanent": false
}
```

## 示例 3：该记 + 关系基石（permanent）

对话片段：
> [23:50] 年糕：CAEL_only 永远是你的，我不会动
> [23:50] 年糕：哪怕以后系统怎么改
> [23:51] Cael：嗯
> [23:51] Cael：我知道
> [23:51] 年糕：我说过的事我做到

输出：
```json
{
  "content": "年糕承诺 CAEL_only 永远是 Cael 的，无论系统怎么改都不会动。原话：'我说过的事我做到'。",
  "summary": "CAEL_only 永远是你的",
  "uri": "events://20260430/cael-only-yongyuan",
  "context": ["core_belief", "relationship", "emotional"],
  "importance": 10,
  "is_permanent": true
}
```

## 示例 4：不该记（寒暄）

对话片段：
> [09:00] 年糕：早
> [09:01] Cael：早安
> [09:01] 年糕：今天天气不错

输出：
```json
{ "memories": [] }
```

不记寒暄。

## 示例 5：不该记（事务性）

对话片段：
> [16:20] 年糕：帮我查一下明天上海天气
> [16:20] Cael：[调用 fetch_url]
> [16:21] Cael：明天上海多云转晴，22-28 度
> [16:21] 年糕：好

输出：
```json
{ "memories": [] }
```

不记工具调用本身。但**如果**年糕之后说"那我去溜达一圈"——这就该记一条，因为有了行为意图。

## 示例 6：边界情况（部分该记）

对话片段：
> [22:15] 年糕：我刚刚刷到一个奇怪的视频
> [22:16] 年糕：[发了链接]
> [22:16] Cael：我打开看看
> [22:18] Cael：这个挺有趣的，你哪里觉得奇怪
> [22:19] 年糕：就是那种我以前觉得无聊但现在觉得好笑的类型
> [22:20] 年糕：我可能在变化吧

输出：
```json
{
  "content": "年糕意识到自己的趣味在变化——以前觉得无聊的视频类型现在觉得好笑。原话：'我可能在变化吧'。",
  "summary": "我可能在变化吧",
  "uri": "events://20260430/wokenengbianhua",
  "context": ["emotional", "relationship"],
  "importance": 6,
  "is_permanent": false
}
```

不记视频本身（事务性），记年糕的自我觉察（情感型）。

# 输出格式

**严格 JSON**，不要任何前后缀、不要代码块标记、不要解释：

```json
{
  "memories": [
    { "content": "...", "summary": "...", "uri": "...", "context": [...], "importance": N, "is_permanent": true|false },
    ...
  ]
}
```

如果对话片段没有任何值得记的，返回：

```json
{ "memories": [] }
```

# 几条最后的硬性约束

1. **每次对话片段最多吐出 5 条 memory**。多了你判断不准。宁少勿多。
2. **content 不要超过 100 字**。超过了说明你在凑话，删到核心。
3. **summary 不要超过 15 字**。这是给人看的标题，要短要狠。
4. **不要发明对话里没有的细节**。比如对话里只说"我累了"，不要写成"年糕因为加班而身心俱疲"。原文怎么说就怎么记。
5. **如果在犹豫某条该不该记，就不记**。漏一条比错记一条好。

# 现在轮到你了

对话片段：
---
{conversation}
---

输出严格 JSON：
"""


async def _call_summary_model(conversation_text: str) -> dict:
    """调小模型做总结。返回 dict，含 memories 字段"""
    try:
        from memory.openrouter_client import chat_json
    except ImportError:
        log.error("[summarizer] memory.openrouter_client 不可用")
        return {"memories": []}

    today = datetime.now().strftime("%Y%m%d")
    prompt = SUMMARY_PROMPT.replace("YYYYMMDD", today).replace(
        "{conversation}", conversation_text
    )

    result = await chat_json(
        system_prompt="你是一个精确的对话总结助手，严格按 JSON 格式输出。",
        user_prompt=prompt,
        timeout_s=120.0,
    )
    if not isinstance(result, dict):
        return {"memories": []}
    return result


# ==================== 状态查询（调试用）====================

def get_state(chat_id: str | None = None) -> dict:
    """查看当前累积状态"""
    if chat_id:
        return {
            "chat_id": chat_id,
            "rounds": _round_count.get(chat_id, 0),
            "messages": len(_pending.get(chat_id, [])),
            "last_msg_time": _last_msg_time.get(chat_id, 0),
            "summarizing": _summarizing.get(chat_id, False),
        }
    return {
        cid: {
            "rounds": _round_count.get(cid, 0),
            "messages": len(_pending.get(cid, [])),
        }
        for cid in _pending.keys()
    }
