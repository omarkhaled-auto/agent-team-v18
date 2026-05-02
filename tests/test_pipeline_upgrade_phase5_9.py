"""Phase 5.9 — milestone AC-count cap + auto-split fixtures.

Plan: docs/plans/2026-04-28-phase-5-quality-milestone.md §L.

Locks for this phase:

* MASTER_PLAN.md parser/generator/status-updater accept suffixed IDs
  (`milestone-7-a`, `milestone-7-b`, ...) so auto-split halves round-trip
  through every plumbing layer (Blocker 1 from scope check-in).
* `split_oversized_milestones` heuristic: emit cap-2 chunks while the
  remainder is > cap; the final remainder may equal cap. 12→8/4, 15→8/7,
  18→8/10, 19→8/8/3, 21→8/8/5.
* Stable id pattern: flat `<id>-a`, `-b`, `-c`, ... up to `-z` (26 halves
  max; pre-mutation validator error if exceeded).
* Per-half active REQUIREMENTS.md scoped to the half's AC refs (one
  checkbox per AC); original archived under
  `<orig-id>/_phase_5_9_split_source/REQUIREMENTS.original.md` so
  directory-scanner consumers (`_list_milestone_ids`,
  `aggregate_milestone_convergence`, `get_cross_milestone_wiring`,
  `stack_contract._collect_requirements_texts`) skip the orig source.
* `validate_plan(milestones, *, ac_cap)` gates above cap (error, not
  warn); `< 3` advisory floor preserved; foundation 0-AC milestones
  exempt; `ac_cap=0` disables both split and gate (legacy behaviour).
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from agent_team_v15.milestone_manager import (
    MILESTONE_AC_CAP_DEFAULT,
    MAX_SPLIT_HALVES,
    MasterPlan,
    MasterPlanMilestone,
    MilestoneManager,
    aggregate_milestone_convergence,
    generate_master_plan_md,
    generate_master_plan_json,
    load_master_plan_json,
    parse_master_plan,
    split_oversized_milestones,
    update_master_plan_status,
    validate_plan,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _milestone(
    id_: str,
    *,
    title: str = "",
    dependencies: list[str] | None = None,
    ac_count: int = 0,
    template: str = "full_stack",
) -> MasterPlanMilestone:
    """Build a MasterPlanMilestone with N synthetic AC refs."""

    return MasterPlanMilestone(
        id=id_,
        title=title or f"Title for {id_}",
        dependencies=list(dependencies or []),
        description=f"Description for {id_}",
        template=template,
        ac_refs=[f"AC-FEAT-{i:03d}" for i in range(1, ac_count + 1)],
        feature_refs=[f"F-FEAT-{i:03d}" for i in range(1, max(1, ac_count // 3) + 1)] if ac_count else [],
    )


def _seed_run_dir_with_master_plan(
    tmp_path: Path,
    milestones: list[MasterPlanMilestone],
    *,
    write_requirements: bool = True,
) -> Path:
    """Create .agent-team/MASTER_PLAN.json + per-milestone REQUIREMENTS.md."""

    cwd = tmp_path
    agent_team = cwd / ".agent-team"
    agent_team.mkdir(parents=True, exist_ok=True)
    generate_master_plan_json(milestones, agent_team / "MASTER_PLAN.json")
    generate_master_plan_md(cwd)
    if write_requirements:
        for ms in milestones:
            mdir = agent_team / "milestones" / ms.id
            mdir.mkdir(parents=True, exist_ok=True)
            req = mdir / "REQUIREMENTS.md"
            checkbox_lines = "\n".join(
                f"- [ ] {ref} (review_cycles: 0)" for ref in ms.ac_refs
            )
            req.write_text(
                f"# Milestone {ms.id} — {ms.title}\n\n"
                f"- **ID:** {ms.id}\n\n"
                f"## AC Refs\n\n{checkbox_lines}\n",
                encoding="utf-8",
            )
    return cwd


# ---------------------------------------------------------------------------
# Blocker 1 — parser/generator/status-updater accept suffixed IDs
# ---------------------------------------------------------------------------


def test_parse_master_plan_accepts_suffixed_ids():
    """Phase 5.9 §L Blocker 1 — `## Milestone 7-a:` parses to id=milestone-7-a."""

    content = textwrap.dedent(
        """
        # MASTER PLAN

        ## Milestone 1: Foundation
        - ID: milestone-1
        - Status: PENDING
        - Dependencies: none
        - Template: full_stack
        - AC-Refs:

        ## Milestone 7-a: Invoice Creation (Part 1)
        - ID: milestone-7-a
        - Status: PENDING
        - Dependencies: milestone-1
        - Template: full_stack
        - AC-Refs: AC-INV-001, AC-INV-002

        ## Milestone 7-b: Invoice Creation (Part 2)
        - ID: milestone-7-b
        - Status: PENDING
        - Dependencies: milestone-1, milestone-7-a
        - Template: full_stack
        - AC-Refs: AC-INV-003, AC-INV-004
        """
    ).strip()

    plan = parse_master_plan(content)
    parsed_ids = [m.id for m in plan.milestones]

    assert parsed_ids == ["milestone-1", "milestone-7-a", "milestone-7-b"]
    assert plan.get_milestone("milestone-7-b").dependencies == [
        "milestone-1", "milestone-7-a",
    ]


def test_generate_master_plan_md_emits_parser_compatible_heading_for_suffixed_id(tmp_path):
    """Phase 5.9 §L Blocker 1 — generator emits `## Milestone 7-a:` (not `## Milestone milestone-7-a:`)."""

    milestones = [
        _milestone("milestone-1", ac_count=0, title="Foundation"),
        _milestone("milestone-7-a", title="Invoice Creation (Part 1)", ac_count=2,
                   dependencies=["milestone-1"]),
        _milestone("milestone-7-b", title="Invoice Creation (Part 2)", ac_count=2,
                   dependencies=["milestone-1", "milestone-7-a"]),
    ]
    cwd = _seed_run_dir_with_master_plan(tmp_path, milestones, write_requirements=False)

    md = (cwd / ".agent-team" / "MASTER_PLAN.md").read_text(encoding="utf-8")

    assert "## Milestone 1: Foundation" in md
    assert "## Milestone 7-a: Invoice Creation (Part 1)" in md
    assert "## Milestone 7-b: Invoice Creation (Part 2)" in md
    # Negative — the pre-Phase-5.9 broken shape MUST NOT appear:
    assert "## Milestone milestone-7-a" not in md
    assert "## Milestone milestone-7-b" not in md

    # Round-trip: generated MD parses back to the same id list.
    plan = parse_master_plan(md)
    assert [m.id for m in plan.milestones] == [
        "milestone-1", "milestone-7-a", "milestone-7-b",
    ]


def test_update_master_plan_status_targets_suffixed_id():
    """Phase 5.9 §L Blocker 1 — status update on milestone-7-b doesn't touch milestone-7-a."""

    content = textwrap.dedent(
        """
        # MASTER PLAN

        ## Milestone 7-a: Invoice Creation (Part 1)
        - ID: milestone-7-a
        - Status: PENDING

        ## Milestone 7-b: Invoice Creation (Part 2)
        - ID: milestone-7-b
        - Status: PENDING
        """
    ).strip()

    updated = update_master_plan_status(content, "milestone-7-b", "COMPLETE")
    plan = parse_master_plan(updated)

    a = plan.get_milestone("milestone-7-a")
    b = plan.get_milestone("milestone-7-b")
    assert a is not None and b is not None
    assert a.status == "PENDING"
    assert b.status == "COMPLETE"


