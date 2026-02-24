"""V10: CopilotService — 对话式 AI 助理（Trading Copilot）"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = logging.getLogger(__name__)

# 操作意图关键词映射
INTENT_PATTERNS = [
    # (pattern, intent_type)
    (r"把\s*(\w+)\s*止损.*?(\d+\.?\d*)", "modify_stop"),
    (r"买[入]?\s*(\w+)\s*(\d+)\s*[股份]", "place_order"),
    (r"卖[出]?\s*(\w+)\s*(\d+)?\s*[股份]?", "place_order"),
    (r"平[仓]?\s*所有|清仓", "close_all"),
    (r"暂停\s*AI|停止自主", "pause_autonomy"),
]


class CopilotService:
    """对话式 AI，支持自然语言查询 + 操作意图识别"""

    async def chat(
        self,
        account_id: str,
        session_id: str,
        message: str,
        db: Optional[AsyncSession] = None,
    ) -> dict:
        """
        处理用户消息，返回 AI 回复
        自动路由：查询类→轻量模型，复杂/操作类→复杂模型
        """
        is_complex = self._is_complex_query(message)
        model_type = "complex" if is_complex else "lightweight"

        # 构建对话历史
        history = await self._get_history(account_id, session_id, db)
        context = await self._build_context(account_id)

        prompt = self._build_system_prompt(context)
        messages = [{"role": "system", "content": prompt}]
        # 加入最近 10 条历史
        for msg in history[-10:]:
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": message})

        # 调用 AI
        raw_response, model_used, tokens = await self._call_ai(messages, model_type)

        # 意图检测
        action_intent = self._detect_intent(message, raw_response)

        # 持久化
        if db:
            await self._save_messages(db, account_id, session_id, message, raw_response, model_used, action_intent, tokens)

        response = {
            "message": raw_response,
            "session_id": session_id,
            "model_used": model_used,
            "tokens_used": tokens,
            "action_intent": action_intent,
            "requires_confirmation": action_intent is not None,
        }
        return response

    async def morning_brief(self, account_id: str) -> dict:
        """每日 08:15 生成盘前摘要 (V10 structured)"""
        context = await self._build_context(account_id)
        prompt = f"""你是专业量化交易 AI，请基于以下信息生成今日盘前交易摘要。

当前状态：{json.dumps(context, ensure_ascii=False, indent=2)}

请务必按以下 JSON 格式输出：
{{
  "date": "YYYY-MM-DD",
  "summary": "概要描述",
  "market_outlook": "市场展望",
  "top_signals": [
    {{"symbol": "AAPL", "action": "BUY", "reason": "突破压力位"}}
  ],
  "risk_alerts": ["波动率上升", "关键支撑位跌破"]
}}
仅输出 JSON。"""

        messages = [{"role": "user", "content": prompt}]
        raw_response, _, _ = await self._call_ai(messages, "complex")
        
        try:
            # 简单提取 JSON
            match = re.search(r"(\{.*\})", raw_response, re.DOTALL)
            if match:
                return json.loads(match.group(1))
            return {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "summary": raw_response[:200] + "...",
                "market_outlook": "AI 正在分析中...",
                "top_signals": [],
                "risk_alerts": []
            }
        except Exception:
            return {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "summary": "解析摘要失败",
                "market_outlook": raw_response,
                "top_signals": [],
                "risk_alerts": []
            }

    async def confirm_action(
        self, account_id: str, action_id: str, db: AsyncSession
    ) -> dict:
        """执行 Copilot 检测到的操作意图（须人工确认）"""
        from sqlalchemy import text

        row = await db.execute(
            text("SELECT action_intent FROM copilot_messages WHERE id=:id AND account_id=:aid"),
            {"id": int(action_id), "aid": account_id},
        )
        record = row.fetchone()
        if not record or not record[0]:
            return {"success": False, "reason": "Action not found"}

        intent = record[0] if isinstance(record[0], dict) else json.loads(record[0])

        # 根据意图类型执行
        if intent["type"] == "modify_stop":
            # TODO: 调用 order_service.modify_stop_loss
            pass
        elif intent["type"] == "place_order":
            # TODO: 调用 twap_vwap_service.submit
            pass
        elif intent["type"] == "close_all":
            # TODO: 调用 position_service.close_all
            pass
        elif intent["type"] == "pause_autonomy":
            # TODO: 更新 settings.AI_AUTONOMY_LEVEL = "ADVISORY"
            pass

        # 标记已确认
        await db.execute(
            text("UPDATE copilot_messages SET action_confirmed=1 WHERE id=:id"),
            {"id": int(action_id)},
        )
        await db.commit()

        return {"success": True, "action_type": intent["type"], "params": intent.get("params", {})}

    # ──────────────────────────────────────────
    # 内部方法
    # ──────────────────────────────────────────

    def _is_complex_query(self, message: str) -> bool:
        """判断是否需要复杂推理模型"""
        complex_keywords = ["分析", "评估", "策略", "优化", "为什么", "怎么", "建议", "风险", "回测"]
        return any(kw in message for kw in complex_keywords)

    def _detect_intent(self, user_msg: str, ai_response: str) -> Optional[dict]:
        """从用户消息检测操作意图"""
        for pattern, intent_type in INTENT_PATTERNS:
            m = re.search(pattern, user_msg)
            if m:
                return {"type": intent_type, "params": {"matched": m.groups()}}
        return None

    async def _build_context(self, account_id: str) -> dict:
        """构建账户上下文摘要（简化）"""
        return {
            "account_id": account_id,
            "date": date.today().isoformat(),
            "autonomy_level": settings.AI_AUTONOMY_LEVEL,
        }

    def _build_system_prompt(self, context: dict) -> str:
        return f"""你是 Trading Copilot，一个专业的量化交易 AI 助理。
