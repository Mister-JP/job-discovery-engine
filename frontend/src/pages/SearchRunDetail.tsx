import React, { useEffect, useState } from "react";

import api from "../api";
import {
  SearchRunDetail as SearchRunDetailType,
  SearchRunStage,
  VerificationEvidence,
} from "../types";

interface Props {
  runId: string;
  onBack: () => void;
}

interface CandidateSummary {
  url: string;
  name: string;
  checks: VerificationEvidence[];
  passed: boolean;
  failedCheck: VerificationEvidence | null;
  checksPassed: number;
  totalDurationMs: number | null;
  skippedChecks: string[];
}

interface CheckSummary {
  checkName: string;
  count: number;
  failures: number;
  averageDurationMs: number;
  maxDurationMs: number;
}

const CHECK_ORDER = [
  "url_wellformed",
  "not_aggregator",
  "dns_resolves",
  "http_reachable",
  "content_signals",
];

const CHECK_LABELS: Record<string, string> = {
  url_wellformed: "URL Wellformed",
  not_aggregator: "Not Aggregator",
  dns_resolves: "DNS Resolves",
  http_reachable: "HTTP Reachable",
  content_signals: "Content Signals",
};

function formatDuration(durationMs: number | null): string {
  if (durationMs === null) {
    return "—";
  }

  return durationMs >= 1000
    ? `${(durationMs / 1000).toFixed(1)}s`
    : `${durationMs}ms`;
}

function formatDateTime(value: string | null): string {
  if (!value) {
    return "—";
  }

  return new Date(value).toLocaleString();
}

function formatCheckName(checkName: string): string {
  return CHECK_LABELS[checkName] || checkName.replace(/_/g, " ");
}

function formatPercent(numerator: number, denominator: number): string {
  if (denominator === 0) {
    return "—";
  }

  return `${((numerator / denominator) * 100).toFixed(1)}%`;
}

function formatStageDetailValue(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }

  if (Array.isArray(value)) {
    return value.length > 0 ? value.map(formatStageDetailValue).join(", ") : "—";
  }

  if (typeof value === "object") {
    return JSON.stringify(value);
  }

  return String(value);
}

/** Group verification evidence by candidate URL while preserving first-seen order. */
function groupByCandidate(
  evidence: VerificationEvidence[]
): Array<[string, VerificationEvidence[]]> {
  const groups = new Map<string, VerificationEvidence[]>();

  evidence.forEach((item) => {
    const existing = groups.get(item.candidate_url);
    if (existing) {
      existing.push(item);
      return;
    }

    groups.set(item.candidate_url, [item]);
  });

  return Array.from(groups.entries());
}

function getCandidateSummaries(
  evidence: VerificationEvidence[]
): CandidateSummary[] {
  return groupByCandidate(evidence)
    .map(([url, checks]) => {
      const orderedChecks = [...checks].sort(
        (left, right) =>
          CHECK_ORDER.indexOf(left.check_name) - CHECK_ORDER.indexOf(right.check_name)
      );
      const failedCheck = orderedChecks.find((item) => !item.passed) || null;
      const durationValues = orderedChecks
        .map((item) => item.duration_ms)
        .filter((value): value is number => value !== null);

      return {
        url,
        name: orderedChecks[0]?.candidate_name || url,
        checks: orderedChecks,
        passed: failedCheck === null && orderedChecks.length > 0,
        failedCheck,
        checksPassed: orderedChecks.filter((item) => item.passed).length,
        totalDurationMs:
          durationValues.length > 0
            ? durationValues.reduce((sum, value) => sum + value, 0)
            : null,
        skippedChecks: CHECK_ORDER.filter(
          (checkName) =>
            !orderedChecks.some((item) => item.check_name === checkName)
        ),
      };
    })
    .sort((left, right) => {
      if (left.passed !== right.passed) {
        return left.passed ? 1 : -1;
      }

      return left.name.localeCompare(right.name);
    });
}

function getCheckSummaries(evidence: VerificationEvidence[]): CheckSummary[] {
  const buckets: Record<
    string,
    { count: number; failures: number; totalDurationMs: number; maxDurationMs: number }
  > = {};

  evidence.forEach((item) => {
    if (item.duration_ms === null) {
      return;
    }

    const bucket = buckets[item.check_name] || {
      count: 0,
      failures: 0,
      totalDurationMs: 0,
      maxDurationMs: 0,
    };

    bucket.count += 1;
    bucket.totalDurationMs += item.duration_ms;
    bucket.maxDurationMs = Math.max(bucket.maxDurationMs, item.duration_ms);
    if (!item.passed) {
      bucket.failures += 1;
    }

    buckets[item.check_name] = bucket;
  });

  return Object.entries(buckets)
    .map(([checkName, bucket]) => ({
      checkName,
      count: bucket.count,
      failures: bucket.failures,
      averageDurationMs: bucket.totalDurationMs / bucket.count,
      maxDurationMs: bucket.maxDurationMs,
    }))
    .sort((left, right) => right.averageDurationMs - left.averageDurationMs);
}

