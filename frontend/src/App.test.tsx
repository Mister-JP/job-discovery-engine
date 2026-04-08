import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";

import App from "./App";

jest.mock("./pages/Dashboard", () => {
  return function MockDashboard(props: {
    onSelectRun: (runId: string) => void;
    onSelectInstitution: (institutionId: string) => void;
  }) {
    return (
      <div>
        <h1>Mock dashboard</h1>
        <button onClick={() => props.onSelectRun("run-123")}>Open run</button>
        <button onClick={() => props.onSelectInstitution("inst-456")}>
          Open institution
        </button>
      </div>
    );
  };
});

jest.mock("./pages/SearchRunDetail", () => {
  return function MockSearchRunDetail(props: {
    runId: string;
    onBack: () => void;
  }) {
    return (
      <div>
        <div>Mock run detail for {props.runId}</div>
        <button onClick={props.onBack}>Back</button>
      </div>
    );
  };
});

jest.mock("./pages/InstitutionDetail", () => {
  return function MockInstitutionDetail(props: {
    institutionId: string;
    onBack: () => void;
  }) {
    return (
      <div>
        <div>Mock institution detail for {props.institutionId}</div>
        <button onClick={props.onBack}>Back</button>
      </div>
    );
  };
});

test("renders the dashboard by default", () => {
  render(<App />);

  expect(screen.getByRole("heading", { name: /mock dashboard/i })).toBeInTheDocument();
});

test("opens and exits the search run detail page", () => {
  render(<App />);

  fireEvent.click(screen.getByRole("button", { name: /open run/i }));

  expect(screen.getByText(/mock run detail for run-123/i)).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /^back$/i }));

  expect(screen.getByRole("heading", { name: /mock dashboard/i })).toBeInTheDocument();
});

test("opens and exits the institution detail page", () => {
  render(<App />);

  fireEvent.click(screen.getByRole("button", { name: /open institution/i }));

  expect(
    screen.getByText(/mock institution detail for inst-456/i)
  ).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /^back$/i }));

  expect(screen.getByRole("heading", { name: /mock dashboard/i })).toBeInTheDocument();
});