def test_parse_master_plan_unchanged_for_legacy_numeric_only_headers():
    """Phase 5.9 §L Blocker 1 — backward-compat: pre-Phase-5.9 plans parse byte-identically."""

    content = textwrap.dedent(
        """
        # MASTER PLAN

        ## Milestone 1: Foundation
        - ID: milestone-1
        - Status: PENDING

        ## Milestone 2: Auth
        - ID: milestone-2
        - Status: COMPLETE
        - Dependencies: milestone-1

        ## Milestone 3: Polish
        - ID: milestone-3
        - Status: IN_PROGRESS
        - Dependencies: milestone-1, milestone-2
        """
    ).strip()

    plan = parse_master_plan(content)

    assert [m.id for m in plan.milestones] == [
        "milestone-1", "milestone-2", "milestone-3",
    ]
    assert plan.get_milestone("milestone-3").status == "IN_PROGRESS"
    assert plan.get_milestone("milestone-3").dependencies == [
        "milestone-1", "milestone-2",
    ]


def test_parser_rejects_double_letter_suffix_id():
    """Phase 5.9 §L — single-letter suffix only; `## Milestone 7-aa:` does not parse as a milestone."""

    content = textwrap.dedent(
        """
        # MASTER PLAN

        ## Milestone 7-aa: Should not parse
        - ID: milestone-7-aa
        - Status: PENDING
        """
    ).strip()

    plan = parse_master_plan(content)
    parsed_ids = [m.id for m in plan.milestones]
    assert parsed_ids == []


# ---------------------------------------------------------------------------
# Splitter heuristic locks (cap=10, cap-2=8 chunks, final remainder ≤ cap)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ac_count, expected_split_sizes",
    [
        (12, [8, 4]),    # plan §L.2 AC2 — the canonical example
        (15, [8, 7]),    # M1's empirical 15-AC shape
        (18, [8, 10]),   # final remainder may equal cap exactly
        (19, [8, 8, 3]), # recursion: 3-way flat letters
        (21, [8, 8, 5]),
        (11, [8, 3]),    # cap+1
        (22, [8, 8, 6]),
    ],
)
def test_split_heuristic_cap_minus_2_chunking(ac_count, expected_split_sizes):
    """Phase 5.9 §L — split heuristic: cap-2 chunks while remainder > cap; final remainder may be cap."""

    orig = _milestone("milestone-7", title="Big Feature", ac_count=ac_count,
                      dependencies=["milestone-1"])
    result = split_oversized_milestones([orig], cap=10)

    assert [len(m.ac_refs) for m in result] == expected_split_sizes


def test_split_no_op_when_all_milestones_at_or_below_cap():
    """Phase 5.9 §L AC4 — backward-compat: ≤cap milestones byte-identical post-split."""

    milestones = [
        _milestone("milestone-1", ac_count=0),  # foundation
        _milestone("milestone-2", ac_count=5, dependencies=["milestone-1"]),
        _milestone("milestone-3", ac_count=10, dependencies=["milestone-2"]),  # at-cap
        _milestone("milestone-4", ac_count=3, dependencies=["milestone-3"]),
    ]
    result = split_oversized_milestones(milestones, cap=10)

    assert [m.id for m in result] == [m.id for m in milestones]
    assert [len(m.ac_refs) for m in result] == [0, 5, 10, 3]
    assert [m.dependencies for m in result] == [m.dependencies for m in milestones]


