import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import TraceabilityPanel from "./TraceabilityPanel";

const sections = [
  {
    sectionKey: "Need Statement",
    paragraphs: [
      {
        text: "Paragraph one text.",
        citations: [
          {
            id: "c1",
            sectionKey: "Need Statement",
            paragraphIndex: 1,
            citationIndex: 1,
            docId: "impact.txt",
            page: 1,
            snippet: "Impact evidence snippet",
            paragraphText: "Paragraph one text.",
          },
          {
            id: "c2",
            sectionKey: "Need Statement",
            paragraphIndex: 1,
            citationIndex: 2,
            docId: "budget.pdf",
            page: 2,
            snippet: "Budget evidence snippet",
            paragraphText: "Paragraph one text.",
          },
        ],
      },
    ],
  },
];

describe("TraceabilityPanel", () => {
  it("supports citation click-through to evidence detail", () => {
    render(<TraceabilityPanel sections={sections} />);

    expect(screen.getByText("Impact evidence snippet")).toBeInTheDocument();
    expect(screen.getByText("impact.txt")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Open citation budget.pdf page 2" }));

    expect(screen.getByText("Budget evidence snippet")).toBeInTheDocument();
    expect(screen.getByText("budget.pdf")).toBeInTheDocument();
  });
});
