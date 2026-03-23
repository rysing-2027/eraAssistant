"""Analysis Agent - AI-powered report evaluation using LangGraph.

This agent orchestrates the evaluation process:
1. Load product knowledge + evaluation criteria from DB
2. Call 3 independent judges (Qwen, OpenAI, DeepSeek) in parallel
3. Main judge consolidates results and generates final score + email content
4. Save all results to Record model
"""
import os
import asyncio
from typing import TypedDict, List, Dict, Any, Optional
from datetime import datetime
import json

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END

import re

from app.models.product_knowledge import ProductKnowledge
from app.models.evaluation_criteria import EvaluationCriteria
from app.models.email_template import EmailTemplate
from app.models.record import Record, RecordStatus
from app.utils.database import get_db
from config.settings import get_settings

# Configure LangSmith tracing
_settings = get_settings()
if _settings.langsmith_api_key:
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_ENDPOINT"] = _settings.langsmith_endpoint
    os.environ["LANGSMITH_API_KEY"] = _settings.langsmith_api_key
    os.environ["LANGSMITH_PROJECT"] = _settings.langsmith_project


def _extract_json_str(raw: str) -> str:
    """Extract JSON string from LLM response, handling markdown blocks, thinking tags, etc."""
    text = raw.strip()

    # Remove <think>...</think> blocks (DeepSeek/GLM thinking mode)
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()

    # Extract from ```json ... ``` block
    m = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
    if m:
        return m.group(1).strip()

    # Extract from ``` ... ``` block
    m = re.search(r'```\s*(.*?)\s*```', text, re.DOTALL)
    if m:
        candidate = m.group(1).strip()
        if candidate.startswith('{'):
            return candidate

    # If text starts with {, find the matching }
    if text.lstrip().startswith('{'):
        return text.lstrip()

    return text


def _try_parse_json(raw: str) -> dict:
    """Try to parse JSON with progressive repair strategies."""
    text = _extract_json_str(raw)

    # 1. Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Remove control characters (except newline/tab)
    cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 3. Remove trailing commas before } or ]
    fixed = re.sub(r',\s*([}\]])', r'\1', cleaned)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # 4. Try to extract first complete top-level JSON object via brace matching
    depth = 0
    start = None
    in_string = False
    escape = False
    for i, ch in enumerate(fixed):
        if escape:
            escape = False
            continue
        if ch == '\\' and in_string:
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            if start is None:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    return json.loads(fixed[start:i+1])
                except json.JSONDecodeError:
                    # Try with trailing comma fix on this substring
                    sub = re.sub(r',\s*([}\]])', r'\1', fixed[start:i+1])
                    try:
                        return json.loads(sub)
                    except json.JSONDecodeError:
                        pass
                    start = None
                    depth = 0

    # 5. Give up
    raise json.JSONDecodeError("Failed to parse after repair attempts", raw[:200], 0)


# ============================================================================
# 统一限流器 — 每个 API provider 一个实例
# ============================================================================

class RateLimiter:
    """通用 API 限流器：Semaphore 控制并发 + 最小间隔控制 QPS。"""

    def __init__(self, name: str, max_concurrent: int = 3, min_interval: float = 0.2):
        self.name = name
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._min_interval = min_interval
        self._last_call_time = 0.0
        self._lock = asyncio.Lock()

    async def call(self, llm, messages) -> Any:
        async with self._semaphore:
            async with self._lock:
                now = asyncio.get_event_loop().time()
                elapsed = now - self._last_call_time
                if elapsed < self._min_interval:
                    await asyncio.sleep(self._min_interval - elapsed)
                self._last_call_time = asyncio.get_event_loop().time()

            return await llm.ainvoke(messages)