def test_split_30_acs_across_6_milestones_no_split_needed():
    """Phase 5.9 §L AC1 — 30 ACs across 6 milestones; no milestone over cap → no split."""

    milestones = [
        _milestone("milestone-1", ac_count=0),  # foundation
        _milestone("milestone-2", ac_count=5, dependencies=["milestone-1"]),
        _milestone("milestone-3", ac_count=5, dependencies=["milestone-2"]),
        _milestone("milestone-4", ac_count=5, dependencies=["milestone-3"]),
        _milestone("milestone-5", ac_count=8, dependencies=["milestone-4"]),
        _milestone("milestone-6", ac_count=7, dependencies=["milestone-5"]),
    ]
    result = split_oversized_milestones(milestones, cap=10)

    assert len(result) == 6
    assert sum(len(m.ac_refs) for m in result) == 30


def test_foundation_milestone_zero_acs_never_split():
    """Phase 5.9 §L — 0-AC foundation milestones are split-exempt (would be nonsensical)."""

    milestones = [_milestone("milestone-1", ac_count=0, title="Foundation")]
    result = split_oversized_milestones(milestones, cap=10)
    assert len(result) == 1
    assert result[0].id == "milestone-1"
    assert result[0].ac_refs == []


def test_split_preserves_ac_order_first_n_in_a_rest_in_b():
    """Phase 5.9 §L — cumulative AC ordering preserved across split halves."""

    orig = _milestone("milestone-7", title="Feature", ac_count=12,
                      dependencies=["milestone-1"])
    expected_acs = list(orig.ac_refs)

    result = split_oversized_milestones([orig], cap=10)

    a, b = result
    assert a.ac_refs == expected_acs[:8]
    assert b.ac_refs == expected_acs[8:]
    assert a.ac_refs + b.ac_refs == expected_acs


def test_split_titles_carry_part_n_suffix():
    """Phase 5.9 §L — split halves get `(Part N)` titles; original title not duplicated."""

    orig = _milestone("milestone-7", title="Invoice Creation", ac_count=19,
                      dependencies=["milestone-1"])
    result = split_oversized_milestones([orig], cap=10)

    assert [m.title for m in result] == [
        "Invoice Creation (Part 1)",
        "Invoice Creation (Part 2)",
        "Invoice Creation (Part 3)",
    ]


def test_split_b_depends_on_split_a_and_inherits_originals_deps():
    """Phase 5.9 §L — within-split chain: M-b deps M-a; M-a inherits original deps."""

    orig = _milestone("milestone-7", ac_count=12,
                      dependencies=["milestone-1", "milestone-3"])
    a, b = split_oversized_milestones([orig], cap=10)

    assert a.dependencies == ["milestone-1", "milestone-3"]
    # M-b inherits original deps + chains on M-a
    assert b.dependencies == ["milestone-1", "milestone-3", "milestone-7-a"]


def test_split_three_way_chain_bg_depends_on_a_then_b():
    """Phase 5.9 §L — N-way split chains b→a, c→b, d→c, etc."""

    orig = _milestone("milestone-7", ac_count=21,
                      dependencies=["milestone-1"])
    a, b, c = split_oversized_milestones([orig], cap=10)

    assert a.dependencies == ["milestone-1"]
    assert b.dependencies == ["milestone-1", "milestone-7-a"]
    assert c.dependencies == ["milestone-1", "milestone-7-b"]


def test_downstream_dependency_rewrites_to_completion_half():
    """Phase 5.9 §L — milestones depending on the split orig get rewritten to depend on the LAST half."""

    milestones = [
        _milestone("milestone-1", ac_count=0),
        _milestone("milestone-7", ac_count=12, dependencies=["milestone-1"]),
        _milestone("milestone-9", ac_count=5, dependencies=["milestone-7"]),
    ]
    result = split_oversized_milestones(milestones, cap=10)

    by_id = {m.id: m for m in result}
    # M-9's "milestone-7" dep got rewritten to "milestone-7-b" (the completion half).
    assert by_id["milestone-9"].dependencies == ["milestone-7-b"]
    assert "milestone-7" not in by_id


def test_downstream_with_three_way_split_rewrites_to_last_letter():
    """Phase 5.9 §L — N-way split: downstream dep rewrites to the LAST chunk (`-c` for 3-way)."""

    milestones = [
        _milestone("milestone-1", ac_count=0),
        _milestone("milestone-7", ac_count=21, dependencies=["milestone-1"]),
        _milestone("milestone-9", ac_count=5, dependencies=["milestone-7"]),
    ]
    result = split_oversized_milestones(milestones, cap=10)

    by_id = {m.id: m for m in result}
    assert by_id["milestone-9"].dependencies == ["milestone-7-c"]


# ---------------------------------------------------------------------------
# 26-half pre-mutation guard
# ---------------------------------------------------------------------------


