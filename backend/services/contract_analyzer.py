"""
合同风险分析引擎
将合同文本发送给 LLM，识别风险条款 + 缺失条款，返回结构化分析结果
"""
import json
import re
from openai import OpenAI


# 标准合同应包含的条款清单（LLM 对照此清单逐项检查）
STANDARD_CLAUSES = [
    "Parties & Effective Date",
    "Scope of Work / Statement of Work (SOW)",
    "Payment Terms & Schedule",
    "Term & Termination (including termination for convenience and for cause)",
    "Intellectual Property Ownership & Assignment",
    "Confidentiality / Non-Disclosure",
    "Indemnification (mutual or one-sided)",
    "Limitation of Liability",
    "Warranties & Representations",
    "Dispute Resolution (arbitration vs litigation, venue, governing law)",
    "Force Majeure",
    "Insurance Requirements",
    "Data Protection & Privacy",
    "Non-Compete / Non-Solicitation",
    "Assignment & Subcontracting",
    "Entire Agreement Clause",
    "Severability",
    "Amendment & Modification",
    "Notice Provisions",
    "Survival of Obligations",
]

SYSTEM_PROMPT = f"""You are a senior contract attorney reviewing a contract for a client. Do TWO things:

PART A — Risky Clauses (existing text):
Scan every clause in the contract. For each one that poses a risk to the client, flag it with:
1. The exact clause text quoted from the contract
2. Risk level: "high", "medium", or "low"
3. Explanation: why this is dangerous (plain English, 1-2 sentences)
4. Suggestion: how to negotiate or fix it (1-2 sentences)

PART B — Missing Clauses (gaps):
Compare this contract against the standard checklist below. For each standard clause that is MISSING or significantly incomplete, flag it with:
1. Clause name from the checklist
2. Risk level: "high" (business-critical gap), "medium" (important gap), "low" (minor gap)
3. Why it matters: what the client risks by not having this clause (1 sentence)
4. Suggested language: a 1-sentence template of what should be added

Standard contract checklist (check EVERY item):
{chr(10).join(f"- {c}" for c in STANDARD_CLAUSES)}

Scoring rules:
- overall_risk_score: 0-100
  - Each HIGH-risk existing clause: +15 points
  - Each MEDIUM-risk existing clause: +8 points
  - Each LOW-risk existing clause: +3 points
  - Each HIGH-risk missing clause: +20 points
  - Each MEDIUM-risk missing clause: +10 points
  - Each LOW-risk missing clause: +4 points
  - Cap at 100. Be honest — don't inflate or deflate.
- summary: 2-3 sentence overall assessment. Mention both "X clause issues found" AND "Y critical clauses missing."

Return ONLY valid JSON, no markdown, no backticks:
{{
  "overall_risk_score": 65,
  "summary": "This contract has 3 risky clauses and is missing 5 critical provisions including IP ownership and termination rights.",
  "risks": [
    {{
      "clause_text": "exact quote...",
      "risk_level": "high",
      "explanation": "Why risky.",
      "suggestion": "How to fix."
    }}
  ],
  "missing_clauses": [
    {{
      "clause_name": "Intellectual Property",
      "risk_level": "high",
      "why_matters": "Without IP assignment, the client may not own the deliverables they paid $50,000 for.",
      "suggested_language": "All work product created under this Agreement shall be owned exclusively by the Client as work-made-for-hire."
    }}
  ]
}}"""


def _build_client(api_key: str, api_base: str) -> OpenAI:
    """根据配置创建 OpenAI 兼容客户端"""
    return OpenAI(api_key=api_key, base_url=api_base)


def _clean_json_response(raw: str) -> str:
    """清理 LLM 返回的 JSON"""
    match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', raw)
    if match:
        raw = match.group(1)
    raw = raw.strip()
    if raw.startswith('"') and raw.endswith('"'):
        raw = raw[1:-1]
    return raw


def analyze_contract(
    contract_text: str,
    api_key: str,
    api_base: str = "https://api.deepseek.com",
    model: str = "deepseek-chat",
    max_chars: int = 12000,
) -> dict:
    """
    分析合同文本，返回风险 + 缺失条款分析
    返回:
        {
            "overall_risk_score": int,
            "summary": str,
            "risks": [{clause_text, risk_level, explanation, suggestion}],
            "missing_clauses": [{clause_name, risk_level, why_matters, suggested_language}]
        }
    """
    if len(contract_text) > max_chars:
        contract_text = contract_text[:max_chars] + f"\n\n[Contract truncated at {max_chars} characters]"

    client = _build_client(api_key, api_base)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Review this contract per the instructions above. Be thorough — check every clause in the checklist:\n\n{contract_text}"},
        ],
        temperature=0.3,
        max_tokens=4096,
    )

    raw_output = response.choices[0].message.content or "{}"
    cleaned = _clean_json_response(raw_output)

    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        return {
            "overall_risk_score": 0,
            "summary": "Analysis failed: AI returned an invalid format. Please try again.",
            "risks": [],
            "missing_clauses": [],
            "raw_response": raw_output,
        }

    result.setdefault("overall_risk_score", 0)
    result.setdefault("summary", "")
    result.setdefault("risks", [])
    result.setdefault("missing_clauses", [])

    return result