# 各 provider 限流配置
# DashScope (通义千问 + Kimi K2): 5 QPS → max_concurrent=3, interval=0.2s
_dashscope_limiter = RateLimiter("dashscope", max_concurrent=3, min_interval=0.2)
# 火山方舟 (Doubao): 保守限制 → max_concurrent=3, interval=0.3s
_ark_limiter = RateLimiter("ark", max_concurrent=3, min_interval=0.3)
# DeepSeek: 保守限制 → max_concurrent=3, interval=0.3s
_deepseek_limiter = RateLimiter("deepseek", max_concurrent=3, min_interval=0.3)

# provider 名称 → 限流器映射
_LIMITERS: Dict[str, RateLimiter] = {
    "dashscope": _dashscope_limiter,
    "ark": _ark_limiter,
    "deepseek": _deepseek_limiter,
}


async def call_with_rate_limit(provider: str, llm, messages) -> Any:
    """统一限流调用入口。"""
    limiter = _LIMITERS.get(provider)
    if limiter:
        return await limiter.call(llm, messages)
    # 未知 provider，直接调用
    return await llm.ainvoke(messages)


# ============================================================================
# State Definition
# ============================================================================

class AnalysisState(TypedDict):
    """State passed through the LangGraph workflow."""
    # Input
    record_id: int
    employee_name: str
    raw_text: str

    # Loaded context (from DB)
    knowledge_content: str
    evaluation_criteria: str
    email_template: str

    # Judge results
    judge_1_result: Optional[Dict[str, Any]]
    judge_2_result: Optional[Dict[str, Any]]
    judge_3_result: Optional[Dict[str, Any]]

    # Final output
    final_score: Optional[Dict[str, Any]]
    email_content: Optional[str]
    error: Optional[str]


# ============================================================================
# Prompts
# ============================================================================

def get_judge_system_prompt(knowledge_content: str, evaluation_criteria: str) -> str:
    """Get system prompt for individual judges."""
    return f"""你是一位专业的产品体验报告评估专家。请独立、客观地评估员工提交的产品体验报告。

## 产品知识库
{knowledge_content}

## 评估标准
{evaluation_criteria}

## 评估导向

你的核心任务是**挖掘用户对产品的真实反馈**，而不是审查员工的报告写得如何。
- 关注：员工发现了哪些产品问题？提出了哪些有价值的洞察？
- 不关注：员工的报告写得够不够好、应该如何改进
- **重要**：在评价和总结中，尽量引用用户的"原话"，这样更真实、更有说服力

## 重要约束

1. **严禁编造产品知识**：所有产品介绍、功能说明必须严格来源于"产品知识库"中的内容，不得凭空编造或臆测任何产品信息。
2. **严禁做任何承诺或暗示改进计划**：绝对不要向用户承诺任何修复时间、功能上线计划、技术方案或解决方案。禁止使用"正在优化"、"后续版本会改进"、"已纳入规划"、"将在下个版本修复"等暗示产品团队有具体行动的表述。你的角色是"倾听者和记录者"，只需确认收到反馈、表示理解和重视、说明已记录并转达给产品团队即可。

## 输出要求

请以JSON格式返回评估结果，格式如下：
{{
  "总分": 0,
  "等级": "S/A/B/C/D",
  "各维度评分": {{
    "体验完整性": {{"分数": 0, "满分": 20, "评价": ""}},
    "用户视角还原度": {{"分数": 0, "满分": 15, "评价": ""}},
    "分析深度": {{"分数": 0, "满分": 25, "评价": ""}},
    "建议价值": {{"分数": 0, "满分": 20, "评价": ""}},
    "表达质量": {{"分数": 0, "满分": 10, "评价": ""}},
    "态度与投入": {{"分数": 0, "满分": 10, "评价": ""}}
  }},
  "报告亮点": ["亮点1：具体的洞察或发现", "亮点2：..."],
  "产品痛点总结": ["痛点1：用户反馈的产品问题", "痛点2：..."],
  "期望功能总结": ["期望1：用户希望增加的功能", "期望2：..."]
}}

注意：
- "报告亮点"：挖掘报告中有价值的洞察和发现
- "产品痛点总结"：总结用户反馈的产品问题和不足
- "期望功能总结"：总结用户期望增加或改进的功能
- 如果没有明显问题，对应字段可以为空数组

只返回JSON，不要包含其他文字。"""


