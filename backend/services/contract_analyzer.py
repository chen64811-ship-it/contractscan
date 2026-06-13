"""
合同风险分析引擎
将合同文本发送给 LLM，识别风险条款 + 缺失条款，返回结构化分析结果

v2: 拆分为两次 API 调用，解决 DeepSeek 返回 {} 的 bug
    - 调用1：识别现有风险条款
    - 调用2：检查缺失条款
    - 在本地计算风险评分（不依赖 LLM 算分）
"""
import json
import re
from openai import OpenAI

# 标准合同应包含的条款清单
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

# ── 调用1：识别现有风险条款（提示词短，DeepSeek 能稳定返回）──
RISK_SYSTEM_PROMPT = """You are a senior contract attorney reviewing a contract.

For EVERY clause in the contract that poses a risk to the client, flag it. Return ONLY valid JSON:

{
  "risks": [
    {
      "clause_text": "exact quote from contract",
      "risk_level": "high",
      "explanation": "Why dangerous (1 sentence)",
      "suggestion": "How to negotiate (1 sentence)"
    }
  ]
}

Risk levels: "high" (unacceptable — e.g. one-sided indemnity, IP grab, no termination rights), "medium" (concerning — e.g. high late fees, short confidentiality), "low" (minor — e.g. slightly imbalanced notice periods).

Be thorough. Flag EVERY risky clause. Return ONLY valid JSON."""

# ── 调用2：检查缺失条款 ──
MISSING_SYSTEM_PROMPT = f"""You are a senior contract attorney. Compare this contract against the standard checklist below.

For each clause in the checklist that is MISSING or significantly incomplete, flag it.

Standard checklist:
{chr(10).join(f"- {c}" for c in STANDARD_CLAUSES)}

Return ONLY valid JSON:

{{
  "missing_clauses": [
    {{
      "clause_name": "Intellectual Property",
      "risk_level": "high",
      "why_matters": "Without IP assignment, client may not own deliverables (1 sentence)",
      "suggested_language": "Suggested clause text (1 sentence)"
    }}
  ]
}}

Risk levels for missing clauses:
- "high": business-critical gap (no IP, no termination, no liability cap, no confidentiality)
- "medium": important gap (no indemnity, no dispute resolution, no data protection)
- "low": minor gap (no force majeure, no severability, no notice provisions)

ONLY flag clauses that are truly missing. Do NOT flag clauses that exist but could be improved — those go in the risks section elsewhere.
Return ONLY valid JSON."""


def _build_client(api_key: str, api_base: str) -> OpenAI:
    return OpenAI(api_key=api_key, base_url=api_base, timeout=60.0, max_retries=2)


def _clean_json_response(raw: str) -> str:
    """清理 LLM 返回的 JSON"""
    match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', raw)
    if match:
        raw = match.group(1)
    raw = raw.strip()
    if raw.startswith('"') and raw.endswith('"'):
        raw = raw[1:-1]
    return raw


def _call_llm(client: OpenAI, model: str, system_prompt: str, user_prompt: str, label: str = "") -> dict:
    """调用 LLM 并解析 JSON"""
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=4096,
        response_format={"type": "json_object"},
    )
    raw_output = response.choices[0].message.content or "{}"
    cleaned = _clean_json_response(raw_output)

    import sys
    print(f"[{label}] Raw length: {len(raw_output)}, first 200: {raw_output[:200]}", file=sys.stderr)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        print(f"[{label}] JSON PARSE FAILED. Cleaned first 300: {cleaned[:300]}", file=sys.stderr)
        return {}


def _compute_score(risks: list, missing: list) -> tuple:
    """基于风险条款和缺失条款计算总分"""
    score = 0
    high_risks = 0
    med_risks = 0
    low_risks = 0

    for r in risks:
        level = (r.get("risk_level") or "low").lower()
        if level == "high":
            score += 15
            high_risks += 1
        elif level == "medium":
            score += 8
            med_risks += 1
        else:
            score += 3
            low_risks += 1

    for m in missing:
        level = (m.get("risk_level") or "low").lower()
        if level == "high":
            score += 20
            high_risks += 1
        elif level == "medium":
            score += 10
            med_risks += 1
        else:
            score += 4
            low_risks += 1

    return min(score, 100), high_risks, med_risks, low_risks


def analyze_contract(
    contract_text: str,
    api_key: str,
    api_base: str = "https://api.deepseek.com",
    model: str = "deepseek-chat",
    max_chars: int = 12000,
) -> dict:
    """
    分析合同文本，返回风险 + 缺失条款分析

    分两次调用 DeepSeek：
    1. 识别现有风险条款
    2. 检查缺失条款
    3. 本地计算风险评分（不依赖 LLM）
    """
    if len(contract_text) > max_chars:
        contract_text = contract_text[:max_chars] + f"\n\n[Contract truncated at {max_chars} characters]"

    client = _build_client(api_key, api_base)
    user_prompt = f"Review this contract:\n\n{contract_text}"

    # 调用1：识别风险条款
    risk_result = _call_llm(client, model, RISK_SYSTEM_PROMPT, user_prompt, label="RISK")
    risks = risk_result.get("risks", [])

    # 调用2：检查缺失条款
    missing_result = _call_llm(client, model, MISSING_SYSTEM_PROMPT, user_prompt, label="MISSING")
    missing_clauses = missing_result.get("missing_clauses", [])

    # 本地计算评分
    score, high_count, med_count, low_count = _compute_score(risks, missing_clauses)

    # 构建摘要
    risk_count = len(risks)
    missing_count = len(missing_clauses)
    parts = []
    if risk_count > 0:
        parts.append(f"{risk_count} risky clause{'s' if risk_count != 1 else ''}")
    if missing_count > 0:
        parts.append(f"{missing_count} missing provision{'s' if missing_count != 1 else ''}")

    if parts:
        summary = f"This contract has {' and '.join(parts)}. Score based on {high_count} high, {med_count} medium, and {low_count} low severity items."
    else:
        summary = "No significant risks or missing clauses detected. This contract appears well-drafted and balanced."

    return {
        "overall_risk_score": score,
        "summary": summary,
        "risks": risks,
        "missing_clauses": missing_clauses,
    }
