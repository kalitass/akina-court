"""Stretch modules, each behind an env flag (default off; unset = MVP behaviour, byte-for-byte):

    STRETCH_PRECEDENT=1   precedent.py   similar past rulings as judge context + consistency warning
    STRETCH_FRAUD=1       fraud.py       deterministic bad-faith signals rendered as extra facts
    STRETCH_SLA=1         sla.py         queue routing after the ruling + runs/queue.json
    STRETCH_FEEDBACK=1    feedback.py    human override -> runs/overrides.json + precedent re-index as "human"

Orchestrator wiring (three call sites; everything returns plain values, nothing raises on a disabled flag):

    hooks = Hooks()                                   # or Hooks(runs_dir=Path("runs"))
    extra = hooks.before_judge(table, briefs, case)   # list[Fact] with temporary ids
    if extra:
        table = table.model_copy(update={"facts": table.facts + renumber(extra, table)})
    replay(hooks.events, log.emit)                    # fraud screen + precedent lines, numbered by EventLog
    prompt = judge_prompt(...) + "\n\n" + hooks.judge_context()     # "" when no precedent / flag off
    ...
    replay(hooks.after_ruling(record), log.emit)      # consistency check, precedent index, SLA route
    hooks.on_human_override(case_id, new_ruling, reviewer="ops", note="...")   # from a review page later

`before_judge` needs neither briefs nor case (both optional); calling it right after build_fact_table lets
the advocates cite the signal facts too.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.schemas import Case, CaseBrief, CaseRecord, Event, Fact, FactTable, Ruling
from core.stretch._util import RUNS_DIR, enabled, make_event, renumber, replay
from core.stretch import precedent, fraud, sla       # noqa: E402  (order matters: feedback imports these)
from core.stretch import feedback                    # noqa: E402

__all__ = ["enabled", "Hooks", "renumber", "replay", "make_event", "precedent", "fraud", "sla", "feedback"]


class Hooks:
    """Registry the orchestrator calls at three points. Holds per-case state (signals, precedent hits, events)
    so one Hooks instance serves one run_case() call."""

    def __init__(self, runs_dir: Path = RUNS_DIR):
        self.runs_dir = runs_dir
        self.signals: list[fraud.Signal] = []
        self.hits: list[precedent.PrecedentHit] = []
        self.events: list[Event] = []            # produced by before_judge; caller replays them into the log
        self.route: Optional[sla.Route] = None

    @staticmethod
    def active() -> dict[str, bool]:
        return {n: enabled(n) for n in ("precedent", "fraud", "sla", "feedback")}

    # ---- 1. before the judge (after briefs/rebuttals, or right after the fact table) ----
    def before_judge(self, table: FactTable, briefs: Optional[list[CaseBrief]] = None,
                     case: Optional[Case] = None) -> list[Fact]:
        """Extra facts to append (temporary ids; use renumber()). Also fills self.events / self.hits / self.signals."""
        self.events, extra = [], []
        if enabled("fraud"):
            self.signals = fraud.detect(table, case)
            extra = fraud.as_facts(self.signals)
            self.events.append(fraud.event(self.signals))
        if enabled("precedent"):
            self.hits = precedent.similar(table, runs_dir=self.runs_dir)
            if self.hits:
                self.events.append(precedent.event(self.hits))
        return extra

    def judge_context(self) -> str:
        """Precedent block for the judge prompt ("" when disabled or nothing similar is stored)."""
        return precedent.judge_block(self.hits) if enabled("precedent") else ""

    # ---- 2. after verify_ruling, with the finished CaseRecord ----
    def after_ruling(self, record: CaseRecord) -> list[Event]:
        out: list[Event] = []
        r = record.ruling
        if r is None:
            return out
        if enabled("precedent"):
            lines = precedent.consistency(r, self.hits)
            out.append(make_event("verify", "check", "Precedent consistency" + (" — WARNING" if any(l.startswith("WARNING") for l in lines) else ""),
                                  "\n".join(lines)))
            precedent.index(record, self.runs_dir)
        if enabled("sla"):
            self.route = sla.route(r, record.facts.dispute_type, self.signals, getattr(record, "eligibility", None))
            sla.enqueue(record.case_id, self.route, self.runs_dir)
            out.append(sla.event(self.route, record.case_id))
        return out

    # ---- 3. a human reviewer changes the outcome (future review page) ----
    def on_human_override(self, case_id: str, new_ruling: Ruling, reviewer: str = "reviewer", note: str = "",
                          record: Optional[CaseRecord] = None) -> Optional[feedback.Override]:
        if not enabled("feedback"):
            return None
        return feedback.record_override(case_id, new_ruling, reviewer, note, self.runs_dir, record)