def get_main_judge_system_prompt(evaluation_criteria: str, email_template: str) -> str:
    """Get system prompt for main judge."""
    return f"""你是最终的评估裁决者。三位评委已经对员工的产品体验报告进行了独立评估。

## 评估标准
{evaluation_criteria}

## 评估导向

你的核心任务是**汇总用户对产品的真实反馈**，而不是审查员工的报告写得如何。
- 关注：员工发现了哪些产品问题？提出了哪些有价值的洞察？
- 不关注：员工的报告写得够不够好、应该如何改进
- **重要**：在总结和邮件中，尽量引用用户的"原话"，这样更真实、更有说服力

## 重要约束

1. **严禁编造产品知识**：所有产品介绍、功能说明必须严格来源于评委提供的信息，不得凭空编造或臆测任何产品信息。
2. **严禁做任何承诺或暗示改进计划**：绝对不要向用户承诺任何修复时间、功能上线计划、技术方案或解决方案。在邮件的"针对性反馈"部分：
   - ❌ 禁止说"正在优化"、"后续版本会改进"、"已纳入规划"、"将在下个版本修复"、"我们正在研发"
   - ❌ 禁止编造技术方案（如"端侧模型"、"重构配对流程"、"参考XX体验"）
   - ❌ 禁止给出优先级判断（如"P0级问题"、"重点优化方向"）
   - ❌ 禁止暗示时间节点（如"紧急版本"、"近期"）
   - ✅ 只需：确认收到反馈 → 表示理解和重视 → 说明已记录并转达给产品团队
   - ✅ 可用表述："感谢你指出这个问题，我们已如实记录并反馈给产品团队"、"这个反馈很有价值，已同步给相关团队"
   你的角色是"倾听者和记录者"，不是"产品决策者"。
3. **评分下限**：尽量不要给低于60分的总分。即使报告质量确实较差，最终总分也应给在60分左右，体现对员工参与的基本认可。

## 你的任务

1. 审阅三位评委的评分结果，判断是否合理
2. 如有明显偏差，做出你的裁决并说明理由
3. 生成最终评分（计算三位评委的平均分，或根据你的判断调整）
4. 汇总报告亮点、产品痛点、期望功能
5. 撰写给员工的反馈邮件（中英双语）

## 邮件模板

请参考以下模板格式撰写邮件，可根据实际情况调整内容：

{email_template}

## 输出要求

请以JSON格式返回，格式如下：
{{
  "final_score": {{
    "总分": 0,
    "等级": "S/A/B/C/D",
    "各维度平均分": {{
      "体验完整性": {{"分数": 0, "满分": 20}},
      "用户视角还原度": {{"分数": 0, "满分": 15}},
      "分析深度": {{"分数": 0, "满分": 25}},
      "建议价值": {{"分数": 0, "满分": 20}},
      "表达质量": {{"分数": 0, "满分": 10}},
      "态度与投入": {{"分数": 0, "满分": 10}}
    }},
    "个性化开场白": "用1-2句话总结这位员工报告中最突出的贡献或发现，体现我们认真阅读了报告。例如：你在XX场景下发现的XX问题非常有价值，这个洞察直接帮助我们定位了一个关键的用户体验瓶颈。",
    "针对性反馈": ["反馈1：针对报告中具体内容给出的个性化建议或回应", "反馈2：..."],
    "报告亮点": ["亮点1：具体的洞察或发现", "亮点2：..."],
    "产品痛点总结": ["痛点1：用户反馈的产品问题", "痛点2：..."],
    "期望功能总结": ["期望1：用户希望增加的功能", "期望2：..."]
  }},
  "judgment_notes": "裁决说明...",
  "email_content": "邮件内容（Markdown格式，中英双语）..."
}}

注意：
- "个性化开场白"：用1-2句话总结这位员工报告中最突出的贡献或发现，让员工感受到我们认真阅读了报告，要具体、真诚、有温度
- "针对性反馈"：针对报告中的具体内容确认已收到并记录，如果知识库中有事实性信息可以澄清用户误解则补充说明，但绝不做任何承诺或暗示改进计划
- "报告亮点"：挖掘报告中有价值的洞察和发现
- "产品痛点总结"：总结用户反馈的产品问题和不足
- "期望功能总结"：总结用户期望增加或改进的功能
- 邮件内容应肯定员工的贡献，强调其对产品改进的价值

只返回JSON，不要包含其他文字。"""


