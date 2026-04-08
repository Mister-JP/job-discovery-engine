"""Canonical blocklist of job aggregator and ATS domains.

These domains are never treated as primary sources for job discovery.
Keep this list aligned wherever prompts or verification logic reference
job-board exclusions.
"""

AGGREGATOR_DOMAINS = (
    # Major job boards
    "indeed.com",
    "linkedin.com",
    "glassdoor.com",
    "ziprecruiter.com",
    "monster.com",
    "simplyhired.com",
    "careerbuilder.com",
    "dice.com",
    # Startup / tech job boards
    "hired.com",
    "wellfound.com",
    "angel.co",
    "builtin.com",
    "ycombinator.com",
    # ATS platforms (not primary sources)
    "lever.co",
    "greenhouse.io",
    "workday.com",
    "jobvite.com",
    "smartrecruiters.com",
    "icims.com",
    "ultipro.com",
    "breezy.hr",
    "ashbyhq.com",
    "dover.com",
    # International aggregators
    "adzuna.com",
    "jooble.org",
    "neuvoo.com",
    "talent.com",
    "reed.co.uk",
    "totaljobs.com",
    "seek.com.au",
    "naukri.com",
    # Meta-search / review
    "comparably.com",
    "theladders.com",
    "flexjobs.com",
    # Search results
    "google.com",
)
