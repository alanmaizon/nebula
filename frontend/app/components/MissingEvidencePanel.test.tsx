import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import MissingEvidencePanel from "./MissingEvidencePanel";

describe("MissingEvidencePanel", () => {
  it("renders grouped missing evidence with upload guidance", () => {
    render(
      <MissingEvidencePanel
        status="success"
        groups={[
          {
            sectionKey: "Need Statement",
            items: [
              {
                claim: "Need comparative benchmark evidence",
                suggestedUpload: "Upload benchmark report PDF.",
                affectedSections: ["Need Statement"],
              },
            ],
          },
        ]}
      />
    );

    expect(screen.getByText("Need Statement")).toBeInTheDocument();
    expect(screen.getByText("Need comparative benchmark evidence")).toBeInTheDocument();
    expect(screen.getByText(/Upload benchmark report PDF/)).toBeInTheDocument();
  });

  it("shows loading and error states", () => {
    const { rerender } = render(<MissingEvidencePanel status="loading" groups={[]} />);
    expect(screen.getByText("Analyzing missing evidence...")).toBeInTheDocument();

    rerender(
      <MissingEvidencePanel
        status="error"
        groups={[]}
        errorMessage="Coverage computation failed"
      />
    );
    expect(screen.getByText(/Run failed before missing-evidence analysis\./)).toBeInTheDocument();
    expect(screen.getByText(/Cause: Coverage computation failed/)).toBeInTheDocument();
  });
});