# ============================================================================
# Node Functions
# ============================================================================

def load_context(state: AnalysisState) -> dict:
    """Load product knowledge, evaluation criteria, and email template from database."""
    try:
        with get_db() as db:
            # Load product knowledge
            knowledge_items = db.query(ProductKnowledge).filter(
                ProductKnowledge.is_active == True
            ).order_by(ProductKnowledge.product_line, ProductKnowledge.sort_order).all()

            if knowledge_items:
                grouped = {}
                for item in knowledge_items:
                    if item.product_line not in grouped:
                        grouped[item.product_line] = []
                    grouped[item.product_line].append(item.to_prompt_text())

                lines = []
                for product_line, items in grouped.items():
                    lines.append(f"\n## {product_line}")
                    lines.extend(items)
                knowledge_content = "\n".join(lines)
            else:
                knowledge_content = "暂无产品知识库内容"

            # Load evaluation criteria
            criteria_items = db.query(EvaluationCriteria).filter(
                EvaluationCriteria.is_active == True
            ).order_by(EvaluationCriteria.sort_order).all()

            if criteria_items:
                criteria_content = "\n\n".join([item.to_prompt_text() for item in criteria_items])
            else:
                criteria_content = "暂无评估标准内容"

            # Load email template
            email_template = db.query(EmailTemplate).filter(
                EmailTemplate.is_active == True
            ).first()

            if email_template:
                email_template_content = email_template.to_prompt_text()
            else:
                email_template_content = """{员工名}你好！

感谢你提交这份产品体验报告！你的反馈对产品改进非常有价值。

---

### 📊 评分结果

**{总分}分 / {等级}级**

### ✨ 报告亮点

（汇总评委认可的报告亮点）

### 🔧 产品痛点反馈

（汇总你发现的产品问题）

### 💡 期望功能建议

（汇总你提出的改进建议）

---

期待你继续关注产品体验，为公司带来更多有价值的洞察！

Best regards,
产品体验评估委员会"""

        return {
            "knowledge_content": knowledge_content,
            "evaluation_criteria": criteria_content,
            "email_template": email_template_content
        }

    except Exception as e:
        return {
            "error": f"Failed to load context: {str(e)}",
            "knowledge_content": "暂无产品知识库内容",
            "evaluation_criteria": "暂无评估标准内容",
            "email_template": "暂无邮件模板"
        }


async def call_judge(
    llm,
    system_prompt: str,
    raw_text: str,
    employee_name: str,
    judge_name: str,
    provider: str = "dashscope"
) -> Dict[str, Any]:
    """Call a single judge LLM with timeout protection and rate limiting."""
    content = ""
    try:
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"## 员工姓名\n{employee_name}\n\n## 报告内容\n{raw_text}")
        ]

        response = await asyncio.wait_for(
            call_with_rate_limit(provider, llm, messages), timeout=300
        )

        content = response.content
        result = _try_parse_json(content)
        result["judge"] = judge_name
        result["success"] = True
        return result

    except asyncio.TimeoutError:
        return {
            "judge": judge_name,
            "success": False,
            "error": "Timeout after 300s"
        }
    except json.JSONDecodeError as e:
        return {
            "judge": judge_name,
            "success": False,
            "error": f"JSON parse error: {str(e)}",
            "raw_response": content[:500] if content else None
        }
    except Exception as e:
        return {
            "judge": judge_name,
            "success": False,
            "error": str(e)
        }


