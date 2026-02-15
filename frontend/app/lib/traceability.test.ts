import { describe, expect, it } from "vitest";

import { extractTraceabilityData } from "./traceability";

describe("extractTraceabilityData", () => {
  it("extracts sections, citations, and missing evidence groups", () => {
    const payload = {
      bundle: {
        json: {
          drafts: {
            "Need Statement": {
              draft: {
                paragraphs: [
                  {
                    text: "We served 1240 households in 2024.",
                    citations: [
                      {
                        doc_id: "impact.txt",
                        page: 1,
                        snippet: "served 1240 households",
                      },
                    ],
                  },
                ],
                missing_evidence: [
                  {
                    claim: "Need benchmark comparison",
                    suggested_upload: "Upload external benchmark report.",
                  },
                ],
              },
            },
          },
          missing_evidence: [
            {
              claim: "Need letters of support",
              suggested_upload: "Upload partner letters.",
              affected_sections: ["Attachments"],
            },
          ],
        },
      },
    };

    const result = extractTraceabilityData(payload);

    expect(result.sections).toHaveLength(1);
    expect(result.sections[0].sectionKey).toBe("Need Statement");
    expect(result.citationCount).toBe(1);
    expect(result.sections[0].paragraphs[0].citations[0].docId).toBe("impact.txt");
    expect(result.missingEvidenceGroups).toHaveLength(2);
    expect(result.missingEvidenceGroups.map((group) => group.sectionKey)).toEqual([
      "Attachments",
      "Need Statement",
    ]);
  });
});
