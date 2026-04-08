import { AxiosError } from "axios";
import React, { FormEvent, useState } from "react";

import api from "../api";

interface Props {
  onComplete: (runId: string) => void;
}

interface CreateSearchRunResponse {
  id: string;
}

interface ApiErrorResponse {
  detail?: string;
}

export default function SearchForm({ onComplete }: Props) {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const trimmedQuery = query.trim();
    if (trimmedQuery.length < 3) {
      setError("Query must be at least 3 characters");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const response = await api.post<CreateSearchRunResponse>(
        "/api/search-runs",
        { query: trimmedQuery }
      );

      setQuery("");
      setLoading(false);
      onComplete(response.data.id);
    } catch (requestError) {
      const detail = (requestError as AxiosError<ApiErrorResponse>).response
        ?.data?.detail;
      setError(detail || "Search failed. Please try again.");
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="search-form">
      <label htmlFor="dashboard-search-query" className="search-form-label">
        Start a new search run
      </label>

      <div className="search-input-group">
        <input
          id="dashboard-search-query"
          type="text"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="e.g., AI safety research labs hiring, climate tech nonprofits with engineering roles..."
          disabled={loading}
          className="search-input"
        />
        <button
          type="submit"
          disabled={loading || !query.trim()}
          className="search-btn"
        >
          {loading ? "Searching..." : "Search"}
        </button>
      </div>

      <p className="search-form-copy">
        Submit a focused query and the pipeline will search, verify, and store
        the latest matching institutions and roles.
      </p>

      {loading && (
        <div className="search-progress" role="status">
          Searching the web, verifying results, and storing data... This takes
          10-30 seconds.
        </div>
      )}

      {error && (
        <div className="search-error" role="alert">
          {error}
        </div>
      )}
    </form>
  );
}
