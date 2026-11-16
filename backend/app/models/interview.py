"""模拟面试独立数据结构；不复用普通聊天。"""
from datetime import datetime
from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, ForeignKeyConstraint, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base
from app.models.chat import new_id


class InterviewPreset(Base):
    __tablename__ = 'interview_presets'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    __table_args__ = (CheckConstraint("kind IN ('bank','role')", name='ck_ip_kind'), CheckConstraint('version > 0', name='ck_ip_version'))


class InterviewQuestionBank(Base):
    __tablename__ = 'interview_question_bank'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    preset_id: Mapped[str] = mapped_column(ForeignKey('interview_presets.id', ondelete='RESTRICT'), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    topic: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    __table_args__ = (CheckConstraint('version > 0', name='ck_iqb_version'),)


class Interview(Base):
    __tablename__ = 'interviews'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='pending', index=True)
    create_key: Mapped[str | None] = mapped_column(String(100), unique=True)
    create_hash: Mapped[str | None] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    preset_id: Mapped[str | None] = mapped_column(ForeignKey('interview_presets.id', ondelete='RESTRICT'))
    preset_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    config_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    jd: Mapped[str | None] = mapped_column(Text)
    limit_type: Mapped[str] = mapped_column(String(10), nullable=False)
    main_limit: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_reason: Mapped[str | None] = mapped_column(String(100))
    main_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_main_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint("status IN ('pending','in_progress','completed','terminated','interrupted')", name='ck_iv_status'),
        CheckConstraint("mode IN ('practice','formal')", name='ck_iv_mode'),
        CheckConstraint("(limit_type='count' AND main_limit IS NOT NULL AND main_limit > 0 AND duration_seconds IS NULL) OR (limit_type='time' AND duration_seconds IS NOT NULL AND duration_seconds > 0 AND main_limit IS NULL)", name='ck_iv_limit'),
        CheckConstraint('main_count >= 0 AND valid_main_count >= 0 AND valid_main_count <= main_count AND version >= 0', name='ck_iv_counts'),
        CheckConstraint("(status='pending' AND started_at IS NULL AND ended_at IS NULL) OR (status='in_progress' AND started_at IS NOT NULL AND ended_at IS NULL) OR (status IN ('completed','terminated','interrupted') AND started_at IS NOT NULL AND ended_at IS NOT NULL)", name='ck_iv_times'),
    )


class InterviewQuestion(Base):
    __tablename__ = 'interview_questions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    interview_id: Mapped[str] = mapped_column(ForeignKey('interviews.id', ondelete='CASCADE'), nullable=False, index=True)
    parent_id: Mapped[str | None] = mapped_column(String(36))
    main_number: Mapped[int] = mapped_column(Integer, nullable=False)
    depth: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        UniqueConstraint('interview_id', 'id', name='uq_iq_interview_id'),
        UniqueConstraint('interview_id', 'main_number', 'position', name='uq_iq_sequence'),
        ForeignKeyConstraint(['interview_id','parent_id'], ['interview_questions.interview_id','interview_questions.id'], name='fk_iq_parent', ondelete='CASCADE'),
        CheckConstraint('main_number > 0 AND depth BETWEEN 0 AND 2 AND position BETWEEN 0 AND 2', name='ck_iq_position_v2'),
        CheckConstraint('(depth = 0 AND position = 0 AND parent_id IS NULL) OR (depth > 0 AND position > 0 AND parent_id IS NOT NULL)', name='ck_iq_parent'),
    )


class InterviewAnswer(Base):
    __tablename__ = 'interview_answers'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    interview_id: Mapped[str] = mapped_column(ForeignKey('interviews.id', ondelete='CASCADE'), nullable=False, index=True)
    question_id: Mapped[str] = mapped_column(String(36), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    request_id: Mapped[str] = mapped_column(String(100), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(['interview_id','question_id'], ['interview_questions.interview_id','interview_questions.id'], name='fk_ia_question', ondelete='CASCADE'),
        UniqueConstraint('question_id', name='uq_ia_question'), UniqueConstraint('interview_id','request_id', name='uq_ia_request'),
        CheckConstraint("(kind='answer' AND length(trim(content)) > 0) OR (kind='skip' AND content='')", name='ck_ia_content'),
    )


class InterviewReport(Base):
    __tablename__ = 'interview_reports'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    interview_id: Mapped[str] = mapped_column(ForeignKey('interviews.id', ondelete='CASCADE'), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='not_requested')
    text_review: Mapped[str | None] = mapped_column(Text)
    overall_score: Mapped[float | None] = mapped_column(Float)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint('interview_id', 'type', name='uq_ir_type'), CheckConstraint("type IN ('full','partial')", name='ck_ir_type'), CheckConstraint("status IN ('not_requested','generating','ready','failed')", name='ck_ir_status'), CheckConstraint("type != 'partial' OR overall_score IS NULL", name='ck_ir_partial_score'))


class InterviewOperation(Base):
    __tablename__ = 'interview_operations'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    interview_id: Mapped[str] = mapped_column(ForeignKey('interviews.id', ondelete='CASCADE'), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    request_id: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    result: Mapped[dict | None] = mapped_column(JSON)
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(60))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default='0')
    __table_args__ = (UniqueConstraint('interview_id','request_id', name='uq_io_request'), CheckConstraint("status IN ('pending','running','complete','failed')", name='ck_io_status'))


class InterviewAIArtifact(Base):
    __tablename__ = 'interview_ai_artifacts'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    interview_id: Mapped[str] = mapped_column(ForeignKey('interviews.id', ondelete='CASCADE'), nullable=False, index=True)
    operation_id: Mapped[str] = mapped_column(ForeignKey('interview_operations.id', ondelete='CASCADE'), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (UniqueConstraint('interview_id', 'kind', 'target_id', name='uq_iai_target'), CheckConstraint("kind IN ('followup','feedback','report')", name='ck_iai_kind'))
