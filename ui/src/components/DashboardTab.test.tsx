import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const dashboardSummary = vi.fn();
const downloadFile = vi.fn();

vi.mock("../api/client", () => ({
  api: { dashboardSummary: (...args: unknown[]) => dashboardSummary(...args) },
  ApiError: class ApiError extends Error {},
  downloadFile: (...args: unknown[]) => downloadFile(...args),
}));

import { DashboardTab } from "./DashboardTab";

const SUMMARY = {
  source: "session",
  available: true,
  summary: {
    total_accepted: 3,
    total_rejected: 1,
    accept_rate: 0.75,
    avg_hop_count: 2.5,
    avg_weighted_rubric: 4.1,
    hop_distribution: { "2": 2, "3": 1 },
    persona_distribution: { analyst: 3 },
    cluster_coverage: { cluster_0: 3 },
    rejection_breakdown: { multihop_below_floor: 1 },
    rubric_means: { factuality: 4.0 },
    cluster_targets: { cluster_0: 4 },
    cluster_achieved: { cluster_0: 3 },
    duration_s: 12.3,
  },
  rows: [
    { cluster_id: "cluster_0", hop_count: 2, persona: "analyst", question: "Q1?", answer: "A1" },
  ],
  row_count: 1,
};

describe("DashboardTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders KPIs and rows from the session summary", async () => {
    dashboardSummary.mockResolvedValue(SUMMARY);
    render(<DashboardTab connected={true} />);

    await waitFor(() => expect(dashboardSummary).toHaveBeenCalledWith("session"));
    expect(await screen.findByText("Accept rate")).toBeInTheDocument();
    expect(screen.getByText("75.0%")).toBeInTheDocument();
    expect(screen.getByText("Q1?")).toBeInTheDocument();
  });

  it("shows an info banner when no session run is available", async () => {
    dashboardSummary.mockResolvedValue({
      source: "session",
      available: false,
      summary: null,
      rows: [],
      row_count: 0,
    });
    render(<DashboardTab connected={true} />);
    expect(await screen.findByText(/No run has completed/i)).toBeInTheDocument();
  });

  it("triggers a JSON download via the export endpoint", async () => {
    dashboardSummary.mockResolvedValue(SUMMARY);
    downloadFile.mockResolvedValue(undefined);
    render(<DashboardTab connected={true} />);

    const btn = await screen.findByRole("button", { name: "Download JSON" });
    await userEvent.click(btn);
    expect(downloadFile).toHaveBeenCalledWith(
      "/dashboard/export?source=session&fmt=json",
      "multihop_eval_session.json",
    );
  });
});
