# Archived benchmark · 2026-10-09 · keyword-rule version

These are the summary files of the benchmark run on 2026-10-09 (13:33–14:19 UTC) against the version of the court in
which code labelled chat messages by keyword (agreement / request / threat) and the policy engine closed the consent
question and triggered SAFE-1 on those labels. The full per-run files, the audit sample and the code and policy text of
that version are in git at commit `a1c6278`.

Why it was replaced: a keyword is not a reading of what a message means. "I am not okay with this detour" was labelled
agreement, "I cannot find you at the pickup point" was labelled a threat, and a missing GPS trace read as "no detour".
Benchmark case B-0049 had the keyword behaviour written into its reference answer (escalate on "I'll find you at the
lobby"); that reference now expects a ruling on the detour.

From 2026-10-10 the fact table records who said what and when; the court reads what it meant (findings may be
undetermined); missing evidence is a finding of its own and sends the case to a person. The results on the live pages
are from the re-run against that version. Numbers from this archive and from the live pages are not comparable.
