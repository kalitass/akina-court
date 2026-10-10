# Submission pack — working draft

Source: `docs/tencent-hackathon-sg-2026-handbook.pdf`, section 8 and the Ryde track description. The handbook lists **16 October 2026** as the project-submission date; the exact time and form fields still need to be checked in the live submission form.

## Ready to copy into the form

**Project title:** Akina Court — Ryde Dispute Court

**Short blurb (7 words; handbook limit is under 10):** A verifiable AI court for ride-hailing disputes.

**Project description:**

Akina Court helps ride-hailing support teams review route-deviation and no-show fee disputes. A rider and a driver each have an AI advocate that reads the same numbered evidence through logged tools, submits a brief, and rebuts the other side. A judge handles only questions that the written policy and measured facts cannot settle. The system also detects safety concerns and sends those cases to a person.

The prototype turns synthetic trip records, GPS traces, fare lines, chat, and external route and traffic data into a reproducible fact table. A numbered, sourced policy runs as code before and after the agents speak. The final check rejects nonexistent citations, unsupported outcomes, and incorrect amounts. It creates proposed actions and separate plain-language notices; the prototype does not transfer money or punish an account. Account actions and unresolved cases go to human review. An event stream shows each agent's evidence reads and arguments, and a receipt fingerprints the case, policy, code, and model.

In a historical 49-case synthetic policy-conformance benchmark, the full court matched the policy-derived reference outcome, amount, and hand-off on 49/49 cases. The code check let 0 wrong core decisions pass; 42 cases were eligible for automatic handling and 7 went to a person. These are internal results on synthetic data, not an estimate of accuracy on real Ryde disputes. The current code has been updated since that benchmark, so its present latency and token cost have not been remeasured.

The demo is a working web application with route and court replays, an operations queue, a policy page, a results page, and an architecture diagram. The stored DISP-002 sample replay is paused pending a verified rerun; other cases remain available.

## Required items

| Item | Current state | Next action |
|---|---|---|
| Project title and blurb | Draft above | Paste after team review |
| Project description | Draft above; README and results provide detail | Match the submission form's actual fields and limits |
| CodeBuddy or WorkBuddy usage proof | Not collected in this repository | Select at least **3** development-chat screenshots or a screen recording, with visible work relevant to Akina Court |
| 16:9 cover image | `web/cover.png` exists at 1920×1080, but still labels a $3.99 refund as "verified" without saying it is only proposed | Revise the cover before uploading; handbook recommends 380×216 px |
| Source code | Private GitHub repository with open draft PR | Ensure judges can access the final reviewed commit; do not submit an inaccessible private link |
| Architecture diagram | `web/architecture-current.svg` describes the current three-agent flow and proposed actions | Inspect readability in the submission preview |
| Working two-category demo | Route deviation and no-show examples exist | Walk through C-0001 and C-0004 end to end on the final deployed site |
| Live project URL | Existing site is available | Verify it reflects the reviewed release before submitting |

## Optional, valuable for judging

- A 5–8 minute demo video: problem and users → one route case → one no-show case → visible agent exchange and policy check → human hand-off → limits and CodeBuddy/WorkBuddy development reflection.
- Demo screenshots that show the evidence, opposing briefs, code check, and operations hand-off without implying a real refund occurred.
- The handbook's Demo Day criteria are useful for presentation, but they do not replace the preliminary submission form requirements.

## Open product decisions

- Ask the organiser how the sample's 8-minute no-show threshold relates to its 5-minute free wait. The current rule consumes the latter and stores the former without applying it.
- Regenerate and check DISP-002 before restoring its replay. See `runs/STALE_RECORDS.md`.
- Keep the historical benchmark results labelled as synthetic policy conformance until the changed code is benchmarked again.