def test_split_at_max_halves_succeeds_at_210_acs():
    """Phase 5.9 §L — 210 ACs splits into exactly 26 halves (`-a` through `-z`)."""

    orig = _milestone("milestone-7", ac_count=210, dependencies=["milestone-1"])
    result = split_oversized_milestones([orig], cap=10)

    assert len(result) == MAX_SPLIT_HALVES == 26
    assert result[0].id == "milestone-7-a"
    assert result[-1].id == "milestone-7-z"


def test_split_raises_when_milestone_exceeds_max_split_halves():
    """Phase 5.9 §L — 211+ ACs in a single milestone raises BEFORE any file mutation."""

    orig = _milestone("milestone-7", ac_count=211, dependencies=["milestone-1"])
    with pytest.raises(ValueError) as exc_info:
        split_oversized_milestones([orig], cap=10)

    msg = str(exc_info.value)
    assert "milestone-7" in msg
    assert "26" in msg or "MAX_SPLIT_HALVES" in msg


def test_split_pre_mutation_check_does_not_persist_files_on_error(tmp_path):
    """Phase 5.9 §L — over-limit failure leaves the run-dir untouched."""

    orig = _milestone("milestone-7", ac_count=300, dependencies=["milestone-1"])
    foundation = _milestone("milestone-1", ac_count=0)
    cwd = _seed_run_dir_with_master_plan(tmp_path, [foundation, orig])

    pre_files = sorted(p.name for p in (cwd / ".agent-team" / "milestones").iterdir())

    with pytest.raises(ValueError):
        split_oversized_milestones([foundation, orig], cap=10, cwd=cwd)

    post_files = sorted(p.name for p in (cwd / ".agent-team" / "milestones").iterdir())
    assert pre_files == post_files
    # Original REQUIREMENTS.md still in canonical place (no archive ran).
    assert (cwd / ".agent-team" / "milestones" / "milestone-7" / "REQUIREMENTS.md").is_file()
    assert not (cwd / ".agent-team" / "milestones" / "milestone-7" / "_phase_5_9_split_source").exists()


# ---------------------------------------------------------------------------
# REQUIREMENTS.md scoping + archive + scanner-skip
# ---------------------------------------------------------------------------


def test_split_writes_per_half_requirements_with_only_assigned_ac_checkboxes(tmp_path):
    """Phase 5.9 §L Blocker 2 — each half's REQUIREMENTS.md has only its half's AC checkboxes."""

    foundation = _milestone("milestone-1", ac_count=0)
    big = _milestone("milestone-7", title="Big Feature", ac_count=12,
                     dependencies=["milestone-1"])
    cwd = _seed_run_dir_with_master_plan(tmp_path, [foundation, big])

    split_oversized_milestones([foundation, big], cap=10, cwd=cwd)

    req_a = (cwd / ".agent-team" / "milestones" / "milestone-7-a" / "REQUIREMENTS.md").read_text(encoding="utf-8")
    req_b = (cwd / ".agent-team" / "milestones" / "milestone-7-b" / "REQUIREMENTS.md").read_text(encoding="utf-8")

    # Half A: 8 checkboxes (ACs 1..8).
    assert req_a.count("- [ ]") == 8
    for i in range(1, 9):
        assert f"AC-FEAT-{i:03d}" in req_a
    for i in range(9, 13):
        assert f"AC-FEAT-{i:03d}" not in req_a

    # Half B: 4 checkboxes (ACs 9..12).
    assert req_b.count("- [ ]") == 4
    for i in range(9, 13):
        assert f"AC-FEAT-{i:03d}" in req_b
    for i in range(1, 9):
        assert f"AC-FEAT-{i:03d}" not in req_b


def test_split_archives_original_requirements_md_atomically(tmp_path):
    """Phase 5.9 §L Blocker 2 — original moved to _phase_5_9_split_source; canonical path no longer exists."""

    foundation = _milestone("milestone-1", ac_count=0)
    big = _milestone("milestone-7", ac_count=12, dependencies=["milestone-1"])
    cwd = _seed_run_dir_with_master_plan(tmp_path, [foundation, big])

    canonical = cwd / ".agent-team" / "milestones" / "milestone-7" / "REQUIREMENTS.md"
    archive = cwd / ".agent-team" / "milestones" / "milestone-7" / "_phase_5_9_split_source" / "REQUIREMENTS.original.md"
    original_text = canonical.read_text(encoding="utf-8")

    split_oversized_milestones([foundation, big], cap=10, cwd=cwd)

    assert not canonical.is_file(), "Canonical REQUIREMENTS.md must be moved out of the orig-id slot"
    assert archive.is_file(), "Original must be preserved in the archive subdirectory"
    assert archive.read_text(encoding="utf-8") == original_text


def test_split_idempotency_raises_on_existing_archive(tmp_path):
    """Phase 5.9 §L — re-running split with archive already present raises (no silent overwrite)."""

    foundation = _milestone("milestone-1", ac_count=0)
    big = _milestone("milestone-7", ac_count=12, dependencies=["milestone-1"])
    cwd = _seed_run_dir_with_master_plan(tmp_path, [foundation, big])

    split_oversized_milestones([foundation, big], cap=10, cwd=cwd)

    # Re-create the canonical file as if a re-run produced a fresh original.
    canonical = cwd / ".agent-team" / "milestones" / "milestone-7" / "REQUIREMENTS.md"
    canonical.write_text("# replay\n", encoding="utf-8")

    with pytest.raises(FileExistsError):
        split_oversized_milestones([foundation, big], cap=10, cwd=cwd)


