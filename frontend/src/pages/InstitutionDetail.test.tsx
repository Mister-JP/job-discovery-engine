import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import api from "../api";
import InstitutionDetailPage from "./InstitutionDetail";

jest.mock("../api", () => ({
  __esModule: true,
  default: {
    get: jest.fn(),
  },
}));

const mockedApi = api as jest.Mocked<typeof api>;

describe("InstitutionDetailPage", () => {
  afterEach(() => {
    jest.resetAllMocks();
  });

  test("renders institution metadata and linked jobs", async () => {
    mockedApi.get.mockResolvedValue({
      data: {
        id: "inst-123",
        name: "Frontier Research Lab",
        domain: "frontier.example.org",
        careers_url: "https://frontier.example.org/careers",
        institution_type: "research_lab",
        description: "Independent applied AI lab",
        location: "Chicago, IL",
        is_verified: true,
        first_seen_at: "2026-04-01T12:00:00Z",
        last_seen_at: "2026-04-08T12:00:00Z",
        jobs: [
          {
            id: "job-1",
            title: "Research Engineer",
            url: "https://frontier.example.org/jobs/research-engineer",
            location: "Chicago, IL",
            experience_level: "mid",
            salary_range: "$180k-$220k",
            is_active: true,
            is_verified: true,
            first_seen_at: "2026-04-02T12:00:00Z",
            last_seen_at: "2026-04-08T12:00:00Z",
          },
        ],
      },
    });

    const onBack = jest.fn();
    render(<InstitutionDetailPage institutionId="inst-123" onBack={onBack} />);

    expect(screen.getByText(/loading institution/i)).toBeInTheDocument();

    expect(
      await screen.findByRole("heading", { name: /frontier research lab/i })
    ).toBeInTheDocument();
    expect(screen.getByText(/^Research Lab$/)).toBeInTheDocument();
    expect(screen.getByText(/independent applied ai lab/i)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /visit careers site/i })
    ).toHaveAttribute("href", "https://frontier.example.org/careers");
    expect(
      screen.getByRole("link", { name: /research engineer/i })
    ).toHaveAttribute(
      "href",
      "https://frontier.example.org/jobs/research-engineer"
    );
    expect(screen.getByText("$180k-$220k")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^back$/i }));
    expect(onBack).toHaveBeenCalledTimes(1);

    await waitFor(() => {
      expect(mockedApi.get).toHaveBeenCalledWith("/api/institutions/inst-123");
    });
  });

  test("shows an empty state when the institution has no jobs", async () => {
    mockedApi.get.mockResolvedValue({
      data: {
        id: "inst-empty",
        name: "Example University",
        domain: "example.edu",
        careers_url: null,
        institution_type: "university",
        description: null,
        location: null,
        is_verified: false,
        first_seen_at: "2026-04-01T12:00:00Z",
        last_seen_at: "2026-04-08T12:00:00Z",
        jobs: [],
      },
    });

    render(
      <InstitutionDetailPage institutionId="inst-empty" onBack={jest.fn()} />
    );

    expect(
      await screen.findByRole("heading", { name: /example university/i })
    ).toBeInTheDocument();
    expect(
      screen.getByText(/no jobs recorded for this institution/i)
    ).toBeInTheDocument();
    expect(screen.getByText(/none recorded/i)).toBeInTheDocument();
    expect(screen.getByText(/unverified/i)).toBeInTheDocument();
  });
});