function getSlowestCheckLabel(checkSummaries: CheckSummary[]): string {
  if (checkSummaries.length === 0) {
    return "—";
  }

  const slowest = checkSummaries[0];
  return `${formatCheckName(slowest.checkName)} (${formatDuration(
    Math.round(slowest.averageDurationMs)
  )} avg)`;
}

function getStageDetailEntries(stage: SearchRunStage): Array<[string, string]> {
  return Object.entries(stage.details)
    .map(
      ([key, value]): [string, string] => [
        key.replace(/_/g, " "),
        formatStageDetailValue(value),
      ]
    )
    .filter(([, value]) => value !== "—");
}

export default function SearchRunDetailPage({ runId, onBack }: Props) {
  const [run, setRun] = useState<SearchRunDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;

    setLoading(true);
    setError(null);

    api
      .get<SearchRunDetailType>(`/api/search-runs/${runId}`)
      .then((response) => {
        if (!isMounted) {
          return;
        }

        setRun(response.data);
      })
      .catch((requestError) => {
        if (!isMounted) {
          return;
        }

        setRun(null);
        setError(
          requestError.response?.data?.detail ||
            requestError.message ||
            "Failed to load search run"
        );
      })
      .finally(() => {
        if (isMounted) {
          setLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [runId]);

  if (loading) {
    return <div className="loading-shell">Loading search run...</div>;
  }

  if (!run) {
    return (
      <div className="page-shell">
        <button onClick={onBack} className="back-btn">
          Back
        </button>
        <div className="error-banner">{error || "Search run not found"}</div>
      </div>
    );
  }

  const candidateSummaries = getCandidateSummaries(run.verification_evidence);
  const checkSummaries = getCheckSummaries(run.verification_evidence);
  const failedCandidates = candidateSummaries.filter((candidate) => !candidate.passed);
  const slowestCheckLabel = getSlowestCheckLabel(checkSummaries);

  return (
    <div className="page-shell">
      <div className="detail-backdrop" aria-hidden="true" />

      <div className="search-run-detail">
        <button onClick={onBack} className="back-btn">
          Back
        </button>

        <header className="detail-hero">
          <div>
            <p className="eyebrow">Search Audit Trail</p>
            <h1>Search Run Detail</h1>
            <p className="hero-copy">
              Full verification trace for a single search execution, from raw
              candidates through stored outcomes.
            </p>
          </div>
          <div className="hero-status-panel">
            <span className={`status-badge status-${run.status}`}>{run.status}</span>
            <span className="run-id-label">Run ID</span>
            <code>{run.id}</code>
          </div>
        </header>

        <section className="run-meta meta-grid" aria-label="Search run metadata">
          <div className="card meta-item meta-card meta-card-query">
            <span className="label">Query</span>
            <span className="value value-query">{run.query}</span>
          </div>
          <div className="card meta-item meta-card">
            <span className="label">Duration</span>
            <span className="value">{formatDuration(run.duration_ms)}</span>
          </div>
          <div className="card meta-item meta-card">
            <span className="label">Started</span>
            <span className="value">{formatDateTime(run.initiated_at)}</span>
          </div>
          <div className="card meta-item meta-card">
            <span className="label">Completed</span>
            <span className="value">{formatDateTime(run.completed_at)}</span>
          </div>
        </section>

        {run.error_detail && (
          <div className="error-banner" role="alert">
            {run.error_detail}
          </div>
        )}

        <section className="cards metric-grid" aria-label="Run debugging summary">
          <div className="card metric-card">
            <span className="card-kicker">Pass Rate</span>
            <div className="card-number">
              {formatPercent(run.candidates_verified, run.candidates_raw)}
            </div>
            <div className="card-label">Verified candidates out of Gemini output</div>
          </div>
          <div className="card metric-card">
            <span className="card-kicker">Rejected</span>
            <div className="card-number">{failedCandidates.length}</div>
            <div className="card-label">Candidates that failed verification</div>
          </div>
          <div className="card metric-card">
            <span className="card-kicker">Evidence</span>
            <div className="card-number">{run.verification_evidence.length}</div>
            <div className="card-label">Recorded verification checks</div>
          </div>
          <div className="card metric-card">
            <span className="card-kicker">Slowest Check</span>
            <div className="card-number metric-card-compact">{slowestCheckLabel}</div>
            <div className="card-label">Highest average latency in this run</div>
          </div>
        </section>

        <section className="funnel-section">
          <div className="section-heading">
            <h2>Pipeline Funnel</h2>
            <p>Raw candidates move through verification into stored entities.</p>
          </div>

          <div className="funnel">
            <div className="funnel-step">
              <div className="funnel-number">{run.candidates_raw}</div>
              <div className="funnel-label">Raw Candidates</div>
            </div>
            <div className="funnel-arrow" aria-hidden="true">
              →
            </div>
            <div className="funnel-step">
              <div className="funnel-number">{run.candidates_verified}</div>
              <div className="funnel-label">Verified</div>
            </div>
            <div className="funnel-arrow" aria-hidden="true">
              →
            </div>
            <div className="funnel-step">
              <div className="funnel-number">{run.institutions_new}</div>
              <div className="funnel-label">New Institutions</div>
            </div>
            <div className="funnel-arrow" aria-hidden="true">
              →
            </div>
            <div className="funnel-step">
              <div className="funnel-number">{run.jobs_new}</div>
              <div className="funnel-label">New Jobs</div>
            </div>
          </div>

          <div className="cards storage-stats">
            <div className="card meta-item storage-card">
              <span className="label">Institutions Updated</span>
              <span className="value">{run.institutions_updated}</span>
            </div>
            <div className="card meta-item storage-card">
              <span className="label">Jobs Updated</span>
              <span className="value">{run.jobs_updated}</span>
            </div>
          </div>
        </section>

        <section className="dashboard-section">
          <div className="section-heading">
            <div>
              <h2>Pipeline Trace</h2>
              <p>
                Stage-by-stage timeline with durations and recorded metadata for
                reconstructing the run after the fact.
              </p>
            </div>
          </div>

          {run.pipeline_trace.length === 0 ? (
            <p className="empty-state">No pipeline trace was recorded for this run.</p>
          ) : (
            <div className="trace-grid">
              {run.pipeline_trace.map((stage) => {
                const detailEntries = getStageDetailEntries(stage);

                return (
                  <article key={`${stage.stage}-${stage.started_at}`} className="card trace-card">
                    <div className="trace-card-header">
                      <div>
                        <div className="trace-title">{stage.label}</div>
                        <div className="trace-name">{stage.stage}</div>
                      </div>
                      <span className={`status-badge status-${stage.status}`}>
                        {stage.status}
                      </span>
                    </div>

                    <div className="trace-meta">
                      <div>
                        <span className="label">Started</span>
                        <span className="value">{formatDateTime(stage.started_at)}</span>
                      </div>
                      <div>
                        <span className="label">Completed</span>
                        <span className="value">{formatDateTime(stage.completed_at)}</span>
                      </div>
                      <div>
                        <span className="label">Duration</span>
                        <span className="value">{formatDuration(stage.duration_ms)}</span>
                      </div>
                    </div>

                    {detailEntries.length > 0 && (
                      <dl className="trace-detail-list">
                        {detailEntries.map(([label, value]) => (
                          <div key={`${stage.stage}-${label}`} className="trace-detail-row">
                            <dt>{label}</dt>
                            <dd>{value}</dd>
                          </div>
                        ))}
                      </dl>
                    )}
                  </article>
                );
              })}
            </div>
          )}
        </section>

        <section className="dashboard-section">
          <div className="section-heading">
            <div>
              <h2>Candidate Diagnosis</h2>
              <p>
                Each checked URL with its final outcome, failure point, reason,
                and total verification latency.
              </p>
            </div>
          </div>

          {candidateSummaries.length === 0 ? (
            <p className="empty-state">No verification evidence was recorded for this run.</p>
          ) : (
            <div className="candidate-summary-grid">
              {candidateSummaries.map((candidate) => (
                <article key={candidate.url} className="card candidate-summary-card">
                  <div className="candidate-summary-header">
                    <div>
                      <div className="candidate-name">{candidate.name}</div>
                      <div className="candidate-url">{candidate.url}</div>
                    </div>
                    <span
                      className={`status-badge status-${
                        candidate.passed ? "completed" : "failed"
                      }`}
                    >
                      {candidate.passed ? "verified" : "rejected"}
                    </span>
                  </div>

                  <div className="candidate-summary-meta">
                    <div className="candidate-summary-stat">
                      <span className="label">Checks</span>
                      <span className="value">
                        {candidate.checksPassed}/{candidate.checks.length}
                      </span>
                    </div>
                    <div className="candidate-summary-stat">
                      <span className="label">Total Check Time</span>
                      <span className="value">{formatDuration(candidate.totalDurationMs)}</span>
                    </div>
                    <div className="candidate-summary-stat">
                      <span className="label">First Checked</span>
                      <span className="value">
                        {formatDateTime(candidate.checks[0]?.checked_at || null)}
                      </span>
                    </div>
                  </div>

                  {candidate.failedCheck ? (
                    <div className="candidate-failure-banner" role="note">
                      <strong>Failed at {formatCheckName(candidate.failedCheck.check_name)}.</strong>{" "}
                      {candidate.failedCheck.detail || "No failure reason recorded."}
                    </div>
                  ) : (
                    <div className="candidate-success-banner" role="note">
                      Passed every executed verification check.
                    </div>
                  )}

                  {candidate.skippedChecks.length > 0 && (
                    <p className="candidate-skipped-checks">
                      Skipped after failure:{" "}
                      {candidate.skippedChecks.map(formatCheckName).join(", ")}
                    </p>
                  )}
                </article>
              ))}
            </div>
          )}
        </section>

        <section className="table-section">
          <div className="section-heading">
            <div>
              <h2>Check Performance</h2>
              <p>
                Average and max latency per verification step, plus failure
                counts for bottleneck analysis.
              </p>
            </div>
          </div>

          {checkSummaries.length === 0 ? (
            <p className="empty-state">No check timings are available for this run.</p>
          ) : (
            <div className="table-wrap">
              <table className="runs-table">
                <thead>
                  <tr>
                    <th>Check</th>
                    <th>Observed</th>
                    <th>Failures</th>
                    <th>Average</th>
                    <th>Max</th>
                  </tr>
                </thead>
                <tbody>
                  {checkSummaries.map((summary) => (
                    <tr key={summary.checkName}>
                      <td>{formatCheckName(summary.checkName)}</td>
                      <td>{summary.count}</td>
                      <td>{summary.failures}</td>
                      <td>{formatDuration(Math.round(summary.averageDurationMs))}</td>
                      <td>{formatDuration(summary.maxDurationMs)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="table-section">
          <div className="section-heading">
            <h2>Verification Evidence Matrix</h2>
            <p>
              {run.verification_evidence.length} recorded checks across candidates.
            </p>
          </div>

          {candidateSummaries.length === 0 ? (
            <p className="empty-state">No verification evidence was recorded for this run.</p>
          ) : (
            <div className="table-wrap">
              <table className="evidence-table">
                <thead>
                  <tr>
                    <th>Candidate</th>
                    {CHECK_ORDER.map((checkName) => (
                      <th key={checkName} className="check-header">
                        {formatCheckName(checkName)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {candidateSummaries.map((candidate) => {
                    const checkMap: Record<string, VerificationEvidence> = {};

                    candidate.checks.forEach((check) => {
                      checkMap[check.check_name] = check;
                    });

                    return (
                      <tr key={candidate.url}>
                        <td className="candidate-cell" title={candidate.url}>
                          <div className="candidate-name">{candidate.name}</div>
                          <div className="candidate-url">{candidate.url}</div>
                        </td>
                        {CHECK_ORDER.map((checkName) => {
                          const evidence = checkMap[checkName];

                          if (!evidence) {
                            return (
                              <td key={checkName} className="check-cell check-skipped">
                                <span aria-label={`${checkName} skipped`}>—</span>
                              </td>
                            );
                          }

                          return (
                            <td
                              key={checkName}
                              className={`check-cell ${
                                evidence.passed ? "check-pass" : "check-fail"
                              }`}
                            >
                              <span
                                className="check-glyph"
                                aria-label={`${checkName} ${
                                  evidence.passed ? "passed" : "failed"
                                }`}
                              >
                                {evidence.passed ? "✓" : "✗"}
                              </span>
                              {evidence.duration_ms !== null && (
                                <span className="check-duration">
                                  {evidence.duration_ms}ms
                                </span>
                              )}
                              {!evidence.passed && evidence.detail && (
                                <span className="check-detail">{evidence.detail}</span>
                              )}
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>

        {run.raw_response && (
          <details className="raw-response">
            <summary>Raw model response</summary>
            <pre>{run.raw_response}</pre>
          </details>
        )}
      </div>
    </div>
  );
}