def create_tongyi_llm(settings, json_mode: bool = False) -> Any:
    """创建通义千问 LLM (使用 OpenAI 兼容接口)。"""
    kwargs = dict(
        model="qwen3.5-plus",
        api_key=settings.dashscope_api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        temperature=0.3,
    )
    if json_mode:
        kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
    return ChatOpenAI(**kwargs)


def create_glm_llm(settings, enable_thinking: bool = True, json_mode: bool = False) -> Any:
    """创建 Kimi K2 LLM (使用阿里云百炼 OpenAI 兼容接口)。"""
    kwargs = dict(
        model="kimi-k2-thinking",
        api_key=settings.dashscope_api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        temperature=0.3,
    )
    # kimi-k2-thinking supports json_mode even in thinking mode
    if json_mode:
        kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
    return ChatOpenAI(**kwargs)


async def analyze_parallel(state: AnalysisState) -> dict:
    """Call 3 judges in parallel."""
    settings = get_settings()

    # Initialize LLMs — all with json_mode for guaranteed valid JSON output
    try:
        judge_1_llm = create_tongyi_llm(settings, json_mode=True)
    except Exception:
        judge_1_llm = None

    try:
        judge_2_llm = ChatOpenAI(
            model="doubao-seed-2-0-lite-260215",
            api_key=settings.ark_api_key,
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            temperature=0.3,
        )
    except Exception:
        judge_2_llm = None

    try:
        judge_3_llm = ChatOpenAI(
            model="deepseek-reasoner",
            api_key=settings.deepseek_api_key,
            base_url="https://api.deepseek.com/v1",
            temperature=0.3,
            model_kwargs={"response_format": {"type": "json_object"}},
        )
    except Exception:
        judge_3_llm = None

    # Build system prompt with both knowledge AND criteria
    system_prompt = get_judge_system_prompt(
        state.get("knowledge_content", ""),
        state.get("evaluation_criteria", "")
    )

    # Call judges in parallel (each with its own rate limiter)
    tasks = []
    if judge_1_llm:
        tasks.append(call_judge(judge_1_llm, system_prompt, state["raw_text"], state["employee_name"], "Judge 1 (Qwen)", provider="dashscope"))
    if judge_2_llm:
        tasks.append(call_judge(judge_2_llm, system_prompt, state["raw_text"], state["employee_name"], "Judge 2 (Doubao)", provider="ark"))
    if judge_3_llm:
        tasks.append(call_judge(judge_3_llm, system_prompt, state["raw_text"], state["employee_name"], "Judge 3 (DeepSeek)", provider="deepseek"))

    if not tasks:
        return {"error": "No LLM configured for any judge"}

    results = await asyncio.gather(*tasks)

    # Map results to state
    output = {}
    for result in results:
        if "Judge 1" in result.get("judge", ""):
            output["judge_1_result"] = result
        elif "Judge 2" in result.get("judge", ""):
            output["judge_2_result"] = result
        elif "Judge 3" in result.get("judge", ""):
            output["judge_3_result"] = result

    return output


