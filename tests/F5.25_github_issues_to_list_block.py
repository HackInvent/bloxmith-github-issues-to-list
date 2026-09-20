#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Role: Verifies GitHub Issues to List block behavior.
# File Name: F5.25_github_issues_to_list_block.py
# Author: Alexandre EL
# Email: alex@hackinvent.com
# Created Date: 2026-05-25
# -----------------------------------------------------------------------------

"""F5.25 - GitHub Issues to List block.

The test verifies functional compaction, Iterator-compatible list output, UI
rendering, and execution in both centralized and zeromq_active runtime modes.
"""

# Test cases:
# - FB1/FB2/FB3/FB4 - Compact raw GitHub Issues response data into stable Iterator-compatible wrappers.
# - FB3 - Verify Iterator can parse the emitted JSON list as item payloads.
# - FB4 - Verify closed-issue filtering and body truncation options.
# - FB7 - Verify required/excluded label filtering, wildcard matching, case normalization, and priority rules.
# - FB8 - Verify comments_data from GitHub Issues include_comments is compacted and preserved.
# - FB5 - Render modal, inspector, node-card, and block-owned assets with one-field-per-line ergonomics.
# - FB6 - Run text payload -> GitHub Issues to List -> display in centralized and zeromq_active modes.

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
import json
import sys


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blocs.github_issues_to_list.block import GitHubIssuesToListBlock
from blocs.iterator.block import IteratorBlock
from bloxsmith_app.block_runtime import BlockRuntimeContext
from bloxsmith_app.block_ui import render_block_inspector_panel, render_block_modal, render_block_node_card
from ui_smoke_common import (
    create_run_api,
    data_edge,
    display_node,
    expect,
    graph_payload,
    isolated_server,
    text_node,
    wait_for_run_terminal,
)
from urllib.parse import quote
from block_test_packages import install_test_package, release_key, surface_payload


LONG_BODY = "0123456789" * 20


def sample_github_response() -> dict[str, Any]:
    """Return a GitHub Issues-like raw response with open and closed issues."""

    return {
        "ok": True,
        "action": "list_issues",
        "repo": "HackInvent/bloxsmith",
        "count": 2,
        "data": [
            {
                "url": "https://api.github.com/repos/HackInvent/bloxsmith/issues/1",
                "html_url": "https://github.com/HackInvent/bloxsmith/issues/1",
                "number": 1,
                "title": "Add GitHub issues block",
                "user": {"login": "HackInvent", "id": 395993},
                "labels": [{"name": "enhancement", "color": "a2eeef"}],
                "state": "open",
                "assignees": [{"login": "maintainer"}],
                "milestone": {"title": "1.0.7", "open_issues": 1},
                "comments": 3,
                "created_at": "2026-05-25T21:03:35Z",
                "updated_at": "2026-05-25T21:04:47Z",
                "closed_at": None,
                "state_reason": None,
                "body": LONG_BODY,
                "comments_data": [
                    {
                        "id": 201,
                        "body": "Premier commentaire",
                        "user": {"login": "reviewer"},
                        "created_at": "2026-05-25T22:00:00Z",
                        "updated_at": "2026-05-25T22:01:00Z",
                        "html_url": "https://github.com/HackInvent/bloxsmith/issues/1#issuecomment-201",
                        "extra": "ignored",
                    }
                ],
                "reactions": {"total_count": 0},
            },
            {
                "html_url": "https://github.com/HackInvent/bloxsmith/issues/2",
                "number": 2,
                "title": "Closed issue",
                "user": {"login": "other"},
                "labels": ["bug"],
                "state": "closed",
                "comments": 0,
                "created_at": "2026-05-24T10:00:00Z",
                "updated_at": "2026-05-24T11:00:00Z",
                "closed_at": "2026-05-24T12:00:00Z",
                "state_reason": "completed",
                "body": "closed body",
            },
        ],
        "http": {"status": 200, "rate_limit_remaining": "4998"},
    }


