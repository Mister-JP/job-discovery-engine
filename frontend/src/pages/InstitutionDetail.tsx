import React, { useEffect, useState } from "react";

import api from "../api";
import { InstitutionDetail as InstitutionDetailType } from "../types";

interface Props {
  institutionId: string;
  onBack: () => void;
}

function formatDate(value: string | null): string {
  if (!value) {
    return "—";
  }

  return new Date(value).toLocaleDateString();
}

function formatToken(value: string | null): string {
  if (!value) {
    return "Unknown";
  }

  return value
    .split("_")
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(" ");
}

export default function InstitutionDetailPage({
  institutionId,
  onBack,
}: Props) {
  const [institution, setInstitution] = useState<InstitutionDetailType | null>(
    null
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;

    setLoading(true);
    setError(null);

    api
      .get<InstitutionDetailType>(`/api/institutions/${institutionId}`)
      .then((response) => {
        if (!isMounted) {
          return;
        }

        setInstitution(response.data);
      })
      .catch((requestError) => {
        if (!isMounted) {
          return;
        }

        setInstitution(null);
        setError(
          requestError.response?.data?.detail ||
            requestError.message ||
            "Failed to load institution"
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
  }, [institutionId]);

  if (loading) {
    return <div className="loading-shell">Loading institution...</div>;
  }

  if (!institution) {
    return (
      <div className="page-shell">
        <button onClick={onBack} className="back-btn">
          Back
        </button>
        <div className="error-banner">{error || "Institution not found"}</div>
      </div>
    );
  }

  return (
    <div className="page-shell">
      <div className="detail-backdrop" aria-hidden="true" />

      <main className="institution-detail">
        <button onClick={onBack} className="back-btn">
          Back
        </button>

        <header className="detail-hero">
          <div>
            <p className="eyebrow">Institution Records</p>
            <h1>{institution.name}</h1>
            <p className="hero-copy">
              Verified institution profile, canonical careers link, and the
              latest job records connected to this organization.
            </p>
          </div>

          <div className="hero-status-panel institution-status-panel">
            <span
              className={`status-badge ${
                institution.is_verified ? "badge-verified" : "badge-unverified"
              }`}
            >
              {institution.is_verified ? "Verified" : "Unverified"}
            </span>
            <span className="run-id-label">Primary Domain</span>
            <code>{institution.domain}</code>
          </div>
        </header>

        <section
          className="inst-meta-grid institution-meta-grid"
          aria-label="Institution metadata"
        >
          <div className="card meta-item meta-card">
            <span className="label">Domain</span>
            <span className="value">{institution.domain}</span>
          </div>
          <div className="card meta-item meta-card">
            <span className="label">Type</span>
            <span className="value">
              {formatToken(institution.institution_type)}
            </span>
          </div>
          <div className="card meta-item meta-card">
            <span className="label">Location</span>
            <span className="value">{institution.location || "Unknown"}</span>
          </div>
          <div className="card meta-item meta-card">
            <span className="label">Careers Page</span>
            {institution.careers_url ? (
              <a
                className="detail-link"
                href={institution.careers_url}
                target="_blank"
                rel="noopener noreferrer"
              >
                Visit careers site
              </a>
            ) : (
              <span className="value">None recorded</span>
            )}
          </div>
          <div className="card meta-item meta-card">
            <span className="label">First Seen</span>
            <span className="value">{formatDate(institution.first_seen_at)}</span>
          </div>
          <div className="card meta-item meta-card">
            <span className="label">Last Seen</span>
            <span className="value">{formatDate(institution.last_seen_at)}</span>
          </div>
        </section>

        {institution.description && (
          <section className="institution-description inst-description">
            <div className="section-heading">
              <div>
                <h2>Profile</h2>
                <p>Stored description and context for this institution record.</p>
              </div>
            </div>
            <p>{institution.description}</p>
          </section>
        )}

        <section className="table-section">
          <div className="section-heading">
            <div>
              <h2>Jobs</h2>
              <p>
                {institution.jobs.length} linked job
                {institution.jobs.length === 1 ? "" : "s"} sorted by latest
                activity.
              </p>
            </div>
          </div>

          {institution.jobs.length === 0 ? (
            <p className="empty-state">
              No jobs recorded for this institution.
            </p>
          ) : (
            <div className="table-wrap">
              <table className="jobs-table">
                <thead>
                  <tr>
                    <th>Title</th>
                    <th>Location</th>
                    <th>Level</th>
                    <th>Salary</th>
                    <th>Verified</th>
                    <th>Active</th>
                    <th>First Seen</th>
                    <th>Last Seen</th>
                  </tr>
                </thead>
                <tbody>
                  {institution.jobs.map((job) => (
                    <tr key={job.id}>
                      <td className="job-title-cell">
                        <a
                          className="detail-link"
                          href={job.url}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          {job.title}
                        </a>
                      </td>
                      <td>{job.location || "—"}</td>
                      <td>{formatToken(job.experience_level)}</td>
                      <td>{job.salary_range || "—"}</td>
                      <td>
                        <span
                          className={`status-badge subtle-badge ${
                            job.is_verified
                              ? "badge-verified"
                              : "badge-unverified"
                          }`}
                        >
                          {job.is_verified ? "Verified" : "Pending"}
                        </span>
                      </td>
                      <td>
                        <span
                          className={`status-badge subtle-badge ${
                            job.is_active ? "badge-verified" : "badge-unverified"
                          }`}
                        >
                          {job.is_active ? "Active" : "Inactive"}
                        </span>
                      </td>
                      <td>{formatDate(job.first_seen_at)}</td>
                      <td>{formatDate(job.last_seen_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
