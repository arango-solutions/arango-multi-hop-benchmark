import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const saveConfig = vi.fn();

vi.mock("../api/client", () => ({
  api: {
    saveConfig: (...args: unknown[]) => saveConfig(...args),
    loadFromEnv: vi.fn(),
    collections: vi.fn().mockResolvedValue({ collections: [] }),
    clusters: vi.fn().mockResolvedValue({ clusters: [] }),
    databases: vi.fn().mockResolvedValue({ databases: [] }),
  },
  ApiError: class ApiError extends Error {},
}));

import { ConfigureTab } from "./ConfigureTab";

const CONFIG_RESP = {
  saved: null,
  defaults: {
    project_name: "multihop_eval",
    collections: {
      similarity_collection: "multihop_eval_similarities",
      relations_collection: "multihop_eval_corpus_relations",
      rags_collection: "multihop_eval_rags",
      sources_collection: "multihop_eval_sources",
      domains_collection: "multihop_eval_domains",
      qa_collection: "qa_pairs_multihop_eval_v1",
    },
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
};

function renderTab() {
  return render(
    <ConfigureTab
      connection={null}
      configResp={CONFIG_RESP as never}
      onConnectionChange={vi.fn()}
      refreshConnection={vi.fn().mockResolvedValue(CONFIG_RESP)}
      refreshConfig={vi.fn().mockResolvedValue(CONFIG_RESP)}
    />,
  );
}

describe("ConfigureTab project name propagation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("prefills collection names derived from the default project name", () => {
    renderTab();
    expect(screen.getByLabelText<HTMLInputElement>("Domains collection").value).toBe(
      "multihop_eval_domains",
    );
    expect(screen.getByLabelText<HTMLInputElement>("QA collection (output)").value).toBe(
      "qa_pairs_multihop_eval_v1",
    );
  });

  it("re-derives every collection when the project name changes", async () => {
    renderTab();
    const project = screen.getByLabelText("Autograph project name");
    await userEvent.clear(project);
    await userEvent.type(project, "acme");

    expect(screen.getByLabelText<HTMLInputElement>("Sources collection").value).toBe(
      "acme_sources",
    );
    expect(screen.getByLabelText<HTMLInputElement>("Domains collection").value).toBe(
      "acme_domains",
    );
    expect(screen.getByLabelText<HTMLInputElement>("Relations collection").value).toBe(
      "acme_corpus_relations",
    );
    expect(screen.getByLabelText<HTMLInputElement>("QA collection (output)").value).toBe(
      "qa_pairs_acme_v1",
    );
  });

  it("sends the project name and derived collections on save", async () => {
    saveConfig.mockResolvedValue(CONFIG_RESP);
    renderTab();
    const project = screen.getByLabelText("Autograph project name");
    await userEvent.clear(project);
    await userEvent.type(project, "acme");
    await userEvent.click(screen.getByRole("button", { name: "Save configuration" }));

    expect(saveConfig).toHaveBeenCalledTimes(1);
    const payload = saveConfig.mock.calls[0][0];
    expect(payload.project_name).toBe("acme");
    expect(payload.collections.domains_collection).toBe("acme_domains");
  });
});
