import React from "react";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";

import api from "../api";
import Dashboard from "./Dashboard";

jest.mock("recharts", () => {
  const React = require("react");

  const MockContainer = ({ children }: { children: React.ReactNode }) => (
    <div data-testid="recharts-responsive-container">{children}</div>
  );

  const MockChart = ({
    children,
    data,
  }: {
    children: React.ReactNode;
    data?: unknown[];
  }) => (
    <div data-testid="recharts-chart" data-points={data?.length ?? 0}>
      {children}
    </div>
  );

  const MockPrimitive = ({ children }: { children?: React.ReactNode }) => (
    <div>{children}</div>
  );

  return {
    __esModule: true,
    ResponsiveContainer: MockContainer,
    LineChart: MockChart,
    BarChart: MockChart,
    CartesianGrid: MockPrimitive,
    XAxis: MockPrimitive,
    YAxis: MockPrimitive,
    Tooltip: MockPrimitive,
    Legend: MockPrimitive,
    Line: MockPrimitive,
    Bar: MockPrimitive,
  };
});

jest.mock("../api", () => ({
  __esModule: true,
  default: {
    get: jest.fn(),
    post: jest.fn(),
  },
}));

const mockedApi = api as jest.Mocked<typeof api>;

describe("Dashboard", () => {
  afterEach(() => {
    jest.resetAllMocks();
  });

  test("loads summary metrics and routes clicks to the selected entities", async () => {
    mockedApi.get.mockImplementation((url: string) => {
      switch (url) {
        case "/api/search-runs?limit=20":
          return Promise.resolve({
            data: [
              {
                id: "run-1",
                query: "AI safety faculty jobs",
                status: "completed",
                candidates_raw: 10,
                candidates_verified: 7,
                institutions_new: 2,
                institutions_updated: 0,
                jobs_new: 3,
                jobs_updated: 1,
                duration_ms: 1420,
                error_detail: null,
              },
              {
                id: "run-2",
                query: "ML infrastructure labs",
                status: "completed",
                candidates_raw: 5,
                candidates_verified: 2,
                institutions_new: 1,
                institutions_updated: 0,
                jobs_new: 1,
                jobs_updated: 0,
                duration_ms: 860,
                error_detail: null,
              },
            ],
          });
        case "/api/institutions?verified=true&limit=500":
          return Promise.resolve({
            data: [
              {
                id: "inst-1",
                name: "Frontier Research Lab",
                domain: "frontier.example.org",
                careers_url: "https://frontier.example.org/careers",
                institution_type: "research_lab",
                description: "Research lab",
                location: "Chicago, IL",
                is_verified: true,
                first_seen_at: "2026-04-01T12:00:00Z",
                last_seen_at: "2026-04-08T12:00:00Z",
              },
              {
                id: "inst-2",
                name: "Example University",
                domain: "example.edu",
                careers_url: "https://example.edu/jobs",
                institution_type: "university",
                description: "University",
                location: null,
                is_verified: true,
                first_seen_at: "2026-04-01T12:00:00Z",
                last_seen_at: "2026-04-07T12:00:00Z",
              },
            ],
          });
        case "/api/jobs?is_active=true&limit=500":
          return Promise.resolve({
            data: [
              {
                id: "job-1",
                title: "Research Engineer",
                url: "https://frontier.example.org/jobs/research-engineer",
                institution_name: "Frontier Research Lab",
                institution_domain: "frontier.example.org",
                location: "Chicago, IL",
                experience_level: "mid",
                salary_range: null,
                is_active: true,
                is_verified: true,
                source_query: "AI safety faculty jobs",
                first_seen_at: "2026-04-01T12:00:00Z",
                last_seen_at: "2026-04-08T12:00:00Z",
              },
              {
                id: "job-2",
                title: "Applied Scientist",
                url: "https://example.edu/jobs/applied-scientist",
                institution_name: "Example University",
                institution_domain: "example.edu",
                location: null,
                experience_level: "senior",
                salary_range: null,
                is_active: true,
                is_verified: true,
                source_query: "ML infrastructure labs",
                first_seen_at: "2026-04-01T12:00:00Z",
                last_seen_at: "2026-04-08T12:00:00Z",
              },
            ],
          });
        default:
          return Promise.reject(new Error(`Unexpected URL: ${url}`));
      }
    });

    const onSelectRun = jest.fn();
    const onSelectInstitution = jest.fn();

    render(
      <Dashboard
        onSelectRun={onSelectRun}
        onSelectInstitution={onSelectInstitution}
      />
    );

    expect(screen.getByText(/loading dashboard/i)).toBeInTheDocument();

    expect(
      await screen.findByRole("heading", { name: /discovery dashboard/i })
    ).toBeInTheDocument();
    expect(
      within(screen.getByLabelText(/summary metrics/i)).getAllByText(/^2$/)
    ).toHaveLength(3);
    expect(screen.getByText("60.0%")).toBeInTheDocument();
    expect(screen.getByText("Up 30.0 pts")).toBeInTheDocument();
    expect(
      screen.getByText(/latest completed run is trending up versus the previous run/i)
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /search run metrics/i })
    ).toBeInTheDocument();
    expect(
      screen.getByText(/verification pass rate over time/i)
    ).toBeInTheDocument();
    expect(screen.getByText(/search funnel per run/i)).toBeInTheDocument();
    expect(screen.getAllByTestId("recharts-chart")).toHaveLength(2);
    expect(screen.getByText(/ai safety faculty jobs/i)).toBeInTheDocument();
    expect(screen.getByText(/frontier research lab/i)).toBeInTheDocument();
    expect(screen.getByText(/example\.edu • unknown location/i)).toBeInTheDocument();

    fireEvent.click(screen.getByText(/ai safety faculty jobs/i));
    expect(onSelectRun).toHaveBeenCalledWith("run-1");

    fireEvent.click(
      screen.getByRole("button", { name: /frontier research lab/i })
    );
    expect(onSelectInstitution).toHaveBeenCalledWith("inst-1");

    await waitFor(() => expect(mockedApi.get).toHaveBeenCalledTimes(3));
    expect(mockedApi.get).toHaveBeenCalledWith("/api/search-runs?limit=20");
    expect(mockedApi.get).toHaveBeenCalledWith(
      "/api/institutions?verified=true&limit=500"
    );
    expect(mockedApi.get).toHaveBeenCalledWith(
      "/api/jobs?is_active=true&limit=500"
    );
  });

  test("shows helpful empty states when no data exists", async () => {
    mockedApi.get.mockResolvedValue({ data: [] });

    render(
      <Dashboard
        onSelectRun={jest.fn()}
        onSelectInstitution={jest.fn()}
      />
    );

    expect(
      await screen.findByRole("heading", { name: /discovery dashboard/i })
    ).toBeInTheDocument();
    expect(
      screen.getByText(/need at least 2 completed runs to show metrics/i)
    ).toBeInTheDocument();
    expect(screen.getByText(/no search runs yet/i)).toBeInTheDocument();
    expect(
      screen.getByText(/no verified institutions have been stored yet/i)
    ).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
  });

  test("submits a new search run from the dashboard form", async () => {
    mockedApi.get.mockResolvedValue({ data: [] });
    mockedApi.post.mockResolvedValue({ data: { id: "run-99" } });

    const onSelectRun = jest.fn();

    render(
      <Dashboard
        onSelectRun={onSelectRun}
        onSelectInstitution={jest.fn()}
      />
    );

    expect(
      await screen.findByRole("heading", { name: /discovery dashboard/i })
    ).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/start a new search run/i), {
      target: { value: "  climate tech nonprofits with engineering roles  " },
    });
    fireEvent.click(screen.getByRole("button", { name: /^search$/i }));

    await waitFor(() =>
      expect(mockedApi.post).toHaveBeenCalledWith("/api/search-runs", {
        query: "climate tech nonprofits with engineering roles",
      })
    );
    await waitFor(() => expect(onSelectRun).toHaveBeenCalledWith("run-99"));
  });
});
