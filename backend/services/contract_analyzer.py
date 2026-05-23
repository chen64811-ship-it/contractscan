"""
合同风险分析引擎
将合同文本发送给 LLM，识别风险条款，返回结构化分析结果
"""
import json
import re
from typing import Optional
from openai import OpenAI


# LLM System Prompt：告诉 AI 它是什么角色、输出什么格式
SYSTEM_PROMPT = """You are a professional contract risk analyst. Your task is to review contract text and identify risky or unusual clauses.

For each risk you find, provide:
1. The exact clause text (quote from the contract)
2. Risk level: "high", "medium", or "low"
3. Explanation: why this clause is risky (1-2 sentences in plain English)
4. Suggestion: how to fix or negotiate this clause (1-2 sentences)

Also calculate:
- overall_risk_score: 0-100 (0 = perfectly safe, 100 = extremely risky)
- summary: a 2-3 sentence overall assessment of the contract

IMPORTANT: Return ONLY valid JSON in this exact format, no other text:
{
  "overall_risk_score": 45,
  "summary": "Overall assessment here.",
  "risks": [
    {
      "clause_text": "exact quote from contract...",
      "risk_level": "high",
      "explanation": "Why this is risky.",
      "suggestion": "How to fix it."
    }
  ]
}

If no risks are found, return an empty risks array and a low risk score.
Only report genuine legal/financial risks. Do NOT flag standard boilerplate clauses."""


def _build_client(api_key: str, api_base: str) -> OpenAI:
    """根据配置创建 OpenAI 兼容客户端（支持 DeepSeek、MiniMax 等）"""
    return OpenAI(api_key=api_key, base_url=api_base)


def _clean_json_response(raw: str) -> str:
    """清理 LLM 返回的 JSON（去除 markdown 代码块标记等）"""
    # 去掉 ```json ... ``` 包裹
    match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', raw)
    if match:
        raw = match.group(1)
    # 去掉前后空白
    raw = raw.strip()
    return raw


def analyze_contract(
    contract_text: str,
    api_key: str,
    api_base: str = "https://api.deepseek.com",
    model: str = "deepseek-chat",
    max_chars: int = 12000,
) -> dict:
    """
    分析合同文本，返回风险分析结果

    参数:
        contract_text: 合同全文
        api_key: LLM API Key
        api_base: API 地址（默认 DeepSeek）
        model: 模型名称
        max_chars: 发送给 LLM 的最大字符数（防止超 token 限制）

    返回:
        {
            "overall_risk_score": int,
            "summary": str,
            "risks": [
                {
                    "clause_text": str,
                    "risk_level": "high/medium/low",
                    "explanation": str,
                    "suggestion": str
                }
            ]
        }
    """
    # 截断过长文本（大部分合同分析不需要全文，前12000字足够覆盖关键条款）
    if len(contract_text) > max_chars:
        contract_text = contract_text[:max_chars] + "\n\n[合同内容过长，已截断至前{max_chars}字符]"

    client = _build_client(api_key, api_base)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Please analyze the following contract and identify any risky clauses:\n\n{contract_text}"},
        ],
        temperature=0.3,  # 低温度 = 更稳定、更少瞎编
        max_tokens=4096,
    )

    raw_output = response.choices[0].message.content or "{}"

    # 清理并解析 JSON
    cleaned = _clean_json_response(raw_output)
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        # 如果 LLM 返回格式不对，返回一个兜底结果
        return {
            "overall_risk_score": 0,
            "summary": "分析失败：AI 返回格式异常，请重试。",
            "risks": [],
            "raw_response": raw_output,  # 保留原始返回，方便调试
        }

    # 确保返回结构完整
    result.setdefault("overall_risk_score", 0)
    result.setdefault("summary", "")
    result.setdefault("risks", [])

    return result


def analyze_clause(
    clause_text: str,
    api_key: str,
    api_base: str = "https://api.deepseek.com",
    model: str = "deepseek-chat",
) -> dict:
    """
    分析单条合同条款（用于用户选中某条条款单独分析）
    返回与 analyze_contract 相同的结构，但只分析这一条
    """
    prompt = f"Please analyze this single contract clause and identify any risks:\n\n{clause_text}"
    return analyze_contract(prompt, api_key, api_base, model, max_chars=5000)
