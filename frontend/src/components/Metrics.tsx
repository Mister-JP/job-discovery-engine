import React from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { SearchRunSummary } from "../types";

interface Props {
  runs: SearchRunSummary[];
}

interface MetricDatum {
  name: string;
  query: string;
  passRate: number;
  raw: number;
  verified: number;
  newInstitutions: number;
  newJobs: number;
}

function getTooltipLabel(label: string, data: MetricDatum[]): string {
  return data.find((item) => item.name === label)?.query || label;
}

export default function Metrics({ runs }: Props) {
  const completed = runs
    .filter((run) => run.status === "completed")
    .reverse()
    .slice(-20);

  const chartData: MetricDatum[] = completed.map((run, index) => ({
    name: `Run ${index + 1}`,
    query: run.query,
    passRate:
      run.candidates_raw > 0
        ? Math.round((run.candidates_verified / run.candidates_raw) * 100)
        : 0,
    raw: run.candidates_raw,
    verified: run.candidates_verified,
    newInstitutions: run.institutions_new,
    newJobs: run.jobs_new,
  }));

  return (
    <section className="dashboard-section metrics-section">
      <div className="section-heading">
        <div>
          <h2>Search Run Metrics</h2>
          <p>
            Trends across the latest completed runs, including verification
            performance and raw-to-new funnel counts.
          </p>
        </div>
      </div>

      {chartData.length < 2 ? (
        <p className="empty-state">
          Need at least 2 completed runs to show metrics.
        </p>
      ) : (
        <div className="metrics-grid">
          <article className="card chart-card">
            <h3 className="chart-card-title">Verification Pass Rate Over Time</h3>
            <p className="chart-copy">
              Completed-run verification rate for the last 20 runs.
            </p>
            <ResponsiveContainer width="100%" height={250}>
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="name" fontSize={12} />
                <YAxis domain={[0, 100]} unit="%" fontSize={12} />
                <Tooltip
                  formatter={(value) => [`${value}%`, "Pass Rate"]}
                  labelFormatter={(label) =>
                    getTooltipLabel(String(label), chartData)
                  }
                />
                <Line
                  type="monotone"
                  dataKey="passRate"
                  stroke="#3182ce"
                  strokeWidth={2}
                  dot={{ r: 4 }}
                  name="Pass Rate"
                />
              </LineChart>
            </ResponsiveContainer>
          </article>

          <article className="card chart-card">
            <h3 className="chart-card-title">Search Funnel Per Run</h3>
            <p className="chart-copy">
              Raw, verified, and newly stored results for each completed run.
            </p>
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="name" fontSize={12} />
                <YAxis fontSize={12} />
                <Tooltip
                  labelFormatter={(label) =>
                    getTooltipLabel(String(label), chartData)
                  }
                />
                <Legend />
                <Bar dataKey="raw" fill="#a0aec0" name="Raw Candidates" />
                <Bar dataKey="verified" fill="#3182ce" name="Verified" />
                <Bar
                  dataKey="newInstitutions"
                  fill="#38a169"
                  name="New Institutions"
                />
                <Bar dataKey="newJobs" fill="#d69e2e" name="New Jobs" />
              </BarChart>
            </ResponsiveContainer>
          </article>
        </div>
      )}
    </section>
  );
}
