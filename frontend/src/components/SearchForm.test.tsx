import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import api from "../api";
import SearchForm from "./SearchForm";

jest.mock("../api", () => ({
  __esModule: true,
  default: {
    post: jest.fn(),
  },
}));

const mockedApi = api as jest.Mocked<typeof api>;

describe("SearchForm", () => {
  afterEach(() => {
    jest.resetAllMocks();
  });

  test("validates short queries before posting", async () => {
    render(<SearchForm onComplete={jest.fn()} />);

    fireEvent.change(screen.getByLabelText(/start a new search run/i), {
      target: { value: "ai" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^search$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /query must be at least 3 characters/i
    );
    expect(mockedApi.post).not.toHaveBeenCalled();
  });

  test("shows progress while the search request is in flight and completes", async () => {
    let resolvePost:
      | ((value: { data: { id: string } }) => void)
      | undefined;

    mockedApi.post.mockReturnValue(
      new Promise((resolve) => {
        resolvePost = resolve;
      })
    );

    const onComplete = jest.fn();
    render(<SearchForm onComplete={onComplete} />);

    fireEvent.change(screen.getByLabelText(/start a new search run/i), {
      target: { value: "AI safety research labs hiring" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^search$/i }));

    expect(mockedApi.post).toHaveBeenCalledWith("/api/search-runs", {
      query: "AI safety research labs hiring",
    });
    expect(screen.getByRole("button", { name: /searching/i })).toBeDisabled();
    expect(
      screen.getByText(/searching the web, verifying results, and storing data/i)
    ).toBeInTheDocument();

    resolvePost?.({ data: { id: "run-123" } });

    await waitFor(() => expect(onComplete).toHaveBeenCalledWith("run-123"));
    await waitFor(() =>
      expect(screen.getByLabelText(/start a new search run/i)).toHaveValue("")
    );
  });

  test("shows API errors returned by the backend", async () => {
    mockedApi.post.mockRejectedValue({
      response: {
        data: {
          detail: "Gemini API error",
        },
      },
    });

    render(<SearchForm onComplete={jest.fn()} />);

    fireEvent.change(screen.getByLabelText(/start a new search run/i), {
      target: { value: "AI research institutions" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^search$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /gemini api error/i
    );
    expect(screen.getByRole("button", { name: /^search$/i })).toBeEnabled();
  });
});
