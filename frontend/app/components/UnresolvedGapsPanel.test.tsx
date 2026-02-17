import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import UnresolvedGapsPanel from "./UnresolvedGapsPanel";

describe("UnresolvedGapsPanel", () => {
  it("renders requirement-level unresolved gaps with status and notes", () => {
    render(
      <UnresolvedGapsPanel
        status="success"
        gaps={[
          {
            requirementId: "Q1",
            internalId: "Q1",
            originalId: "REQ-101",
            status: "missing",
            notes: "No evidence-backed paragraph found.",
            evidenceRefs: [],
          },
          {
            requirementId: "Q2",
            internalId: "Q2",
            originalId: "REQ-202",
            status: "partial",
            notes: "Coverage is shallow and needs stronger references.",
            evidenceRefs: ["rfp.pdf:p3"],
          },
        ]}
      />
    );

    expect(screen.getByText("Unresolved Coverage Gaps")).toBeInTheDocument();
    expect(screen.getByText("Q1")).toBeInTheDocument();
    expect(screen.getByText(/REQ-101/)).toBeInTheDocument();
    expect(screen.getByText("No evidence-backed paragraph found.")).toBeInTheDocument();
    expect(screen.getByText(/rfp.pdf:p3/)).toBeInTheDocument();
  });

  it("shows an empty message when no unresolved gaps remain", () => {
    render(<UnresolvedGapsPanel status="success" gaps={[]} />);
    expect(screen.getByText(/No unresolved partial\/missing coverage gaps/)).toBeInTheDocument();
  });
});