def test_split_rejects_already_suffixed_milestone_with_too_many_acs():
    """Phase 5.9 §L — refuse re-splitting a milestone whose ID is already a split-half.

    Nested IDs (e.g. ``milestone-7-a-a``) round-trip through neither the
    parser regex nor the generator's heading-num extraction (both accept
    a SINGLE optional ``-<letter>`` segment by design). An above-cap
    split-half is therefore surfaced as a structural defect rather than
    silently expanded.
    """

    foundation = _milestone("milestone-1", ac_count=0)
    # An over-cap split-half should not exist in normal flow; if it does,
    # raise loudly.
    bad_half = _milestone(
        "milestone-7-a", title="Already a Half", ac_count=12,
        dependencies=["milestone-1"],
    )

    with pytest.raises(ValueError) as exc_info:
        split_oversized_milestones([foundation, bad_half], cap=10)

    msg = str(exc_info.value)
    assert "milestone-7-a" in msg
    assert "already-suffixed" in msg or "split-half" in msg or "nested" in msg.lower()


def test_split_at_max_split_halves_all_letters_unique_and_flat():
    """Phase 5.9 §L — N-way split letter sequence is flat (no nested suffixes)."""

    orig = _milestone("milestone-7", ac_count=210, dependencies=["milestone-1"])
    result = split_oversized_milestones([orig], cap=10)

    suffixes = [m.id.removeprefix("milestone-7-") for m in result]
    # 26 single-letter suffixes, alphabetically ordered, no duplicates,
    # no multi-letter forms.
    assert len(suffixes) == 26
    assert len(set(suffixes)) == 26
    assert all(len(s) == 1 and s.isalpha() and s.islower() for s in suffixes)
    assert suffixes == sorted(suffixes)


def test_split_preflights_archives_no_canonical_moved_on_idempotency_failure(tmp_path):
    """Phase 5.9 §L — when ANY archive target exists, NO canonical REQUIREMENTS.md is moved.

    Multi-original split: m7 has no archive, m8 has archive already. The
    preflight must catch m8's existing archive BEFORE the loop renames
    m7's canonical file. Locks the no-half-mutation invariant.
    """

    foundation = _milestone("milestone-1", ac_count=0)
    m7 = _milestone("milestone-7", ac_count=12, dependencies=["milestone-1"])
    m8 = _milestone("milestone-8", ac_count=12, dependencies=["milestone-1"])
    cwd = _seed_run_dir_with_master_plan(tmp_path, [foundation, m7, m8])

    # Pre-create m8's archive (simulate a prior partial split or an operator
    # leftover) — preflight should refuse the new split.
    m8_archive_dir = (
        cwd / ".agent-team" / "milestones" / "milestone-8" / "_phase_5_9_split_source"
    )
    m8_archive_dir.mkdir(parents=True, exist_ok=True)
    (m8_archive_dir / "REQUIREMENTS.original.md").write_text(
        "# pre-existing archive\n", encoding="utf-8"
    )

    m7_canonical = cwd / ".agent-team" / "milestones" / "milestone-7" / "REQUIREMENTS.md"
    m8_canonical = cwd / ".agent-team" / "milestones" / "milestone-8" / "REQUIREMENTS.md"
    assert m7_canonical.is_file()
    assert m8_canonical.is_file()

    with pytest.raises(FileExistsError) as exc_info:
        split_oversized_milestones([foundation, m7, m8], cap=10, cwd=cwd)

    # Critical invariant: NEITHER canonical was moved.
    assert m7_canonical.is_file(), "m7's canonical REQUIREMENTS.md must NOT move when m8's archive blocks the split"
    assert m8_canonical.is_file(), "m8's canonical REQUIREMENTS.md must NOT move (its archive already existed pre-call)"
    # And no half-files were written for either milestone.
    assert not (cwd / ".agent-team" / "milestones" / "milestone-7-a" / "REQUIREMENTS.md").exists()
    assert not (cwd / ".agent-team" / "milestones" / "milestone-7-b" / "REQUIREMENTS.md").exists()
    assert not (cwd / ".agent-team" / "milestones" / "milestone-8-a" / "REQUIREMENTS.md").exists()
    assert not (cwd / ".agent-team" / "milestones" / "milestone-8-b" / "REQUIREMENTS.md").exists()
    # Error message names the offending archive so the operator can find it.
    assert "milestone-8" in str(exc_info.value)


def test_original_split_source_excluded_from_list_milestone_ids(tmp_path):
    """Phase 5.9 §L — orig-id directory drops out of _list_milestone_ids after archive."""

    foundation = _milestone("milestone-1", ac_count=0)
    big = _milestone("milestone-7", ac_count=12, dependencies=["milestone-1"])
    cwd = _seed_run_dir_with_master_plan(tmp_path, [foundation, big])

    split_oversized_milestones([foundation, big], cap=10, cwd=cwd)

    mm = MilestoneManager(project_root=cwd)
    ids = mm._list_milestone_ids()

    assert "milestone-1" in ids
    assert "milestone-7-a" in ids
    assert "milestone-7-b" in ids
    assert "milestone-7" not in ids, "Archived orig-id must NOT appear in active milestone discovery"


