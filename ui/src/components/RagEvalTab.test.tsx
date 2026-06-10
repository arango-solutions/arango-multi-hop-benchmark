import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const ragEvalEvaluate = vi.fn();
const downloadFile = vi.fn();

vi.mock("../api/client", () => ({
  api: { ragEvalEvaluate: (...args: unknown[]) => ragEvalEvaluate(...args) },
  ApiError: class ApiError extends Error {},
  downloadFile: (...args: unknown[]) => downloadFile(...args),
}));

import { RagEvalTab } from "./RagEvalTab";

describe("RagEvalTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("warns when not connected and disables Evaluate", () => {
    render(<RagEvalTab connected={false} />);
    expect(screen.getByText(/Connect on the Configure tab/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Evaluate" })).toBeDisabled();
  });

  it("evaluates against an Arango source and renders per-system metrics", async () => {
    ragEvalEvaluate.mockResolvedValue({
      runs: [
        {
          system_name: "sys_a",
          n_responses: 2,
          n_matched_goldens: 2,
          metrics: {
            retrieval: { "ndcg@5": 0.8123 },
            generation: { groundedness: 0.95 },
            per_query: [],
          },
          started_at: "2026-01-01T00:00:00Z",
          finished_at: "2026-01-01T00:00:01Z",
        },
      ],
      n_goldens: 2,
      n_responses: 2,
      n_systems: 1,
      load_errors: [],
    });

    render(<RagEvalTab connected={true} />);

    // Switch to the Arango source so no file upload is required.
    await userEvent.selectOptions(screen.getByLabelText("Response source"), "arango");

    const evaluate = screen.getByRole("button", { name: "Evaluate" });
    expect(evaluate).toBeEnabled();
    await userEvent.click(evaluate);

    expect(ragEvalEvaluate).toHaveBeenCalledTimes(1);
    expect(ragEvalEvaluate.mock.calls[0][0].response_source).toBe("arango");
    expect(await screen.findByRole("heading", { name: "sys_a" })).toBeInTheDocument();
    expect(screen.getByText("ndcg@5")).toBeInTheDocument();
    expect(screen.getByText("0.8123")).toBeInTheDocument();
  });

  it("exports results after a successful run", async () => {
    ragEvalEvaluate.mockResolvedValue({
      runs: [
        {
          system_name: "sys_a",
          n_responses: 1,
          n_matched_goldens: 1,
          metrics: { retrieval: {}, generation: {}, per_query: [] },
          started_at: "2026-01-01T00:00:00Z",
          finished_at: "2026-01-01T00:00:01Z",
        },
      ],
      n_goldens: 1,
      n_responses: 1,
      n_systems: 1,
      load_errors: [],
    });
    downloadFile.mockResolvedValue(undefined);

    render(<RagEvalTab connected={true} />);
    await userEvent.selectOptions(screen.getByLabelText("Response source"), "arango");
    await userEvent.click(screen.getByRole("button", { name: "Evaluate" }));

    const excel = await screen.findByRole("button", { name: "Download Excel" });
    await userEvent.click(excel);
    expect(downloadFile).toHaveBeenCalledWith("/rag_eval/export?fmt=excel", "rag_eval.xlsx");
  });
});
