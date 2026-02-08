# Nebula: A Build Log on Designing Trust-First AI for Grants

This post is our engineering reflection for the Amazon Nova Hackathon, not a repeat of our submission form.
Tag: `Amazon-Nova`

## The creative question we started with

Most grant-writing tools optimize for speed of text generation.
We chose a different question: **how do we reduce decision risk for nonprofit teams under deadline pressure?**

That changed everything about the design.

## Creative process: design from failure modes, not feature lists

Before writing product copy, we mapped the three ways grant drafts fail in practice:
- a requirement is missed
- a claim is unsupported
- a mismatch is found too late in review

From there, we built Nebula backward from those failure points.
Each major component exists to make one of those failures visible earlier.

## Three design bets that shaped the system

1. Citation-first drafting over fluent drafting  
   We treated unsupported prose as a bug, not a style issue. Outputs need `doc_id`, `page`, and snippet references so a reviewer can challenge claims quickly.

2. Schema-first artifacts over free-form output  
   We forced requirements, drafts, and coverage into structured contracts. This made validation and repair deterministic, and reduced silent formatting drift.

3. Specialized roles over one large prompt  
   The planned Nova path uses role boundaries (analyst, researcher, writer, reviewer) with deterministic orchestration, because bounded responsibilities are easier to test and audit.

## What we intentionally did not build

Creativity also meant saying no:
- no broad autonomous behavior that cannot be inspected
- no hidden scoring logic without traceable evidence
- no UI complexity that hides missing information from operators

That restraint gave us a clearer reliability surface and a simpler debugging loop.

## Potential influence beyond this project

If this pattern works at scale, the impact is bigger than grant writing:
- smaller nonprofits can compete with better-resourced organizations using evidence-backed workflows
- reviewers and leadership teams can audit claims faster with less back-and-forth
- compliance-heavy writing domains (public sector, healthcare, education funding) can reuse the same trust-first architecture

The important shift is cultural as much as technical: move AI from "draft generator" to "decision support with evidence accountability."

## What we are testing next

- quantify quality with reproducible metrics (coverage completeness, unsupported-claim rate, iteration time)
- complete Nova runtime proof in the production path with explicit model-call evidence
- compare baseline deterministic RAG vs staged agent orchestration for measurable operator benefit

## Closing

The project goal is not more words per minute.
It is fewer bad decisions per submission.

`#Amazon-Nova` `#AgenticAI` `#AmazonBedrock` `#NonprofitTech`