async def main_judge(state: AnalysisState) -> dict:
    """Main judge consolidates results and generates final output. Retries once on failure."""
    settings = get_settings()

    # Gather judge results
    judge_results = []
    if state.get("judge_1_result"):
        judge_results.append(state["judge_1_result"])
    if state.get("judge_2_result"):
        judge_results.append(state["judge_2_result"])
    if state.get("judge_3_result"):
        judge_results.append(state["judge_3_result"])

    if not judge_results:
        return {"error": "No judge results to consolidate"}

    judge_summary = json.dumps(judge_results, ensure_ascii=False, indent=2)

    system_prompt = get_main_judge_system_prompt(
        evaluation_criteria=state.get("evaluation_criteria", ""),
        email_template=state.get("email_template", "")
    )
    user_message = f"""## 员工姓名
{state["employee_name"]}

## 三位评委的评分结果
{judge_summary}

请生成最终评估结果和邮件内容。"""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_message)
    ]

    # Try up to 2 times: kimi-k2-thinking supports json_mode in thinking mode
    for attempt in range(1, 3):
        try:
            main_llm = create_glm_llm(settings, enable_thinking=True, json_mode=True)
            response = await asyncio.wait_for(
                call_with_rate_limit("dashscope", main_llm, messages), timeout=300
            )
            content = response.content
            result = _try_parse_json(content)

            return {
                "final_score": result.get("final_score"),
                "email_content": result.get("email_content"),
                "error": None
            }

        except asyncio.TimeoutError:
            last_error = f"Main judge timeout after 300s (attempt {attempt})"
        except json.JSONDecodeError as e:
            last_error = f"Main judge JSON parse error (attempt {attempt}): {str(e)}"
        except Exception as e:
            last_error = f"Main judge error (attempt {attempt}): {str(e)}"

    return {"error": last_error}


def save_results(state: AnalysisState) -> dict:
    """Save all results to the Record model."""
    try:
        with get_db() as db:
            record = db.query(Record).filter(Record.id == state["record_id"]).first()
            if not record:
                return {"error": f"Record {state['record_id']} not found"}

            # Collect all judge results
            analysis_results = []
            if state.get("judge_1_result"):
                analysis_results.append(state["judge_1_result"])
            if state.get("judge_2_result"):
                analysis_results.append(state["judge_2_result"])
            if state.get("judge_3_result"):
                analysis_results.append(state["judge_3_result"])

            # Save to record
            record.analysis_results = analysis_results
            record.final_score = state.get("final_score")
            record.email_content = state.get("email_content")

            # Update status
            if state.get("error"):
                record.status = RecordStatus.FAILED
                record.error_message = state["error"]
            else:
                record.status = RecordStatus.SCORED

            db.commit()

        return {}

    except Exception as e:
        return {"error": f"Failed to save results: {str(e)}"}


# ============================================================================
# Build LangGraph
# ============================================================================

def build_analysis_graph() -> StateGraph:
    """Build the LangGraph workflow."""
    workflow = StateGraph(AnalysisState)

    # Add nodes
    workflow.add_node("load_context", load_context)
    workflow.add_node("analyze_parallel", analyze_parallel)
    workflow.add_node("main_judge", main_judge)
    workflow.add_node("save_results", save_results)

    # Add edges
    workflow.set_entry_point("load_context")
    workflow.add_edge("load_context", "analyze_parallel")
    workflow.add_edge("analyze_parallel", "main_judge")
    workflow.add_edge("main_judge", "save_results")
    workflow.add_edge("save_results", END)

    return workflow.compile()


# ============================================================================
# Agent Class
# ============================================================================

class AnalysisAgent:
    """Analysis agent that uses LangGraph to orchestrate evaluation."""

    def __init__(self):
        self.graph = build_analysis_graph()

    async def analyze(self, record_id: int, employee_name: str, raw_text: str) -> Dict[str, Any]:
        """Run the full analysis workflow.

        Args:
            record_id: Database record ID
            employee_name: Employee name
            raw_text: Report content (from Excel)

        Returns:
            Dict with final_score, email_content, and any errors
        """
        initial_state: AnalysisState = {
            "record_id": record_id,
            "employee_name": employee_name,
            "raw_text": raw_text,
            "knowledge_content": "",
            "evaluation_criteria": "",
            "email_template": "",
            "judge_1_result": None,
            "judge_2_result": None,
            "judge_3_result": None,
            "final_score": None,
            "email_content": None,
            "error": None
        }

        result = await self.graph.ainvoke(initial_state)
        return result


# Singleton
_analysis_agent: Optional[AnalysisAgent] = None


def get_analysis_agent() -> AnalysisAgent:
    """Get the analysis agent singleton."""
    global _analysis_agent
    if _analysis_agent is None:
        _analysis_agent = AnalysisAgent()
    return _analysis_agent