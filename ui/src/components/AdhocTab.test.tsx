import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const adhocEvaluate = vi.fn();

vi.mock("../api/client", () => ({
  api: { adhocEvaluate: (...args: unknown[]) => adhocEvaluate(...args) },
  ApiError: class ApiError extends Error {},
}));

import { AdhocTab } from "./AdhocTab";

describe("AdhocTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("warns and disables submission when no config is saved", () => {
    render(<AdhocTab hasConfig={false} />);
    expect(screen.getByText(/Save a configuration/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Evaluate" })).toBeDisabled();
  });

  it("submits the QA pair and renders the verdict", async () => {
    adhocEvaluate.mockResolvedValue({
      multi_hop_pass: true,
      genuine_hop_count: 2,
      multi_hop_reason: "genuinely multi-hop",
      proof_verdict: "pass",
      corrected_proof: [{ point: "p", source_id: "sources/1" }],
      rubric_scores: {},
      rubric_weighted_score: null,
    });

    render(<AdhocTab hasConfig={true} />);

    await userEvent.type(screen.getByLabelText("Question"), "What links A and B?");
    await userEvent.type(screen.getByLabelText("Answer"), "They share C.");
    await userEvent.type(screen.getByLabelText("source-id-0"), "sources/1");
    await userEvent.type(screen.getByLabelText("source-id-1"), "sources/2");

    const evaluate = screen.getByRole("button", { name: "Evaluate" });
    expect(evaluate).toBeEnabled();
    await userEvent.click(evaluate);

    expect(adhocEvaluate).toHaveBeenCalledTimes(1);
    const payload = adhocEvaluate.mock.calls[0][0];
    expect(payload.sources).toHaveLength(2);
    expect(await screen.findByText("Multi-hop pass")).toBeInTheDocument();
    expect(screen.getByText("Proof pass")).toBeInTheDocument();
  });
});