def github_issues_to_list_node(*, include_closed: bool = True, max_body_chars: int = 6000) -> dict[str, Any]:
    """Build a graph node payload for the GitHub Issues to List block."""

    return {
        "id": "github-issues-to-list-1",
        "kind": "github_issues_to_list",
        "title": "Issues compactes",
        "position": {"x": 360, "y": 120},
        "inputs": [
            {
                "id": 1,
                "name": "issues",
                "title": "Issues",
                "accepts": ["application/json", "message/*"],
                "multiplicity": "many",
                "required": False,
            }
        ],
        "outputs": [
            {"id": 1, "name": "liste", "title": "Liste", "emits": ["application/json", "message/*"], "multiplicity": "many"},
            {"id": 2, "name": "summary", "title": "Summary", "emits": ["text/plain", "message/*"], "multiplicity": "many"},
        ],
        "config": {
            "include_body": True,
            "include_closed": include_closed,
            "max_body_chars": max_body_chars,
            "empty_body_placeholder": "",
            "required_labels": [],
            "excluded_labels": [],
        },
    }


def runtime_graph(runtime_mode: str) -> dict[str, Any]:
    """Build text payload -> GitHub Issues to List -> display graph for runtime tests."""

    return graph_payload(
        f"F5 GitHub Issues to List {runtime_mode}",
        [
            text_node("text-1", "Issues brutes", json.dumps(sample_github_response(), ensure_ascii=False), 80, 120),
            github_issues_to_list_node(include_closed=False, max_body_chars=32),
            display_node("display-1", "Affichage", 720, 120),
        ],
        [
            data_edge("edge-text-transform", "text-1", 1, "github-issues-to-list-1", 1),
            data_edge("edge-transform-display", "github-issues-to-list-1", 1, "display-1", 1),
        ],
    )


def unit_context(*, config: dict[str, Any], input_payload: Any) -> BlockRuntimeContext:
    """Build a direct runtime context for unit-level block tests."""

    text_payload = json.dumps(input_payload, ensure_ascii=False) if not isinstance(input_payload, str) else input_payload
    return BlockRuntimeContext(
        run_id="unit-run",
        node_id="github-issues-to-list-unit",
        kind="github_issues_to_list",
        title="GitHub Issues to List unit",
        config=config,
        inputs={"issues": text_payload},
        input_content_types={"issues": "application/json"},
        input_message=text_payload,
        input_ports=(SimpleNamespace(id=1, name="issues"),),
        output_ports=(
            SimpleNamespace(id=1, name="liste", emits=("application/json", "message/*")),
            SimpleNamespace(id=2, name="summary", emits=("text/plain", "message/*")),
        ),
        root_dir=ROOT,
        run_dir=ROOT,
    )


def parse_list_output(result) -> list[dict[str, Any]]:
    """Decode the primary JSON output emitted by the block."""

    raw_output = result.outputs[0].value
    parsed = json.loads(raw_output)
    expect(isinstance(parsed, list), "La sortie liste doit etre un tableau JSON.")
    return parsed


def test_compaction_and_iterator_compatibility() -> None:
    """TC1 - Verify issue compaction and Iterator-compatible wrapper output."""

    block = GitHubIssuesToListBlock()
    result = block.execute_runtime(
        unit_context(
            config={"include_body": True, "include_closed": True, "max_body_chars": 25},
            input_payload=sample_github_response(),
        )
    )
    expect(result.status == "success", "The transformation must succeed on a raw GitHub Issues response.")
    wrappers = parse_list_output(result)
    expect(len(wrappers) == 2, "Both issues must be kept by default.")
    first = wrappers[0].get("item") or {}
    expect(first.get("number") == 1, "Le numero issue doit etre conserve.")
    expect(first.get("title") == "Add GitHub issues block", "The issue title must be kept.")
    expect(first.get("labels") == ["enhancement"], "Labels must be compacted to names.")
    expect(first.get("milestone") == "1.0.7", "The milestone must be compacted to its title.")
    expect(first.get("author") == "HackInvent", "The author must be compacted to a login.")
    expect(first.get("assignees") == ["maintainer"], "Assignees must be compacted to logins.")
    expect(first.get("comments_data", [])[0].get("author") == "reviewer", "Enriched comments must be compacted.")
    expect(first.get("comments_data", [])[0].get("body") == "Premier commentaire", "Comment content must be preserved.")
    expect("extra" not in first.get("comments_data", [])[0], "Noisy comment fields must not be copied.")
    expect(first.get("body_truncated") is True, "The body must report the truncation.")
    expect(len(first.get("body") or "") == 25, "Le body doit etre tronque au seuil configure.")
    expect("reactions" not in first and "repository_url" not in first, "Les champs GitHub bruyants ne doivent pas etre copies.")

    iterator_items = IteratorBlock().parse_items(result.outputs[0].value)
    expect(isinstance(iterator_items[0], dict) and "item" in iterator_items[0], "Iterator doit lire la liste wrapper produite.")


