from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class RequestLog(Base):
    __tablename__ = "request_logs"
 
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class SupportFaqEntry(Base):
    __tablename__ = "support_faq_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="manual",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class SupportFaqQueryMetric(Base):
    __tablename__ = "support_faq_query_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_question: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    matched_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    relevance_avg: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    relevance_max: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    zero_match: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="support_faq")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
