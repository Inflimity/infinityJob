"""
Job Classification, Heuristic Intent Filtering, and Scoring Engine.

Categorizes jobs into 3 focused career tracks:
1. FULL_STACK_BACKEND (React, Next.js, Node, Laravel/PHP, C#/.NET, Postgres, APIs)
2. AI_AGENTIC_ENGINEER (Python, FastAPI, LLMs, LangChain/LlamaIndex, Agents, RAG, Supabase)
3. BUSINESS_SYSTEMS_WORKFORCE_ANALYST (SQL, Power BI, Tableau, Workforce Planning, Erlang, KPIs)

Computes a composite relevance score (0–100) based on role match, skill density,
timezone/remote compatibility, and compensation transparency.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ── Track Definitions & Pitch Templates ──────────────────────────────────────

TARGET_TRACKS = {
    "FULL_STACK_BACKEND": {
        "badge": "💻 Full-Stack / Backend",
        "roles": [
            "full stack engineer", "full stack developer", "fullstack engineer",
            "fullstack developer", "full-stack engineer", "full-stack developer",
            "backend engineer", "backend developer", "software engineer",
            "web engineer", "web developer", "api developer", "systems engineer",
            "software developer", "full stack", "fullstack", "backend dev"
        ],
        "skills": [
            "typescript", "javascript", "react", "next.js", "nextjs", "next js",
            "node", "node.js", "nodejs", "express", "php", "laravel", "c#",
            ".net", "dotnet", "asp.net", "postgresql", "postgres", "mysql",
            "rest api", "restful", "docker", "graphql", "tailwind", "tailwindcss",
            "prisma", "trpc", "redis", "aws", "gcp", "azure", "ci/cd"
        ],
        "min_match": 2,  # 1 role + at least 1 skill
        "pitch_template": (
            "Hi {author}, I saw your post regarding the {role} position. "
            "I'm a Full-Stack / Backend Engineer with extensive experience building production "
            "systems using Next.js, Node.js, PHP/Laravel, and .NET with robust REST/GraphQL APIs and PostgreSQL. "
            "I'd love to connect to discuss how I can contribute: {link}"
        ),
    },
    "AI_AGENTIC_ENGINEER": {
        "badge": "🤖 AI / Agentic Systems",
        "roles": [
            "ai engineer", "llm engineer", "ai developer", "agentic engineer",
            "automation engineer", "ai/ml engineer", "machine learning engineer",
            "prompt engineer", "ai application developer", "agent engineer",
            "ai software engineer", "generative ai engineer"
        ],
        "skills": [
            "python", "fastapi", "llm", "llms", "langchain", "llamaindex",
            "gemini", "openai", "agent", "agents", "rag", "embeddings",
            "supabase", "vector db", "vectordb", "chromadb", "pgvector",
            "playwright", "anthropic", "claude", "crewai", "autogen",
            "fine-tuning", "huggingface", "pytorch", "langsmith"
        ],
        "min_match": 2,
        "pitch_template": (
            "Hi {author}, I noticed your post for an {role}. "
            "I specialize in building autonomous AI agents, multi-agent systems, and production RAG pipelines "
            "using Python, FastAPI, vector databases, and modern LLM frameworks. "
            "Would love to share relevant agentic projects: {link}"
        ),
    },
    "BUSINESS_SYSTEMS_WORKFORCE_ANALYST": {
        "badge": "📊 Systems & Workforce Analyst",
        "roles": [
            "business analyst", "systems analyst", "workforce planning analyst",
            "workforce analyst", "data analyst", "technical business analyst",
            "operations analyst", "quality business analyst", "planning analyst",
            "wfm analyst", "resource planner", "business systems analyst",
            "reporting analyst", "bi analyst", "operations specialist"
        ],
        "skills": [
            "sql", "excel", "power bi", "powerbi", "tableau", "process mapping",
            "workforce planning", "erlang", "capacity planning", "kpi", "kpis",
            "reporting", "python", "workflow optimization", "dashboards",
            "data modeling", "etl", "jira", "confluence", "forecast", "forecasting",
            "scheduling", "call center analytics", "wfm"
        ],
        "min_match": 2,
        "pitch_template": (
            "Hi {author}, I came across your posting for a {role}. "
            "My background blends technical business systems analysis, SQL/BI reporting, "
            "and workforce capacity modeling to optimize operational workflows and KPIs. "
            "Here is where we can connect: {link}"
        ),
    },
}

# ── Intent Keywords ──────────────────────────────────────────────────────────

HIRING_INTENT_PATTERNS = [
    r"\[hiring\]",
    r"\bwe(?:'re| are|\s+are)\s+hiring\b",
    r"\blooking for (?:a|an)\b",
    r"\bseeking (?:a|an)\b",
    r"\bjob opening\b",
    r"\bopen position\b",
    r"\bhiring for\b",
    r"\bapply (?:here|via|at|now)\b",
    r"\bdm (?:me|us|open)\b",
    r"\bjoin our team\b",
    r"\bcontract role\b",
    r"\bfull-time role\b",
    r"\bpart-time role\b",
    r"\bbounty\b",
    r"\bpaid gig\b",
    r"\bpaid project\b",
]

SEEKER_NEGATIVE_PATTERNS = [
    r"\[for hire\]",
    r"\[forhire\]",
    r"\[seeking work\]",
    r"\bfor hire\b",
    r"\bhire me\b",
    r"\blooking for work\b",
    r"\blooking for a job\b",
    r"\bi am available for\b",
    r"\bi'm available for\b",
    r"\bmy portfolio\b",
    r"\bopen to work\b",
    r"\bunpaid\b",
    r"\bno salary\b",
    r"\bequity only\b",
    r"\binternship\b",
    r"\bintern\b",
    r"\bco-op\b",
    r"\bcampus ambassador\b",
]

# Strict Disqualification Patterns (e.g. strict citizenship or clearance)
RESTRICTIVE_VISA_PATTERNS = [
    r"\bus citizen only\b",
    r"\bus citizenship required\b",
    r"\bsecurity clearance required\b",
    r"\bactive secret clearance\b",
    r"\bw2 only\b",
    r"\bno c2c\b",
]

# Location / Remote Patterns
REMOTE_WORLDWIDE_PATTERNS = [
    r"\bworldwide\b",
    r"\banywhere\b",
    r"\bglobal\b",
    r"\bremote \(worldwide\)\b",
    r"\bremote - worldwide\b",
    r"\b100% remote\b",
    r"\bfully remote\b",
    r"\bwork from anywhere\b",
]

REMOTE_EMEA_PATTERNS = [
    r"\bemea\b",
    r"\beurope\b",
    r"\buk\b",
    r"\bunited kingdom\b",
    r"\blondon\b",
    r"\beu remote\b",
    r"\buk remote\b",
    r"\bgmt\b",
    r"\bcet\b",
]

REMOTE_US_PATTERNS = [
    r"\bus remote\b",
    r"\bremote \(us\)\b",
    r"\bus only\b",
    r"\bus / canada\b",
    r"\bnorth america\b",
]

# Salary / Rate Regex Patterns
SALARY_PATTERNS = [
    r"\$\s*\d{1,3}(?:,\d{3})*(?:\s*-\s*\$?\s*\d{1,3}(?:,\d{3})*)?\s*(?:k|usd|per year|/yr|/year|a year)?\b",
    r"\$\s*\d{2,3}(?:\.\d+)?\s*(?:-\s*\$?\s*\d{2,3}(?:\.\d+)?)?\s*(?:/hr|/hour|per hour|hr)\b",
    r"£\s*\d{1,3}(?:,\d{3})*(?:\s*-\s*£?\s*\d{1,3}(?:,\d{3})*)?\s*(?:k|gbp|per year|/yr|/year)?\b",
    r"€\s*\d{1,3}(?:,\d{3})*(?:\s*-\s*€?\s*\d{1,3}(?:,\d{3})*)?\s*(?:k|eur|per year|/yr|/year)?\b",
    r"\b\d{2,3}k\s*-\s*\d{2,3}k\s*(?:usd|eur|gbp)?\b",
]


@dataclass(slots=True)
class JobMatch:
    """Classified and scored job offer metadata."""

    track_id: str
    track_badge: str
    role: str
    company: str
    salary: str
    location: str
    remote_type: str  # worldwide, emea, us_remote, us_only, onsite, hybrid, unspecified
    matched_skills: list[str]
    score: int  # 0 - 100
    score_breakdown: dict[str, int] = field(default_factory=dict)
    summary: str = ""
    pitch: str = ""
    original_text: str = ""
    link: str = ""
    language: str = "en"


def check_negative_intent(text: str) -> bool:
    """Returns True if the text represents a job seeker, unpaid gig, or intern role."""
    text_lower = text.lower()
    for pattern in SEEKER_NEGATIVE_PATTERNS:
        if re.search(pattern, text_lower):
            return True
    return False


def check_restrictive_visa(text: str) -> bool:
    """Returns True if the posting requires US Citizenship or Active Clearance."""
    text_lower = text.lower()
    for pattern in RESTRICTIVE_VISA_PATTERNS:
        if re.search(pattern, text_lower):
            return True
    return False


def check_hiring_intent(text: str) -> bool:
    """Returns True if explicit hiring intent keywords are found."""
    text_lower = text.lower()
    for pattern in HIRING_INTENT_PATTERNS:
        if re.search(pattern, text_lower):
            return True
    return False


def extract_salary(text: str) -> str:
    """Extracts explicit salary / hourly rate strings."""
    for pattern in SALARY_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            val = match.group(0).strip()
            if len(val) >= 3:
                return val
    return ""


def extract_location(text: str) -> tuple[str, str, int]:
    """
    Extracts location string, classifies remote type, and assigns location score points (0-20).
    Returns (display_str, remote_type, score_points).
    """
    text_lower = text.lower()

    if check_restrictive_visa(text_lower):
        return "US Only (Restricted / Clearance)", "us_only", 0

    for p in REMOTE_WORLDWIDE_PATTERNS:
        if re.search(p, text_lower):
            return "Remote (Worldwide / Anywhere)", "worldwide", 20

    for p in REMOTE_EMEA_PATTERNS:
        if re.search(p, text_lower):
            return "Remote (EMEA / UK / Europe Friendly)", "emea", 20

    for p in REMOTE_US_PATTERNS:
        if re.search(p, text_lower):
            return "Remote (US Timezone / Async)", "us_remote", 12

    if "remote" in text_lower:
        return "Remote (Location Unspecified)", "worldwide", 15
    elif "hybrid" in text_lower:
        return "Hybrid", "hybrid", 5
    elif "onsite" in text_lower or "on-site" in text_lower:
        return "Onsite", "onsite", 2

    return "Remote / Flexible", "unspecified", 10


def extract_summary(text: str, max_chars: int = 400) -> str:
    """Cleans up and creates a readable overview snippet."""
    clean = re.sub(r"\s+", " ", text).strip()
    if len(clean) <= max_chars:
        return clean
    snippet = clean[:max_chars]
    last_period = snippet.rfind(".")
    if last_period > max_chars // 2:
        return snippet[: last_period + 1]
    return snippet + "..."


def evaluate_job(
    text: str,
    author: str = "",
    link: str = "",
    from_search: bool = False,
    is_dedicated_job_board: bool = False,
) -> Optional[JobMatch]:
    """
    Analyzes job text against the 3-track taxonomy and returns a scored JobMatch.
    """
    if not text or len(text.strip()) < 15:
        return None

    # Step 1: Disqualify job seekers / unpaid posts
    if check_negative_intent(text):
        logger.debug("Filtered out job seeker / unpaid posting: %s", text[:60])
        return None

    # Step 2: Check hiring intent for uncurated feeds (social posts)
    if not (from_search or is_dedicated_job_board):
        if not check_hiring_intent(text):
            logger.debug("No hiring intent detected: %s", text[:60])
            return None

    text_lower = text.lower()

    # Step 3: Evaluate each track
    best_match: Optional[JobMatch] = None
    highest_score = -1

    location_str, remote_type, location_pts = extract_location(text)
    salary_str = extract_salary(text)

    # Disqualify if restrictive citizenship required
    if remote_type == "us_only" and check_restrictive_visa(text):
        logger.debug("Filtered out restrictive visa/clearance job: %s", text[:60])
        return None

    for track_id, track_info in TARGET_TRACKS.items():
        # Match roles
        matched_roles = []
        for r in track_info["roles"]:
            pattern = rf"\b{re.escape(r)}\b"
            if re.search(pattern, text_lower):
                matched_roles.append(r)

        # Match skills
        matched_skills = []
        for s in track_info["skills"]:
            pattern = rf"\b{re.escape(s)}\b"
            if re.search(pattern, text_lower):
                matched_skills.append(s)

        total_matches = len(matched_roles) + len(matched_skills)
        min_required = track_info.get("min_match", 2)

        has_role = len(matched_roles) >= 1
        has_skill = len(matched_skills) >= 1

        if not is_dedicated_job_board:
            if not (has_role and has_skill):
                continue
        else:
            if not (has_role or (has_skill and len(matched_skills) >= 2)):
                continue

        if total_matches < min_required:
            continue

        # ── Calculate Composite Score (0–100) ────────────────────────────────
        # 1. Role Score (Max 35 pts)
        role_pts = 35 if matched_roles else 15

        # 2. Skill Density (Max 30 pts: 10 pts per matched skill)
        skill_pts = min(30, len(matched_skills) * 10)

        # 3. Location & Timezone (Max 20 pts)
        loc_pts = location_pts

        # 4. Compensation Transparency (Max 15 pts)
        comp_pts = 15 if salary_str else 0

        score = min(100, role_pts + skill_pts + loc_pts + comp_pts)

        if score > highest_score:
            highest_score = score
            detected_role = (
                matched_roles[0].title()
                if matched_roles
                else track_info["roles"][0].title()
            )
            detected_company = author or "Direct Post / Organization"

            # Generate personalized pitch
            pitch = track_info["pitch_template"].format(
                author=author or "Team",
                role=detected_role,
                link=link or "your post",
            )

            best_match = JobMatch(
                track_id=track_id,
                track_badge=track_info["badge"],
                role=detected_role,
                company=detected_company,
                salary=salary_str or "Negotiable / Competitive",
                location=location_str,
                remote_type=remote_type,
                matched_skills=matched_skills,
                score=score,
                score_breakdown={
                    "role_pts": role_pts,
                    "skill_pts": skill_pts,
                    "location_pts": loc_pts,
                    "comp_pts": comp_pts,
                },
                summary=extract_summary(text),
                pitch=pitch,
                original_text=text,
                link=link,
            )

    return best_match
