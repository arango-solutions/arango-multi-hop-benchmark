import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HowToTab } from "./HowToTab";

describe("HowToTab", () => {
  it("renders the overview and tab walkthrough sections", () => {
    render(<HowToTab />);

    expect(
      screen.getByRole("heading", { level: 2, name: "How-To" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "What it does" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Quick start" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Configure" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Run" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Ad-hoc" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "RAG Eval" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Tips" })).toBeInTheDocument();
    expect(screen.getByText(/Multi-Hop Eval generates, validates, and scores/i)).toBeInTheDocument();
    expect(screen.getAllByText(/qa_pair_key/).length).toBeGreaterThan(0);
  });
});