当前账户信息：{json.dumps(context, ensure_ascii=False)}
规则：
1. 对查询类问题直接回答
2. 对操作类请求（下单、止损等），先确认意图再标注"需要确认"
3. 对风险超标的操作，警告并拒绝
4. 所有回复使用中文，简洁专业"""

    async def _get_history(self, account_id: str, session_id: str, db: Optional[AsyncSession]) -> list:
        if not db:
            return []
        from sqlalchemy import text

        result = await db.execute(
            text(
                "SELECT role, content FROM copilot_messages "
                "WHERE account_id=:aid AND session_id=:sid ORDER BY created_at LIMIT 20"
            ),
            {"aid": account_id, "sid": session_id},
        )
        return [{"role": r[0], "content": r[1]} for r in result.fetchall()]

    async def _save_messages(
        self,
        db: AsyncSession,
        account_id: str,
        session_id: str,
        user_msg: str,
        ai_msg: str,
        model_used: str,
        action_intent: Optional[dict],
        tokens: int,
    ) -> None:
        from app.models.copilot_message import CopilotMessage

        db.add(CopilotMessage(account_id=account_id, session_id=session_id, role="user", content=user_msg, model_used=model_used))
        db.add(CopilotMessage(account_id=account_id, session_id=session_id, role="assistant", content=ai_msg, model_used=model_used, action_intent=action_intent, tokens_used=tokens))
        await db.commit()

    async def _call_ai(self, messages: list, model_type: str = "lightweight") -> tuple[str, str, int]:
        """返回 (response_text, model_name, tokens_used)"""
        from openai import AsyncOpenAI

        model = settings.AI_COMPLEX_MODEL if model_type == "complex" else settings.AI_LIGHTWEIGHT_MODEL

        if settings.DEEPSEEK_API_KEY and "deepseek" in model:
            client = AsyncOpenAI(
                api_key=settings.DEEPSEEK_API_KEY,
                base_url=settings.DEEPSEEK_API_BASE,
                timeout=settings.DEEPSEEK_TIMEOUT_SECONDS,
            )
        else:
            client = AsyncOpenAI(
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_API_BASE,
                timeout=settings.OPENAI_TIMEOUT_SECONDS,
            )

        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=1500,
        )
        content = resp.choices[0].message.content or ""
        tokens = getattr(resp.usage, "total_tokens", 0)
        return content, model, int(tokens)


# 全局单例
copilot_service = CopilotService()
