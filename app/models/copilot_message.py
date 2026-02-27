"""V10: Trading Copilot 对话消息模型"""
from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, Integer, JSON, Text, text, Index
from app.models.db import Base


class CopilotMessage(Base):
    __tablename__ = "copilot_messages"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    account_id = Column(String(64), nullable=False)
    session_id = Column(String(64), nullable=False)
    role = Column(String(16), nullable=False, comment="user/assistant/system")
    content = Column(Text, nullable=False)
    model_used = Column(String(64), nullable=True)
    action_intent = Column(JSON, nullable=True, comment='{"type":"modify_stop","params":{...}}')
    action_confirmed = Column(Boolean, nullable=True, default=None)
    tokens_used = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        Index("idx_copilot_account_session", "account_id", "session_id"),
        Index("idx_copilot_created", "created_at"),
    )