def test_closed_filter_and_payload_shapes() -> None:
    """TC2 - Verify closed issue filtering and alternate supported input shapes."""

    block = GitHubIssuesToListBlock()
    filtered = block.execute_runtime(
        unit_context(
            config={"include_body": False, "include_closed": False},
            input_payload=sample_github_response(),
        )
    )
    wrappers = parse_list_output(filtered)
    expect(len(wrappers) == 1, "Les issues fermees doivent etre ignorees quand include_closed=false.")
    first = wrappers[0].get("item") or {}
    expect("body" not in first, "Le body ne doit pas etre present quand include_body=false.")
    expect("2 issue(s) recue(s)" in filtered.outputs[1].value, "Le summary doit indiquer le nombre recu.")
    expect("1 issue(s) conservee(s)" in filtered.outputs[1].value, "Le summary doit indiquer le nombre conserve.")
    expect("1 fermee(s) ignoree(s)" in filtered.outputs[1].value, "Le summary doit indiquer les issues fermees ignorees.")

    direct_list = block.execute_runtime(
        unit_context(
            config={"include_body": True, "include_closed": True, "empty_body_placeholder": "No body"},
            input_payload=sample_github_response()["data"],
        )
    )
    direct_wrappers = parse_list_output(direct_list)
    expect(len(direct_wrappers) == 2, "Un tableau direct d'issues doit etre accepte.")

    invalid = block.execute_runtime(unit_context(config={}, input_payload="not json"))
    expect(invalid.status == "failed", "A non-JSON input must fail cleanly.")
    expect("not valid JSON" in invalid.error, "The error must explain the invalid JSON.")


def sample_label_filter_response() -> list[dict[str, Any]]:
    """Return mixed string/object labels for label-filter test cases."""

    return [
        {"number": 1, "title": "Todo UI", "state": "open", "labels": [{"name": "Todo"}, {"name": "component:ui"}]},
        {"number": 2, "title": "Todo done", "state": "open", "labels": ["todo", "status:done"]},
        {"number": 3, "title": "No todo", "state": "open", "labels": [{"name": "bug"}]},
        {"number": 4, "title": "Done wins", "state": "open", "labels": ["TODO", {"name": "status:done"}]},
    ]


def issue_numbers(result) -> list[int]:
    """Return compact issue numbers emitted by a runtime result."""

    return [int((wrapper.get("item") or {}).get("number") or 0) for wrapper in parse_list_output(result)]


def sample_wildcard_label_response() -> list[dict[str, Any]]:
    """Return labels that exercise exact and `*` wildcard filter matching."""

    return [
        {"number": 10, "title": "Closed duplicate", "state": "open", "labels": ["closed:duplicate", {"name": "todo"}]},
        {"number": 11, "title": "Ready area", "state": "open", "labels": [{"name": "Status:Ready-For-Dev"}, "area:blocs"]},
        {"number": 12, "title": "No status", "state": "open", "labels": ["todo", "area:mcp"]},
        {"number": 13, "title": "Closed status", "state": "open", "labels": ["status:done", {"name": "closed:wontfix"}]},
    ]


