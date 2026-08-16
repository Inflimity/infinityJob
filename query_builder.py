"""
Query Builder — Generates high-signal boolean search queries for X (Twitter) and other engines.
Optimized for the 3 target career tracks.
"""

from __future__ import annotations


def build_twitter_job_queries() -> list[str]:
    """
    Constructs targeted boolean queries for X (Twitter) search.
    Keeps queries within X character limits while maximizing signal across the 3 tracks.
    """
    return [
        # Track 1: Full-Stack / Backend Engineering
        '("we\'re hiring" OR "hiring" OR "looking for a") ("full stack" OR "fullstack" OR "backend" OR "nextjs" OR "laravel" OR "dotnet") (remote OR worldwide) -is:retweet -intern',
        
        # Track 2: AI & Agentic Systems Engineering
        '("we\'re hiring" OR "hiring" OR "looking for an" OR "looking for a") ("ai engineer" OR "agent" OR "agents" OR "llm" OR "fastapi" OR "rag" OR "langchain") (remote OR worldwide) -is:retweet -intern',
        
        # Track 3: Business Systems & Workforce Analytics
        '("we\'re hiring" OR "hiring" OR "looking for a") ("workforce analyst" OR "business analyst" OR "systems analyst" OR "workforce planning") (remote) -is:retweet -intern',
        
        # High-intent Contract / Fast Gigs
        '("paid bounty" OR "contract engineer" OR "freelance engineer" OR "seeking developer") (remote OR worldwide) -is:retweet -intern'
    ]


if __name__ == "__main__":
    queries = build_twitter_job_queries()
    print(f"Generated {len(queries)} job search queries:")
    for i, q in enumerate(queries, 1):
        print(f"[{i}] {q} ({len(q)} chars)")
