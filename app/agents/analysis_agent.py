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
from langchain_community.chat_models import ChatTongyi
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END

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
    "报告亮点": ["亮点1：具体的洞察或发现", "亮点2：..."],
    "产品痛点总结": ["痛点1：用户反馈的产品问题", "痛点2：..."],
    "期望功能总结": ["期望1：用户希望增加的功能", "期望2：..."]
  }},
  "judgment_notes": "裁决说明...",
  "email_content": "邮件内容（Markdown格式，中英双语）..."
}}

注意：
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
    judge_name: str
) -> Dict[str, Any]:
    """Call a single judge LLM."""
    try:
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"## 员工姓名\n{employee_name}\n\n## 报告内容\n{raw_text}")
        ]

        response = await llm.ainvoke(messages)
        content = response.content

        # Parse JSON response
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        result = json.loads(content.strip())
        result["judge"] = judge_name
        result["success"] = True

        return result

    except json.JSONDecodeError as e:
        return {
            "judge": judge_name,
            "success": False,
            "error": f"JSON parse error: {str(e)}",
            "raw_response": content if 'content' in dir() else None
        }
    except Exception as e:
        return {
            "judge": judge_name,
            "success": False,
            "error": str(e)
        }


async def analyze_parallel(state: AnalysisState) -> dict:
    """Call 3 judges in parallel."""
    settings = get_settings()

    # Initialize LLMs
    try:
        judge_1_llm = ChatTongyi(
            model="qwen3-max",
            dashscope_api_key=settings.dashscope_api_key,
            temperature=0.3
        )
    except Exception:
        judge_1_llm = None

    try:
        judge_2_llm = ChatOpenAI(
            model="gpt-5.4-mini",
            api_key=settings.openai_api_key,
            temperature=0.3
        )
    except Exception:
        judge_2_llm = None

    try:
        judge_3_llm = ChatOpenAI(
            model="deepseek-chat",
            api_key=settings.deepseek_api_key,
            base_url="https://api.deepseek.com/v1",
            temperature=0.3
        )
    except Exception:
        judge_3_llm = None

    # Build system prompt with both knowledge AND criteria
    system_prompt = get_judge_system_prompt(
        state.get("knowledge_content", ""),
        state.get("evaluation_criteria", "")
    )

    # Call judges in parallel
    tasks = []
    if judge_1_llm:
        tasks.append(call_judge(judge_1_llm, system_prompt, state["raw_text"], state["employee_name"], "Judge 1 (Qwen)"))
    if judge_2_llm:
        tasks.append(call_judge(judge_2_llm, system_prompt, state["raw_text"], state["employee_name"], "Judge 2 (OpenAI)"))
    if judge_3_llm:
        tasks.append(call_judge(judge_3_llm, system_prompt, state["raw_text"], state["employee_name"], "Judge 3 (DeepSeek)"))

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
    """Main judge consolidates results and generates final output."""
    settings = get_settings()

    main_llm = ChatTongyi(
        model="qwen3-max",
        dashscope_api_key=settings.dashscope_api_key,
        temperature=0.3
    )

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

    # Get system prompt with evaluation criteria and email template
    system_prompt = get_main_judge_system_prompt(
        evaluation_criteria=state.get("evaluation_criteria", ""),
        email_template=state.get("email_template", "")
    )
    user_message = f"""## 员工姓名
{state["employee_name"]}

## 三位评委的评分结果
{judge_summary}

请生成最终评估结果和邮件内容。"""

    try:
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message)
        ]

        response = await main_llm.ainvoke(messages)
        content = response.content

        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        result = json.loads(content.strip())

        return {
            "final_score": result.get("final_score"),
            "email_content": result.get("email_content"),
            "error": None
        }

    except json.JSONDecodeError as e:
        return {"error": f"Main judge JSON parse error: {str(e)}"}
    except Exception as e:
        return {"error": f"Main judge error: {str(e)}"}


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