def test_label_filters() -> None:
    """TC3 - Verify required/excluded label filters and priority rules."""

    block = GitHubIssuesToListBlock()
    payload = sample_label_filter_response()

    unfiltered = block.execute_runtime(unit_context(config={}, input_payload=payload))
    expect(issue_numbers(unfiltered) == [1, 2, 3, 4], "With no filter, every issue must be kept.")
    expect("4 issue(s) recue(s)" in unfiltered.outputs[1].value, "The summary must count the received issues.")
    expect("4 issue(s) conservee(s)" in unfiltered.outputs[1].value, "The summary must count the issues kept with no filter.")

    required = block.execute_runtime(unit_context(config={"required_labels": ["todo"]}, input_payload=payload))
    expect(issue_numbers(required) == [1, 2, 4], "required_labels doit garder les issues avec le label requis, sans tenir compte de la casse.")
    expect("1 excluded for a missing required label" in required.outputs[1].value, "The summary must count the missing required labels.")

    excluded = block.execute_runtime(unit_context(config={"excluded_labels": ["status:done"]}, input_payload=payload))
    expect(issue_numbers(excluded) == [1, 3], "excluded_labels must drop the issues carrying an excluded label.")
    expect("2 excluded by an excluded label" in excluded.outputs[1].value, "The summary must count the excluded labels.")

    combined = block.execute_runtime(
        unit_context(config={"required_labels": ["todo"], "excluded_labels": ["status:done"]}, input_payload=payload)
    )
    expect(issue_numbers(combined) == [1], "excluded_labels must win over required_labels when both match.")
    expect("1 excluded for a missing required label" in combined.outputs[1].value, "The required filter must count the issues without todo.")
    expect("2 excluded by an excluded label" in combined.outputs[1].value, "The exclusion filter must count the issues it drops first.")

    text_config = GitHubIssuesToListBlock().normalize_config({"required_labels": "todo, component:ui", "excluded_labels": "status:done"})
    expect(text_config["required_labels"] == ["todo", "component:ui"], "Comma separated text filters must be normalized.")
    expect(text_config["excluded_labels"] == ["status:done"], "Excluded text filters must be normalized.")


def test_wildcard_label_filters() -> None:
    """TC4 - Verify `*` wildcard label filters without changing exact matching semantics."""

    block = GitHubIssuesToListBlock()
    payload = sample_wildcard_label_response()

    excluded_closed = block.execute_runtime(unit_context(config={"excluded_labels": ["closed:*"]}, input_payload=payload))
    expect(issue_numbers(excluded_closed) == [11, 12], "excluded_labels must accept a wildcard such as closed:*.")
    expect("2 excluded by an excluded label" in excluded_closed.outputs[1].value, "The summary must count the wildcard exclusions.")

    required_status = block.execute_runtime(unit_context(config={"required_labels": ["status:*"]}, input_payload=payload))
    expect(issue_numbers(required_status) == [11, 13], "required_labels must accept a wildcard such as status:*.")
    expect("2 excluded for a missing required label" in required_status.outputs[1].value, "The summary must count the missing required wildcards.")

    required_and_excluded = block.execute_runtime(
        unit_context(config={"required_labels": ["status:*"], "excluded_labels": ["closed:*"]}, input_payload=payload)
    )
    expect(issue_numbers(required_and_excluded) == [11], "A wildcard excluded_labels must stay ahead of a wildcard required_labels.")
    expect("1 excluded for a missing required label" in required_and_excluded.outputs[1].value, "The required wildcard must count the kept issues without status:*.")
    expect("2 excluded by an excluded label" in required_and_excluded.outputs[1].value, "The wildcard exclusion must be applied before the required one.")

    exact_and_wildcard = block.execute_runtime(
        unit_context(config={"required_labels": ["status:*", "area:blocs"]}, input_payload=payload)
    )
    expect(issue_numbers(exact_and_wildcard) == [11], "Every exact and wildcard required filter must match.")

    literal_question_mark = block.execute_runtime(unit_context(config={"required_labels": ["status:?"]}, input_payload=payload))
    expect(issue_numbers(literal_question_mark) == [], "Without *, filters stay exact labels and ? is not a wildcard.")