def test_aggregate_convergence_ignores_original_unsplit_requirements(tmp_path):
    """Phase 5.9 §L — convergence sums halves' checkboxes; orig source not double-counted."""

    foundation = _milestone("milestone-1", ac_count=0)
    big = _milestone("milestone-7", ac_count=12, dependencies=["milestone-1"])
    cwd = _seed_run_dir_with_master_plan(tmp_path, [foundation, big])

    split_oversized_milestones([foundation, big], cap=10, cwd=cwd)

    mm = MilestoneManager(project_root=cwd)
    report = aggregate_milestone_convergence(mm)

    # Halves sum to 12 (8 + 4); foundation has 0 reqs. Orig source's 12 are NOT counted.
    assert report.total_requirements == 12


def test_cross_milestone_wiring_ignores_original_unsplit_requirements(tmp_path):
    """Phase 5.9 §L — cross-milestone wiring doesn't iterate the archived original."""

    foundation = _milestone("milestone-1", ac_count=0)
    big = _milestone("milestone-7", ac_count=12, dependencies=["milestone-1"])
    cwd = _seed_run_dir_with_master_plan(tmp_path, [foundation, big])

    split_oversized_milestones([foundation, big], cap=10, cwd=cwd)

    mm = MilestoneManager(project_root=cwd)
    # _list_milestone_ids gates the wiring scan; if orig-id slipped in we'd
    # see "milestone-7" in the iteration. Use the public id-list as the
    # operational proxy (get_cross_milestone_wiring iterates the same list
    # at milestone_manager.py:1652 + :1726).
    ids = mm._list_milestone_ids()
    assert "milestone-7" not in ids


def test_stack_contract_glob_skips_archived_original(tmp_path):
    """Phase 5.9 §L — stack_contract.py:946's `*/REQUIREMENTS.md` glob skips the archived original."""

    from agent_team_v15.stack_contract import _collect_requirements_texts

    foundation = _milestone("milestone-1", ac_count=0)
    big = _milestone("milestone-7", ac_count=12, dependencies=["milestone-1"])
    cwd = _seed_run_dir_with_master_plan(tmp_path, [foundation, big])

    # Mark the original with a unique sentinel so we can detect leakage.
    canonical = cwd / ".agent-team" / "milestones" / "milestone-7" / "REQUIREMENTS.md"
    sentinel = "PHASE-5-9-ARCHIVE-SENTINEL-DO-NOT-LEAK"
    canonical.write_text(canonical.read_text(encoding="utf-8") + "\n" + sentinel, encoding="utf-8")

    split_oversized_milestones([foundation, big], cap=10, cwd=cwd)

    text = _collect_requirements_texts(cwd)
    assert sentinel not in text, "stack_contract glob must NOT pick up archived original"


def test_active_split_halves_counted_by_check_milestone_health(tmp_path):
    """Phase 5.9 §L — check_milestone_health(<orig-id>-a) returns total_requirements equal to half's AC count."""

    foundation = _milestone("milestone-1", ac_count=0)
    big = _milestone("milestone-7", ac_count=12, dependencies=["milestone-1"])
    cwd = _seed_run_dir_with_master_plan(tmp_path, [foundation, big])

    split_oversized_milestones([foundation, big], cap=10, cwd=cwd)

    mm = MilestoneManager(project_root=cwd)
    rep_a = mm.check_milestone_health("milestone-7-a")
    rep_b = mm.check_milestone_health("milestone-7-b")

    assert rep_a.total_requirements == 8
    assert rep_b.total_requirements == 4


# ---------------------------------------------------------------------------
# Validator gate kwarg
# ---------------------------------------------------------------------------


def test_validate_plan_errors_directly_on_above_cap_input():
    """Phase 5.9 §L — validate_plan(ac_cap=10) returns valid=False when any milestone exceeds cap."""

    milestones = [
        _milestone("milestone-1", ac_count=0),
        _milestone("milestone-7", ac_count=11, dependencies=["milestone-1"]),
    ]
    result = validate_plan(milestones, ac_cap=10)
    assert result.valid is False
    assert any("milestone-7" in err and "11" in err for err in result.errors)


def test_split_then_validate_passes_for_above_cap_input():
    """Phase 5.9 §L — pipeline test: split → validate → no errors."""

    milestones = [
        _milestone("milestone-1", ac_count=0),
        _milestone("milestone-7", ac_count=12, dependencies=["milestone-1"]),
    ]
    after_split = split_oversized_milestones(milestones, cap=10)
    result = validate_plan(after_split, ac_cap=10)

    assert result.valid is True
    assert result.errors == []


def test_validate_plan_ac_cap_zero_disables_gate():
    """Phase 5.9 §L — ac_cap=0 disables gate (legacy unbounded behaviour)."""

    milestones = [
        _milestone("milestone-1", ac_count=0),
        _milestone("milestone-7", ac_count=11, dependencies=["milestone-1"]),
    ]
    result = validate_plan(milestones, ac_cap=0)
    assert result.valid is True


def test_validate_plan_ac_cap_default_falls_back_to_module_constant():
    """Phase 5.9 §L — ac_cap=None reads MILESTONE_AC_CAP_DEFAULT (10)."""

    milestones = [
        _milestone("milestone-1", ac_count=0),
        _milestone("milestone-7", ac_count=11, dependencies=["milestone-1"]),
    ]
    result = validate_plan(milestones)  # no ac_cap kwarg
    assert result.valid is False, "Default should match the module constant (10)"


