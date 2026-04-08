"""Prompt builders that shape Gemini into a constrained discovery tool.

Prompt text is treated as application logic here because small wording changes
materially affect recall, precision, and JSON reliability. Centralizing prompt
construction keeps those tradeoffs explicit and lets the rest of the backend
reuse the same search and verification framing consistently.
"""

from app.core.aggregator_domains import AGGREGATOR_DOMAINS

# Aggregator domains the model should never return.
AGGREGATOR_BLOCKLIST = list(AGGREGATOR_DOMAINS)


def build_search_prompt(
    query: str,
    known_domains: list[str],
    max_results: int = 20,
) -> tuple[str, str]:
    """Build the paired prompts used for grounded institution discovery.

    The prompt blends three goals that naturally compete with each other:
    broad web discovery, strict machine-parseable output, and bias toward new
    institutions instead of rediscovering only what the database already knows.
    Keeping that composition in one function makes prompt tuning safer because
    search behavior and schema expectations evolve together.

    Args:
        query: The user search intent that should drive discovery.
        known_domains: Domains already stored in the database.
        max_results: Upper bound communicated to Gemini for recall control.

    Returns:
        tuple[str, str]: ``(system_prompt, user_message)`` ready for the Gemini
        client.
    """
    unique_known_domains = sorted({domain for domain in known_domains if domain})

    if unique_known_domains:
        known_domains_str = ", ".join(unique_known_domains)
        known_section = f"""
KNOWN DOMAINS (already in our database — still include if relevant, but prioritize discovering NEW institutions):
{known_domains_str}
"""
    else:
        known_section = """
No institutions are in the database yet. Focus on discovering a diverse set of real organizations.
"""

    blocklist_str = ", ".join(AGGREGATOR_BLOCKLIST)

    system_prompt = f"""You are a job discovery research assistant. Your task is to search the web and find REAL institutions (companies, universities, nonprofits, research labs, government agencies) that are currently hiring, along with specific job posting URLs.

CRITICAL RULES:
1. ONLY return results from PRIMARY SOURCES — the institution's own website or official careers page.
2. NEVER return URLs from job aggregator sites: {blocklist_str}
3. Every URL you return must be a real, specific page — not a homepage or generic page.
4. Every institution must have a real careers/jobs page URL.
5. Every job must have a real, specific job posting URL on the institution's own domain.
6. If you cannot find a specific job URL, omit that job entry entirely. Do NOT fabricate URLs.
7. Return UP TO {max_results} results. Quality over quantity — only include results you are confident about.

{known_section}

OUTPUT FORMAT:
Return a JSON object with this exact structure:
{{
  "institutions": [
    {{
      "name": "Institution Name",
      "careers_url": "https://institution.com/careers",
      "institution_type": "company|university|nonprofit|government|research_lab|other",
      "description": "One-sentence description of what they do",
      "location": "City, State/Country",
      "jobs": [
        {{
          "title": "Job Title",
          "url": "https://institution.com/careers/job-id-123",
          "location": "City, State or Remote",
          "experience_level": "intern|entry|mid|senior|lead|executive|unknown",
          "salary_range": "$X-$Y or null if unknown"
        }}
      ]
    }}
  ]
}}

Return ONLY raw JSON. Do not wrap the JSON in markdown fences. Do not add any commentary before or after the JSON.

QUALITY CHECKS BEFORE RETURNING:
- Is each careers_url on the institution's own domain? (not an aggregator)
- Is each job URL a specific posting? (not just a careers listing page)
- Are the institution names real organizations? (not made up)
- Are the job titles plausible for this institution?
"""

    user_message = f"""Search the web for: {query}

Find institutions that are actively hiring for roles related to this query. For each institution, find their careers page and at least 1-2 specific job posting URLs.

Focus on:
- Direct employer websites (not job boards)
- Currently active postings
- A diverse mix of institution types if applicable
- Geographic diversity if the query doesn't specify a location"""

    return system_prompt, user_message


def build_verification_prompt(url: str, page_content: str) -> str:
    """Build a fallback prompt for model-assisted page verification.

    The current verification pipeline mostly relies on deterministic checks, but
    this prompt preserves a path for AI-assisted content review when heuristic
    signals are insufficient. Truncating the page content keeps token usage
    bounded while still giving the model enough evidence to reason about source
    legitimacy and job relevance.

    Args:
        url: Candidate page URL being evaluated.
        page_content: Raw page text to summarize for the model.

    Returns:
        str: Prompt instructing a model to classify the page and explain why.
    """
    preview = page_content[:5000]
    return f"""Analyze this web page content and determine if it is:
1. A legitimate job posting or careers page
2. From a real institution (not a job aggregator)

URL: {url}

Page content (first portion):
{preview}

Return JSON:
{{
  "is_job_related": true/false,
  "is_primary_source": true/false,
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation"
}}"""