def test_ui_contract() -> None:
    """TC3 - Render block-owned modal, inspector, node-card, and assets."""

    node = github_issues_to_list_node()
    rendered = render_block_modal("github_issues_to_list", {"node": node, "runtime": {}})
    html = str(rendered.get("html") or "")
    assets = rendered.get("assets") or []
    css = (ROOT / "blocs/github_issues_to_list/assets/css/block_modal.css").read_text(encoding="utf-8")
    js = (ROOT / "blocs/github_issues_to_list/assets/js/block_modal.js").read_text(encoding="utf-8")
    expect('data-node-kind="github_issues_to_list"' in html, "Le modal doit venir du bloc.")
    expect("cw-github-issues-to-list-modal" in html, "Le modal doit utiliser le layout large du bloc.")
    expect('data-block-runtime-refresh="autonomous"' in html, "Le modal doit gerer son refresh runtime.")
    expect('data-github-issues-to-list-tab-id="transform"' in html, "The modal must expose the Transformation tab.")
    expect('data-github-issues-to-list-tab-id="preview"' in html, "The modal must expose the Preview tab.")
    expect('data-github-issues-to-list-tab-id="status"' in html, "The modal must expose the Ports & etat tab.")
    expect('{&quot;item&quot;:' in html or '{"item":' in html, "Le modal doit montrer le format wrapper item.")
    expect('data-block-config-field="required_labels"' in html, "Le modal doit exposer required_labels.")
    expect('data-block-config-field="excluded_labels"' in html, "Le modal doit exposer excluded_labels.")
    expect("width: min(1120px" in css, "Le CSS doit agrandir le modal.")
    expect("export function mount" in js, "Le JS doit monter le modal via le registre block UI.")

    inspector = render_block_inspector_panel("github_issues_to_list", {"node": node})
    inspector_html = str(inspector.get("html") or "")
    expect("cw-github-issues-to-list-inspector" in inspector_html, "The inspector must come from the block.")
    expect("GitHub Issues to List" in inspector_html and "Transform" in inspector_html, "The inspector metadata must be filled in.")
    expect('class="field-grid"' not in inspector_html, "The inspector must show one attribute per line.")
    expect('data-block-config-field="include_body"' in inspector_html, "include_body must be editable.")
    expect('data-block-config-field="max_body_chars"' in inspector_html, "max_body_chars must be editable.")
    expect('data-block-config-field="include_closed"' in inspector_html, "include_closed must be editable.")
    expect('data-block-config-field="required_labels"' in inspector_html, "required_labels must be editable.")
    expect('data-block-config-field="excluded_labels"' in inspector_html, "excluded_labels must be editable.")

    card = render_block_node_card("github_issues_to_list", {"node": node})
    card_html = str(card.get("html") or "")
    expect("Issues -&gt; liste item" in card_html, "La node-card doit resumer la transformation.")


def run_runtime_case(runtime_mode: str) -> None:
    """TC4 - Run the block through the public run API in one runtime mode."""

    with isolated_server() as server:
        # Surfaces are release assets: a bundled kind serves none of them.
        model = install_test_package(server, "github_issues_to_list")
        key = quote(release_key(model), safe="")
        served = lambda payload, suffix: next(
            asset["path"] for asset in payload["assets"] if asset["path"].endswith(suffix))
        created = create_run_api(server, runtime_graph(runtime_mode), runtime_mode=runtime_mode)
        run = wait_for_run_terminal(server, str(created.get("run_id") or ""), timeout_sec=20)

    logs = "\n".join(run.get("logs", []))
    raw_output = run.get("output_values", {}).get("github-issues-to-list-1:1", {}).get("value") or "[]"
    wrappers = json.loads(raw_output)
    expect(run.get("status") == "success", f"The {runtime_mode} run must succeed.")
    expect(len(wrappers) == 1, "The run must filter out the closed issue and publish one issue.")
    expect(wrappers[0]["item"]["number"] == 1, "The runtime output must contain the compacted issue.")
    expect(wrappers[0]["item"]["body_truncated"] is True, "The runtime output must apply the truncation.")
    expect("fallback centralized" not in logs, "The active run must not fall back to the centralized engine.")
    if runtime_mode == "zeromq_active":
        expect(
            run.get("results", {}).get("github-issues-to-list-1", {}).get("transport") == "zeromq_active",
            "github_issues_to_list must run through zeromq_active.",
        )


def main() -> None:
    test_ui_contract()
    test_compaction_and_iterator_compatibility()
    test_closed_filter_and_payload_shapes()
    test_label_filters()
    test_wildcard_label_filters()
    run_runtime_case("centralized")
    run_runtime_case("zeromq_active")
    print("[ok] F5.25_github_issues_to_list_block")


if __name__ == "__main__":
    main()
