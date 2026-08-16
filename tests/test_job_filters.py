"""
Unit tests for core/job_filters.py.
"""

import pytest
from core.job_filters import (
    evaluate_job,
    extract_salary,
    extract_location,
    check_negative_intent,
    check_hiring_intent,
    check_restrictive_visa,
)


def test_full_stack_backend_match():
    text = (
        "[HIRING] We are looking for a Senior Full Stack Developer to build our SaaS platform. "
        "Must have experience with Next.js, TypeScript, PostgreSQL, and building REST APIs. "
        "Compensation: $110,000 - $140,000 / year. Remote - Worldwide."
    )
    job = evaluate_job(text, author="TechFounder", link="https://x.com/post/1")
    assert job is not None
    assert job.track_id == "FULL_STACK_BACKEND"
    assert "typescript" in job.matched_skills or "next.js" in job.matched_skills
    assert job.score >= 80
    assert "TechFounder" in job.pitch
    assert "Next.js" in job.pitch or "Full Stack" in job.pitch


def test_ai_agentic_engineer_match():
    text = (
        "We're hiring an AI Engineer to build autonomous agent workflows and RAG pipelines. "
        "Stack: Python, FastAPI, LangChain, Supabase, and Vector DBs. "
        "Rate: $75/hr. 100% remote anywhere."
    )
    job = evaluate_job(text, author="AgentLab", link="https://news.ycombinator.com/item?id=123")
    assert job is not None
    assert job.track_id == "AI_AGENTIC_ENGINEER"
    assert "python" in job.matched_skills
    assert "fastapi" in job.matched_skills
    assert "rag" in job.matched_skills or "langchain" in job.matched_skills
    assert job.score >= 80
    assert "$75/hr" in job.salary or "75" in job.salary
    assert "AgentLab" in job.pitch


def test_workforce_analyst_match():
    text = (
        "[Hiring] Seeking a Workforce Planning Analyst to manage call center capacity planning, "
        "Erlang models, and building SQL / Power BI dashboards. "
        "Salary: $85k - $105k USD. Remote (EMEA or UK friendly)."
    )
    job = evaluate_job(text, author="OpsRecruiter", link="https://reddit.com/r/forhire/123")
    assert job is not None
    assert job.track_id == "BUSINESS_SYSTEMS_WORKFORCE_ANALYST"
    assert "power bi" in job.matched_skills or "sql" in job.matched_skills
    assert "erlang" in job.matched_skills or "capacity planning" in job.matched_skills
    assert job.score >= 80
    assert job.remote_type in ("emea", "worldwide")


def test_negative_seeker_rejection():
    # Job seeker should be rejected
    seeker_text = (
        "[FOR HIRE] Senior Full Stack Developer available for hire. "
        "I build apps in React, Node.js, and Python. DM me with work!"
    )
    assert check_negative_intent(seeker_text) is True
    job = evaluate_job(seeker_text)
    assert job is None


def test_unpaid_intern_rejection():
    unpaid_text = (
        "[HIRING] Looking for a React / Python developer. Unpaid internship with equity only."
    )
    assert check_negative_intent(unpaid_text) is True
    job = evaluate_job(unpaid_text)
    assert job is None


def test_restrictive_clearance_rejection():
    restricted_text = (
        "We are hiring a Software Engineer. Must be US Citizen Only with active Secret Security Clearance. "
        "Stack: React, Python, PostgreSQL."
    )
    assert check_restrictive_visa(restricted_text) is True
    job = evaluate_job(restricted_text)
    assert job is None


def test_salary_extraction():
    assert extract_salary("Salary range: $120,000 - $150,000/yr") != ""
    assert extract_salary("Rate is $85/hr for this contract") != ""
    assert extract_salary("Compensation: £75,000 per year") != ""
    assert extract_salary("Budget: €90k") != ""


def test_location_classification():
    loc, rtype, pts = extract_location("Fully remote - Worldwide anywhere")
    assert rtype == "worldwide"
    assert pts == 20

    loc, rtype, pts = extract_location("Remote in Europe / UK London")
    assert rtype == "emea"
    assert pts == 20