def test_validate_plan_under_3_acs_still_warns_post_phase_5_9():
    """Phase 5.9 §L — `< 3` advisory floor preserved as a WARNING (not an error)."""

    milestones = [
        _milestone("milestone-1", ac_count=0),
        _milestone("milestone-2", ac_count=2, dependencies=["milestone-1"]),
    ]
    result = validate_plan(milestones, ac_cap=10)

    assert result.valid is True
    assert any("milestone-2" in w and "2" in w for w in result.warnings)


def test_validate_plan_foundation_zero_acs_exempt_from_gate():
    """Phase 5.9 §L — 0-AC foundation milestones neither warn nor gate."""

    milestones = [_milestone("milestone-1", ac_count=0)]
    result = validate_plan(milestones, ac_cap=10)

    assert result.valid is True
    assert all("milestone-1" not in w for w in result.warnings)


def test_validate_plan_at_cap_passes():
    """Phase 5.9 §L — exactly cap (10) ACs is allowed; gate fires only at > cap."""

    milestones = [
        _milestone("milestone-1", ac_count=0),
        _milestone("milestone-7", ac_count=10, dependencies=["milestone-1"]),
    ]
    result = validate_plan(milestones, ac_cap=10)
    assert result.valid is True


# ---------------------------------------------------------------------------
# Constants + config + post-split persistence
# ---------------------------------------------------------------------------


def test_milestone_ac_cap_default_constant_is_10():
    """Phase 5.9 §L — locked: MILESTONE_AC_CAP_DEFAULT = 10."""

    assert MILESTONE_AC_CAP_DEFAULT == 10


def test_max_split_halves_is_26():
    """Phase 5.9 §L — locked: MAX_SPLIT_HALVES = 26 (single-letter alphabet)."""

    assert MAX_SPLIT_HALVES == 26


def test_config_validator_rejects_cap_1_and_2():
    """Phase 5.9 §L — config validator rejects 1 and 2 (below advisory min)."""

    from agent_team_v15.config import _validate_v18_phase59, V18Config

    cfg = V18Config()

    cfg.milestone_ac_cap = 1
    with pytest.raises(ValueError):
        _validate_v18_phase59(cfg)

    cfg.milestone_ac_cap = 2
    with pytest.raises(ValueError):
        _validate_v18_phase59(cfg)


def test_config_validator_rejects_negative_cap():
    """Phase 5.9 §L — config validator rejects negative caps."""

    from agent_team_v15.config import _validate_v18_phase59, V18Config

    cfg = V18Config()
    cfg.milestone_ac_cap = -5
    with pytest.raises(ValueError):
        _validate_v18_phase59(cfg)


def test_config_validator_accepts_cap_zero_and_above_3():
    """Phase 5.9 §L — config validator accepts 0 (disabled) and ≥ 3 (active)."""

    from agent_team_v15.config import _validate_v18_phase59, V18Config

    for cap in (0, 3, 5, 10, 13, 100):
        cfg = V18Config()
        cfg.milestone_ac_cap = cap
        _validate_v18_phase59(cfg)  # no raise


def test_split_persists_post_split_master_plan_json_and_md(tmp_path):
    """Phase 5.9 §L — post-split MASTER_PLAN.json reflects split-IDs; MD round-trips."""

    foundation = _milestone("milestone-1", ac_count=0)
    big = _milestone("milestone-7", ac_count=12, dependencies=["milestone-1"])
    cwd = _seed_run_dir_with_master_plan(tmp_path, [foundation, big])

    after = split_oversized_milestones([foundation, big], cap=10, cwd=cwd)

    # In-memory: 3 milestones (1 + 2 halves).
    assert [m.id for m in after] == ["milestone-1", "milestone-7-a", "milestone-7-b"]

    # Persist + round-trip via MD.
    generate_master_plan_json(after, cwd / ".agent-team" / "MASTER_PLAN.json")
    generate_master_plan_md(cwd)
    md = (cwd / ".agent-team" / "MASTER_PLAN.md").read_text(encoding="utf-8")
    plan = parse_master_plan(md)

    assert [m.id for m in plan.milestones] == [
        "milestone-1", "milestone-7-a", "milestone-7-b",
    ]


def test_split_persistence_drops_unsplit_original_from_canonical_json(tmp_path):
    """Phase 5.9 split coherence — stale original IDs are not executable after split."""

    from agent_team_v15 import cli as cli_mod

    original = _milestone("milestone-1", ac_count=12)
    downstream = _milestone("milestone-2", dependencies=["milestone-1"], ac_count=3)
    cwd = _seed_run_dir_with_master_plan(tmp_path, [original, downstream])

    after = split_oversized_milestones([original, downstream], cap=10, cwd=cwd)
    generate_master_plan_json(after, cwd / ".agent-team" / "MASTER_PLAN.json")
    generate_master_plan_md(cwd)

    json_path = cwd / ".agent-team" / "MASTER_PLAN.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["milestones"].append(
        {
            "id": "milestone-1",
            "title": "Platform Foundation",
            "status": "PENDING",
            "dependencies": [],
            "description": "stale unsplit original",
            "template": "full_stack",
            "parallel_group": "",
            "merge_surfaces": [],
            "feature_refs": [],
            "ac_refs": original.ac_refs,
            "stack_target": "",
            "complexity_estimate": {},
        }
    )
    json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    current_plan_content = (cwd / ".agent-team" / "MASTER_PLAN.md").read_text(encoding="utf-8")
    cli_mod._persist_master_plan_state(
        cwd / ".agent-team" / "MASTER_PLAN.md",
        current_plan_content,
        cwd,
    )

    reloaded = load_master_plan_json(cwd)
    ids = [m.id for m in reloaded.milestones]
    ready_ids = [m.id for m in reloaded.get_ready_milestones()]

    assert ids == ["milestone-1-a", "milestone-1-b", "milestone-2"]
    assert "milestone-1" not in ids
    assert ready_ids == ["milestone-1-a"]


