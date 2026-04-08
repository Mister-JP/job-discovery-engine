/** Shared TypeScript types matching the backend API responses. */

export interface SearchRunSummary {
  id: string;
  query: string;
  status: string;
  candidates_raw: number;
  candidates_verified: number;
  institutions_new: number;
  institutions_updated: number;
  jobs_new: number;
  jobs_updated: number;
  duration_ms: number | null;
  error_detail: string | null;
}

export interface VerificationEvidence {
  id: string;
  candidate_url: string;
  candidate_name: string | null;
  check_name: string;
  passed: boolean;
  detail: string | null;
  duration_ms: number | null;
  checked_at: string;
}

export interface SearchRunStage {
  stage: string;
  label: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
  details: Record<string, unknown>;
}

export interface SearchRunDetail extends SearchRunSummary {
  initiated_at: string;
  completed_at: string | null;
  raw_response: string | null;
  pipeline_trace: SearchRunStage[];
  verification_evidence: VerificationEvidence[];
}

export interface Institution {
  id: string;
  name: string;
  domain: string;
  careers_url: string | null;
  institution_type: string | null;
  description: string | null;
  location: string | null;
  is_verified: boolean;
  first_seen_at: string;
  last_seen_at: string;
}

export interface Job {
  id: string;
  title: string;
  url: string;
  institution_name: string;
  institution_domain: string;
  location: string | null;
  experience_level: string | null;
  salary_range: string | null;
  is_active: boolean;
  is_verified: boolean;
  source_query: string | null;
  first_seen_at: string;
  last_seen_at: string;
}

export interface InstitutionDetail extends Institution {
  jobs: Array<{
    id: string;
    title: string;
    url: string;
    location: string | null;
    experience_level: string | null;
    salary_range: string | null;
    is_active: boolean;
    is_verified: boolean;
    first_seen_at: string;
    last_seen_at: string;
  }>;
}
