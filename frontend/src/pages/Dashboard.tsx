import React, { KeyboardEvent, useEffect, useState } from "react";

import api from "../api";
import Metrics from "../components/Metrics";
import SearchForm from "../components/SearchForm";
import { Institution, Job, SearchRunSummary } from "../types";

interface Props {
  onSelectRun: (runId: string) => void;
  onSelectInstitution: (instId: string) => void;
}

interface PassRateTrend {
  direction: "up" | "down" | "flat" | "insufficient";
  value: string;
  description: string;
}

function formatDuration(durationMs: number | null): string {
  if (durationMs === null) {
    return "—";
  }

  return durationMs >= 1000
    ? `${(durationMs / 1000).toFixed(1)}s`
    : `${durationMs}ms`;
}

function activateOnKeyPress(
  event: KeyboardEvent<HTMLElement>,
  action: () => void
) {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    action();
  }
}

function getRunPassRate(run: SearchRunSummary): number | null {
  if (run.candidates_raw === 0) {
    return null;
  }

  return (run.candidates_verified / run.candidates_raw) * 100;
}

function average(values: number[]): number {
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function getPassRateTrend(completedRuns: SearchRunSummary[]): PassRateTrend {
  const passRates = completedRuns
    .map(getRunPassRate)
    .filter((value): value is number => value !== null);

  if (passRates.length < 2) {
    return {
      direction: "insufficient",
      value: "—",
      description: "Need at least 2 completed runs to detect a trend.",
    };
  }

  if (passRates.length < 4) {
    const delta = passRates[0] - passRates[1];

    if (Math.abs(delta) < 0.1) {
      return {
        direction: "flat",
        value: "Flat",
        description: "Latest completed run is effectively unchanged versus the previous run.",
      };
    }

    const direction = delta > 0 ? "up" : "down";
    return {
      direction,
      value: `${direction === "up" ? "Up" : "Down"} ${Math.abs(delta).toFixed(
        1
      )} pts`,
      description: `Latest completed run is trending ${direction} versus the previous run.`,
    };
  }

  const recentWindow = passRates.slice(0, Math.min(3, passRates.length));
  const previousWindow = passRates.slice(
    recentWindow.length,
    recentWindow.length * 2
  );

  const recentAverage = average(recentWindow);
  const baselineAverage =
    previousWindow.length > 0 ? average(previousWindow) : passRates[1];
  const delta = recentAverage - baselineAverage;

  if (Math.abs(delta) < 0.1) {
    return {
      direction: "flat",
      value: "Flat",
      description:
        previousWindow.length > 0
          ? `Recent pass rate is effectively unchanged versus the previous ${previousWindow.length} runs.`
          : "Latest completed runs are effectively unchanged.",
    };
  }

  const direction = delta > 0 ? "up" : "down";
  const baselineLabel =
    previousWindow.length > 0
      ? `the previous ${previousWindow.length} runs`
      : "the previous run";

  return {
    direction,
    value: `${direction === "up" ? "Up" : "Down"} ${Math.abs(delta).toFixed(
      1
    )} pts`,
    description: `Recent completed-run pass rate is trending ${direction} versus ${baselineLabel}.`,
  };
}

export default function Dashboard({
  onSelectRun,
  onSelectInstitution,
}: Props) {
  const [runs, setRuns] = useState<SearchRunSummary[]>([]);
  const [institutions, setInstitutions] = useState<Institution[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;

    setLoading(true);
    setError(null);

    Promise.all([
      api.get<SearchRunSummary[]>("/api/search-runs?limit=20"),
      api.get<Institution[]>("/api/institutions?verified=true&limit=500"),
      api.get<Job[]>("/api/jobs?is_active=true&limit=500"),
    ])
      .then(([runsResponse, institutionsResponse, jobsResponse]) => {
        if (!isMounted) {
          return;
        }

        setRuns(runsResponse.data);
        setInstitutions(institutionsResponse.data);
        setJobs(jobsResponse.data);
      })
      .catch((requestError) => {
        if (!isMounted) {
          return;
        }

        setError(
          requestError.response?.data?.detail ||
            requestError.message ||
            "Failed to load dashboard"
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
  }, []);

  if (loading) {
    return <div className="loading-shell">Loading dashboard...</div>;
  }

  const completedRuns = runs.filter((run) => run.status === "completed");
  const totalRawCandidates = completedRuns.reduce(
    (sum, run) => sum + run.candidates_raw,
    0
  );
  const totalVerifiedCandidates = completedRuns.reduce(
    (sum, run) => sum + run.candidates_verified,
    0
  );
  const passRate =
    totalRawCandidates > 0
      ? `${((totalVerifiedCandidates / totalRawCandidates) * 100).toFixed(1)}%`
      : "—";
  const passRateTrend = getPassRateTrend(completedRuns);

  return (
    <div className="page-shell">
      <div className="detail-backdrop" aria-hidden="true" />

      <main className="dashboard-panel">
        <header className="dashboard-header">
          <div>
            <p className="eyebrow">Job Discovery Engine</p>
            <h1>Discovery Dashboard</h1>
            <p className="hero-copy">
              A live snapshot of verified institutions, active openings, and
              the most recent search runs moving through the pipeline.
            </p>
          </div>

          <div className="dashboard-highlight">
            <span className="label">Recent Window</span>
            <strong>{runs.length} runs loaded</strong>
            <p>
              Showing the latest search activity plus the ten most recently seen
              verified institutions.
            </p>
          </div>
        </header>

        <SearchForm onComplete={onSelectRun} />

        {error && (
          <div className="error-banner" role="alert">
            {error}
          </div>
        )}

        <section className="cards metric-grid" aria-label="Summary metrics">
          <div className="card metric-card">
            <span className="card-kicker">Institutions</span>
            <div className="card-number">{institutions.length}</div>
            <div className="card-label">Verified institutions tracked</div>
          </div>
          <div className="card metric-card">
            <span className="card-kicker">Jobs</span>
            <div className="card-number">{jobs.length}</div>
            <div className="card-label">Active jobs in the catalog</div>
          </div>
          <div className="card metric-card">
            <span className="card-kicker">Runs</span>
            <div className="card-number">{runs.length}</div>
            <div className="card-label">Recent search runs loaded</div>
          </div>
          <div className="card metric-card">
            <span className="card-kicker">Verification</span>
            <div className="card-number">{passRate}</div>
            <div className="card-label">Completed-run pass rate</div>
          </div>
          <div className="card metric-card">
            <span className="card-kicker">Trend</span>
            <div className={`card-number trend-value trend-${passRateTrend.direction}`}>
              {passRateTrend.value}
            </div>
            <div className="card-label">{passRateTrend.description}</div>
          </div>
        </section>

        <Metrics runs={runs} />

        <section className="dashboard-section">
          <div className="section-heading">
            <div>
              <h2>Recent Search Runs</h2>
              <p>
                Open any run to inspect its raw-to-verified audit trail and
                stored outcomes.
              </p>
            </div>
          </div>

          {runs.length === 0 ? (
            <p className="empty-state">
              No search runs yet. Trigger a run to start building the dashboard
              history.
            </p>
          ) : (
            <div className="table-wrap">
              <table className="runs-table">
                <thead>
                  <tr>
                    <th>Query</th>
                    <th>Status</th>
                    <th>Raw</th>
                    <th>Verified</th>
                    <th>New</th>
                    <th>Duration</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run) => (
                    <tr
                      key={run.id}
                      className="clickable-row"
                      onClick={() => onSelectRun(run.id)}
                      onKeyDown={(event) =>
                        activateOnKeyPress(event, () => onSelectRun(run.id))
                      }
                      role="button"
                      tabIndex={0}
                    >
                      <td className="run-query-cell">{run.query}</td>
                      <td>
                        <span className={`status-badge status-${run.status}`}>
                          {run.status}
                        </span>
                      </td>
                      <td>{run.candidates_raw}</td>
                      <td>{run.candidates_verified}</td>
                      <td>{run.institutions_new + run.jobs_new}</td>
                      <td>{formatDuration(run.duration_ms)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="dashboard-section">
          <div className="section-heading">
            <div>
              <h2>Recent Institutions</h2>
              <p>
                Review the most recently updated verified institutions and jump
                into the institution detail flow.
              </p>
            </div>
          </div>

          {institutions.length === 0 ? (
            <p className="empty-state">
              No verified institutions have been stored yet.
            </p>
          ) : (
            <div className="institution-list">
              {institutions.slice(0, 10).map((institution) => (
                <button
                  key={institution.id}
                  type="button"
                  className="institution-card"
                  onClick={() => onSelectInstitution(institution.id)}
                >
                  <div className="institution-card-top">
                    <div className="inst-name">{institution.name}</div>
                    <span className="inst-type">
                      {institution.institution_type || "other"}
                    </span>
                  </div>
                  <div className="inst-meta">
                    {institution.domain} •{" "}
                    {institution.location || "Unknown location"}
                  </div>
                </button>
              ))}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
