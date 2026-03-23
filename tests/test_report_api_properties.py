"""Property-based tests for the public report API endpoint.

Tests Properties 4, 5, and 6 from the design document using Hypothesis
and FastAPI's TestClient with an in-memory SQLite database.

**Validates: Requirements 2.3, 2.4, 3.1, 3.2**
"""

import uuid
import json
from datetime import datetime
from unittest.mock import patch
from contextlib import contextmanager

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, Column, String, event
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.models.record import Base, Record, RecordStatus

# ---------------------------------------------------------------------------
# In-memory SQLite test database setup
# ---------------------------------------------------------------------------

# Dynamically add view_token column if the model doesn't have it yet
if not hasattr(Record, "view_token"):
    Record.view_token = Column(String(36), unique=True, index=True, nullable=True)


def _make_engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    return eng


def _make_session(engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


@contextmanager
def _test_db_ctx(session):
    """Context manager matching the signature of app.utils.database.get_db."""
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise


client = TestClient(app)

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

VIEWABLE_STATUSES = [RecordStatus.SCORED, RecordStatus.EMAILING, RecordStatus.DONE]
NON_VIEWABLE_STATUSES = [s for s in RecordStatus if s not in VIEWABLE_STATUSES]

SENSITIVE_FIELDS = {"employee_email", "raw_text", "error_message", "email_content"}

# Strategy for generating judge results with mixed success values
judge_result_st = st.fixed_dictionaries({
    "judge": st.sampled_from(["Judge 1 (Qwen)", "Judge 2 (Doubao)", "Judge 3 (DeepSeek)"]),
    "success": st.booleans(),
    "总分": st.integers(min_value=0, max_value=100),
    "等级": st.sampled_from(["S", "A", "B", "C", "D"]),
})

# Strategy for analysis_results: list of 1-3 judge results
analysis_results_st = st.lists(judge_result_st, min_size=1, max_size=3)

# Strategy for final_score
final_score_st = st.fixed_dictionaries({
    "总分": st.integers(min_value=0, max_value=100),
    "等级": st.sampled_from(["S", "A", "B", "C", "D"]),
})


def _create_record(session, *, status, view_token=None, analysis_results=None, final_score=None):
    """Insert a test Record into the in-memory database."""
    token = view_token or str(uuid.uuid4())
    record = Record(
        feishu_record_id=f"rec_{uuid.uuid4().hex[:12]}",
        employee_name="Test User",
        employee_email="secret@example.com",
        file_token="tok_abc",
        status=status,
        view_token=token,
        raw_text="some raw text",
        error_message="some error",
        email_content="some email content",
        analysis_results=analysis_results,
        final_score=final_score,
    )
    session.add(record)
    session.flush()
    return token


# ---------------------------------------------------------------------------
# Property 5: API 响应不包含敏感字段
# ---------------------------------------------------------------------------


class TestAPISensitiveFieldsExcluded:
    """Property 5: API 响应不包含敏感字段

    For any successful Report_API response, the JSON payload SHALL NOT contain
    the fields employee_email, raw_text, error_message, or email_content.

    **Validates: Requirements 3.1**
    """

    @given(
        status=st.sampled_from(VIEWABLE_STATUSES),
        analysis_results=analysis_results_st,
        final_score=final_score_st,
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_response_never_contains_sensitive_fields(
        self, status, analysis_results, final_score
    ):
        engine = _make_engine()
        session = _make_session(engine)
        try:
            token = _create_record(
                session,
                status=status,
                analysis_results=analysis_results,
                final_score=final_score,
            )
            session.commit()

            with patch("app.routers.report.get_db", return_value=_test_db_ctx(session)):
                resp = client.get(f"/api/report/{token}")

            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
            body = resp.json()

            # Recursively collect all keys in the response
            all_keys = _collect_all_keys(body)
            found_sensitive = all_keys & SENSITIVE_FIELDS
            assert not found_sensitive, (
                f"Response contains sensitive fields: {found_sensitive}"
            )
        finally:
            session.close()
            engine.dispose()


# ---------------------------------------------------------------------------
# Property 4: 不可查看场景返回 404
# ---------------------------------------------------------------------------


class TestAPIStatusFiltering:
    """Property 4: 不可查看场景返回 404

    For any view_token that either does not exist in the database or corresponds
    to a Record whose status is not in Viewable_Status, the Report_API SHALL
    return HTTP 404.

    **Validates: Requirements 2.3, 2.4**
    """

    @given(status=st.sampled_from(NON_VIEWABLE_STATUSES))
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_non_viewable_status_returns_404(self, status):
        """Records with non-viewable status must return 404."""
        engine = _make_engine()
        session = _make_session(engine)
        try:
            token = _create_record(session, status=status)
            session.commit()

            with patch("app.routers.report.get_db", return_value=_test_db_ctx(session)):
                resp = client.get(f"/api/report/{token}")

            assert resp.status_code == 404, (
                f"Expected 404 for status {status.value}, got {resp.status_code}"
            )
        finally:
            session.close()
            engine.dispose()

    @given(st.uuids())
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_nonexistent_token_returns_404(self, random_uuid):
        """A token that doesn't exist in the DB must return 404."""
        engine = _make_engine()
        session = _make_session(engine)
        try:
            # Empty database — no records at all
            with patch("app.routers.report.get_db", return_value=_test_db_ctx(session)):
                resp = client.get(f"/api/report/{random_uuid}")

            assert resp.status_code == 404, (
                f"Expected 404 for nonexistent token, got {resp.status_code}"
            )
        finally:
            session.close()
            engine.dispose()


# ---------------------------------------------------------------------------
# Property 6: 仅返回成功的评委结果
# ---------------------------------------------------------------------------


class TestAPIJudgeResultFiltering:
    """Property 6: 仅返回成功的评委结果

    For any successful Report_API response, every element in the
    analysis_results array SHALL have success equal to true.

    **Validates: Requirements 3.2**
    """

    @given(
        status=st.sampled_from(VIEWABLE_STATUSES),
        analysis_results=analysis_results_st,
        final_score=final_score_st,
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_all_returned_judge_results_are_successful(
        self, status, analysis_results, final_score
    ):
        engine = _make_engine()
        session = _make_session(engine)
        try:
            token = _create_record(
                session,
                status=status,
                analysis_results=analysis_results,
                final_score=final_score,
            )
            session.commit()

            with patch("app.routers.report.get_db", return_value=_test_db_ctx(session)):
                resp = client.get(f"/api/report/{token}")

            assert resp.status_code == 200
            body = resp.json()
            for idx, judge in enumerate(body.get("analysis_results", [])):
                assert judge.get("success") is True, (
                    f"analysis_results[{idx}] has success={judge.get('success')}, "
                    f"expected True. Input had: {analysis_results}"
                )
        finally:
            session.close()
            engine.dispose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_all_keys(obj) -> set:
    """Recursively collect all dictionary keys in a JSON-like structure."""
    keys = set()
    if isinstance(obj, dict):
        keys.update(obj.keys())
        for v in obj.values():
            keys.update(_collect_all_keys(v))
    elif isinstance(obj, list):
        for item in obj:
            keys.update(_collect_all_keys(item))
    return keys
