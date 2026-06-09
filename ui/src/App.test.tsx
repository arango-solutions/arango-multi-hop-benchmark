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
  },
  ApiError: class ApiError extends Error {},
  runEventsUrl: () => "/run/events",
}));

import { App } from "./App";

describe("App", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders all five tabs with Configure active by default", () => {
    render(<App />);
    for (const label of ["Configure", "Run", "Dashboard", "Ad-hoc", "RAG Eval"]) {
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

  it("shows a coming-soon placeholder for the Dashboard tab", async () => {
    render(<App />);
    await userEvent.click(screen.getByRole("tab", { name: "Dashboard" }));
    expect(screen.getByText(/coming in a follow-up slice/i)).toBeInTheDocument();
  });
});
