import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Stub the API client so the smoke test never hits the network.
vi.mock("./api/client", () => ({
  api: {
    connectionStatus: vi.fn().mockResolvedValue({
      status: "disconnected",
      db: null,
      error: null,
      last_tested: null,
      amp: { detected: false, deployment_name: null, endpoint: null },
    }),
    getConfig: vi.fn().mockResolvedValue({
      saved: null,
      defaults: {
        collections: {},
        llm: {
          api_url: "https://api.openai.com/v1/chat/completions",
          api_key: "",
          model: "gpt-4.1",
          temperature: 0.3,
          max_tokens: 4000,
          timeout_s: 180,
          retries: 3,
        },
        eval: {
          target_clusters: ["cluster_0"],
          n_questions: 50,
          hop_dist: [2, 3],
          hop_dist_weights: [0.7, 0.3],
          max_verify_rounds: 3,
          save_to_arango: true,
          score_with_rubric: true,
        },
        personas: [],
        rubric_fields: [],
      },
    }),
    collections: vi.fn().mockResolvedValue({ collections: [] }),
    runStatus: vi.fn().mockResolvedValue({
      status: "idle",
      accepted: 0,
      target: 0,
      summary: null,
      error: null,
      log: [],
    }),
    dashboardSummary: vi.fn().mockResolvedValue({
      source: "session",
      available: false,
      summary: null,
      rows: [],
      row_count: 0,
    }),
    adhocEvaluate: vi.fn(),
    ragEvalEvaluate: vi.fn(),
  },
  ApiError: class ApiError extends Error {},
  runEventsUrl: () => "/run/events",
  downloadFile: vi.fn(),
}));

import { App } from "./App";

const storage = new Map<string, string>();

describe("App", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    storage.clear();
    vi.stubGlobal("localStorage", {
      getItem: vi.fn((key: string) => storage.get(key) ?? null),
      setItem: vi.fn((key: string, value: string) => storage.set(key, value)),
      removeItem: vi.fn((key: string) => storage.delete(key)),
      clear: vi.fn(() => storage.clear()),
    });
    document.documentElement.classList.remove("dark");
  });

  it("renders all six tabs with Configure active by default", () => {
    render(<App />);
    for (const label of ["Configure", "Run", "Dashboard", "Ad-hoc", "RAG Eval", "How-To"]) {
      expect(screen.getByRole("tab", { name: label })).toBeInTheDocument();
    }
    expect(screen.getByRole("tab", { name: "Configure" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("switches to the Run tab when clicked", async () => {
    render(<App />);
    await userEvent.click(screen.getByRole("tab", { name: "Run" }));
    expect(
      screen.getByRole("heading", { level: 2, name: "Run" }),
    ).toBeInTheDocument();
  });

  it("defaults to light mode", () => {
    render(<App />);
    expect(document.documentElement).not.toHaveClass("dark");
    expect(
      screen.getByRole("button", { name: "Switch to dark mode" }),
    ).toBeInTheDocument();
    expect(localStorage.getItem("multihop-eval-theme")).toBe("light");
  });

  it("toggles and persists dark mode", async () => {
    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Switch to dark mode" }));
    expect(document.documentElement).toHaveClass("dark");
    expect(localStorage.getItem("multihop-eval-theme")).toBe("dark");
    expect(
      screen.getByRole("button", { name: "Switch to light mode" }),
    ).toBeInTheDocument();
  });

  it("loads a persisted dark mode preference", () => {
    localStorage.setItem("multihop-eval-theme", "dark");
    render(<App />);
    expect(document.documentElement).toHaveClass("dark");
    expect(
      screen.getByRole("button", { name: "Switch to light mode" }),
    ).toBeInTheDocument();
  });

  it("renders the Dashboard tab", async () => {
    render(<App />);
    await userEvent.click(screen.getByRole("tab", { name: "Dashboard" }));
    expect(
      screen.getByRole("heading", { level: 2, name: "Dashboard" }),
    ).toBeInTheDocument();
  });

  it("renders the Ad-hoc tab", async () => {
    render(<App />);
    await userEvent.click(screen.getByRole("tab", { name: "Ad-hoc" }));
    expect(
      screen.getByRole("heading", { level: 2, name: "Ad-hoc" }),
    ).toBeInTheDocument();
  });

  it("renders the RAG Eval tab", async () => {
    render(<App />);
    await userEvent.click(screen.getByRole("tab", { name: "RAG Eval" }));
    expect(
      screen.getByRole("heading", { level: 2, name: "RAG Eval" }),
    ).toBeInTheDocument();
  });

  it("renders the How-To tab", async () => {
    render(<App />);
    await userEvent.click(screen.getByRole("tab", { name: "How-To" }));
    expect(
      screen.getByRole("heading", { level: 2, name: "How-To" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Quick start/i)).toBeInTheDocument();
  });
});
