import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import SearchRunDetailPage from "./SearchRunDetail";
import api from "../api";

jest.mock("../api", () => ({
  __esModule: true,
  default: {
    get: jest.fn(),
  },
}));

const mockedApi = api as jest.Mocked<typeof api>;

describe("SearchRunDetailPage", () => {
  afterEach(() => {
    jest.resetAllMocks();
  });

  test("renders grouped verification evidence with skipped checks", async () => {
    mockedApi.get.mockResolvedValue({
      data: {
        id: "run-123",
        query: "AI safety faculty jobs",
        status: "completed",
        candidates_raw: 2,
        candidates_verified: 1,
        institutions_new: 1,
        institutions_updated: 0,
        jobs_new: 1,
        jobs_updated: 0,
        duration_ms: 1420,
        error_detail: null,
        initiated_at: "2026-04-08T12:00:00Z",
        completed_at: "2026-04-08T12:01:00Z",
        raw_response: null,
        pipeline_trace: [
          {
            stage: "initiated",
            label: "Search run created",
            status: "completed",
            started_at: "2026-04-08T12:00:00Z",
            completed_at: "2026-04-08T12:00:00Z",
            duration_ms: 0,
            details: {
              query: "AI safety faculty jobs",
            },
          },
          {
            stage: "verification",
            label: "Verify candidate URLs",
            status: "completed",
            started_at: "2026-04-08T12:00:10Z",
            completed_at: "2026-04-08T12:00:40Z",
            duration_ms: 30000,
            details: {
              candidate_count: 2,
              verified_count: 1,
              rejected_count: 1,
            },
          },
        ],
        verification_evidence: [
          {
            id: "1",
            candidate_url: "https://a.example/jobs",
            candidate_name: "Example A",
            check_name: "url_wellformed",
            passed: true,
            detail: "URL is valid",
            duration_ms: 5,
            checked_at: "2026-04-08T12:00:01Z",
          },
          {
            id: "2",
            candidate_url: "https://a.example/jobs",
            candidate_name: "Example A",
            check_name: "not_aggregator",
            passed: true,
            detail: "Domain is not on the denylist",
            duration_ms: 6,
            checked_at: "2026-04-08T12:00:02Z",
          },
          {
            id: "3",
            candidate_url: "https://a.example/jobs",
            candidate_name: "Example A",
            check_name: "dns_resolves",
            passed: true,
            detail: "DNS resolved",
            duration_ms: 7,
            checked_at: "2026-04-08T12:00:03Z",
          },
          {
            id: "4",
            candidate_url: "https://a.example/jobs",
            candidate_name: "Example A",
            check_name: "http_reachable",
            passed: true,
            detail: "HTTP 200",
            duration_ms: 8,
            checked_at: "2026-04-08T12:00:04Z",
          },
          {
            id: "5",
            candidate_url: "https://a.example/jobs",
            candidate_name: "Example A",
            check_name: "content_signals",
            passed: true,
            detail: "Career page content found",
            duration_ms: 9,
            checked_at: "2026-04-08T12:00:05Z",
          },
          {
            id: "6",
            candidate_url: "https://b.example/jobs",
            candidate_name: "Example B",
            check_name: "url_wellformed",
            passed: true,
            detail: "URL is valid",
            duration_ms: 4,
            checked_at: "2026-04-08T12:00:01Z",
          },
          {
            id: "7",
            candidate_url: "https://b.example/jobs",
            candidate_name: "Example B",
            check_name: "not_aggregator",
            passed: false,
            detail: "Aggregator domain blocked",
            duration_ms: 3,
            checked_at: "2026-04-08T12:00:02Z",
          },
        ],
      },
    });

    const onBack = jest.fn();
    render(<SearchRunDetailPage runId="run-123" onBack={onBack} />);

    expect(screen.getByText(/loading search run/i)).toBeInTheDocument();

    expect(
      await screen.findByRole("heading", { name: /search run detail/i })
    ).toBeInTheDocument();
    expect(screen.getAllByText(/ai safety faculty jobs/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByRole("heading", { name: /pipeline trace/i })).toBeInTheDocument();
    expect(screen.getByText(/verify candidate urls/i)).toBeInTheDocument();
    expect(screen.getAllByText(/example a/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/example b/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/failed at not aggregator/i)).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(1);

    fireEvent.click(screen.getByRole("button", { name: /^back$/i }));
    expect(onBack).toHaveBeenCalledTimes(1);

    await waitFor(() => {
      expect(mockedApi.get).toHaveBeenCalledWith("/api/search-runs/run-123");
    });
  });
});