def test_stale_original_milestone_directory_does_not_reintroduce_executable_id(tmp_path):
    """Phase 5.9 split coherence — old milestone dirs are artifacts, not plan entries."""

    original = _milestone("milestone-1", ac_count=12)
    downstream = _milestone("milestone-2", dependencies=["milestone-1"], ac_count=3)
    cwd = _seed_run_dir_with_master_plan(tmp_path, [original, downstream])
    after = split_oversized_milestones([original, downstream], cap=10, cwd=cwd)
    generate_master_plan_json(after, cwd / ".agent-team" / "MASTER_PLAN.json")
    generate_master_plan_md(cwd)

    stale_dir = cwd / ".agent-team" / "milestones" / "milestone-1"
    stale_dir.mkdir(parents=True, exist_ok=True)
    (stale_dir / "REQUIREMENTS.md").write_text("# stale original\n", encoding="utf-8")

    reloaded = load_master_plan_json(cwd)
    ids = [m.id for m in reloaded.milestones]
    ready_ids = [m.id for m in reloaded.get_ready_milestones()]

    assert ids == ["milestone-1-a", "milestone-1-b", "milestone-2"]
    assert "milestone-1" not in ids
    assert ready_ids == ["milestone-1-a"]


def test_split_halves_persist_explicit_split_metadata(tmp_path):
    """Phase 5.9 split coherence — Wave C can distinguish pre-final and final halves."""

    original = _milestone("milestone-1", ac_count=12)
    cwd = _seed_run_dir_with_master_plan(tmp_path, [original])

    after = split_oversized_milestones([original], cap=10, cwd=cwd)
    generate_master_plan_json(after, cwd / ".agent-team" / "MASTER_PLAN.json")
    generate_master_plan_md(cwd)
    reloaded = load_master_plan_json(cwd)

    first = reloaded.get_milestone("milestone-1-a")
    final = reloaded.get_milestone("milestone-1-b")

    assert first is not None and final is not None
    assert first.split_parent_id == "milestone-1"
    assert first.split_part_index == 1
    assert first.split_part_total == 2
    assert first.is_final_split_part is False
    assert final.split_parent_id == "milestone-1"
    assert final.split_part_index == 2
    assert final.split_part_total == 2
    assert final.is_final_split_part is True


def test_required_split_path_precondition_passes_after_auto_split(tmp_path):
    """Stage 2B guard — post-split milestone-1 halves satisfy the preflight."""

    from agent_team_v15 import cli as cli_mod

    original = _milestone("milestone-1", ac_count=12)
    cwd = _seed_run_dir_with_master_plan(tmp_path, [original])
    after = split_oversized_milestones([original], cap=10, cwd=cwd)
    generate_master_plan_json(after, cwd / ".agent-team" / "MASTER_PLAN.json")
    generate_master_plan_md(cwd)

    cli_mod._validate_required_split_path(
        cwd,
        MasterPlan(milestones=after),
        required_parent="milestone-1",
        required_parts_min=2,
    )

    assert not (
        cwd / ".agent-team" / "SPLIT_VALIDATION_PRECONDITION_FAILED.json"
    ).exists()


def test_required_split_path_precondition_writes_artifact_and_fails_without_halves(tmp_path):
    """Stage 2B guard — unsplit plans abort before paid wave execution."""

    from agent_team_v15 import cli as cli_mod

    original = _milestone("milestone-1", ac_count=8)
    downstream = _milestone("milestone-2", dependencies=["milestone-1"], ac_count=3)
    cwd = _seed_run_dir_with_master_plan(tmp_path, [original, downstream])

    with pytest.raises(
        cli_mod.SplitPathPreconditionError,
        match="Required split path absent",
    ):
        cli_mod._validate_required_split_path(
            cwd,
            MasterPlan(milestones=[original, downstream]),
            required_parent="milestone-1",
            required_parts_min=2,
        )

    artifact = cwd / ".agent-team" / "SPLIT_VALIDATION_PRECONDITION_FAILED.json"
    payload = json.loads(artifact.read_text(encoding="utf-8"))

    assert payload["failure_reason"] == "required_split_path_absent"
    assert payload["required_parent"] == "milestone-1"
    assert payload["required_parts_min"] == 2
    assert payload["observed_split_ids"] == []
    assert payload["milestone_ids"] == ["milestone-1", "milestone-2"]


def test_required_split_path_precondition_runs_before_phase_15_research():
    """Stage 2B guard must run before paid Phase 1.5 / Wave execution starts."""

    import inspect
    from agent_team_v15 import cli as cli_mod

    source = inspect.getsource(cli_mod._run_prd_milestones)

    assert source.index("_validate_required_split_path(") < source.index(
        "Phase 1.5: TECH STACK RESEARCH"
    )
