# GitHub Issues to List

<!-- block-metadata:start -->
[![Block version: unversioned](https://img.shields.io/badge/block-unversioned-lightgrey)](model.json)
[![BloxSmith compatibility: 1.0.9](https://img.shields.io/badge/BloxSmith-1.0.9-brightgreen)](compatibility.json)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

Verified BloxSmith versions: **1.0.9** (bundled-block tests; see [test evidence](compatibility.json)).
<!-- block-metadata:end -->


`github_issues_to_list` transforms a raw GitHub Issues JSON response into a compact list that can be consumed by `iterator` or downstream AI blocks.

## Purpose

Keep `github_issues` focused on GitHub API calls and use this block for local shaping/filtering. The output removes noisy GitHub REST fields while keeping the fields normally useful for issue analysis and development triage.

## Ports

Inputs:

- `issues` (`application/json`, `message/*`): raw response from `github_issues`, a direct issue array, one issue object, or a wrapper list.

Outputs:

- `liste` (`application/json`, `message/*`): JSON array shaped as `[ {"item": { ...compact issue... } } ]`.
- `summary` (`text/plain`, `message/*`): short runtime summary.

## Configuration

- `include_body`: include issue body text in each compact item.
- `max_body_chars`: maximum body length before truncation. `0` keeps an empty body when body text exists.
- `include_closed`: keep closed issues from the input payload. Disable it to skip closed issues locally.
- `empty_body_placeholder`: optional text used when a body is empty and `include_body` is enabled.
- `required_labels`: list of exact labels or `*` wildcard patterns that must all match for an issue to be kept. Comparison is case-insensitive. Examples: `["todo"]`, `["status:*"]`.
- `excluded_labels`: list of exact labels or `*` wildcard patterns that exclude an issue when at least one matches. Comparison is case-insensitive, and exclusion wins over required-label matches. Examples: `["status:done"]`, `["closed:*"]`.

## Compact item fields

Each output `item` contains:

- `number`, `title`, `state`, `state_reason`
- `labels`, `milestone`, `author`, `assignees`
- `comments`, `url`
- `comments_data` when upstream `github_issues.include_comments` provided comment contents
- `created_at`, `updated_at`, `closed_at`
- `is_pull_request`
- `body` and `body_truncated` when `include_body` is enabled

## Runtime behavior

- FB1: accepts a raw GitHub Issues block result, a direct issue array, or a list-wrapper payload.
- FB2: compacts each issue to fields useful for workflow analysis and development follow-up.
- FB3: emits an Iterator-compatible JSON list shaped as `[{"item": compact_issue}, ...]`.
- FB4: optionally keeps/skips closed issues, includes/truncates body text, and exposes truncation metadata.
- FB5: renders an ergonomic block-owned inspector, wide modal, and node card.
- FB7: filters issues locally with exact or `*` wildcard `required_labels` and `excluded_labels` before emitting the list.
- FB8: preserves compact `comments_data` when the upstream GitHub Issues block was configured with `include_comments`.
- FB6: runs through the generic runtime path in both One Shot Simulation (`centralized`) and Active Runtime (`zeromq_active`).

## UI Behavior

The inspector and wide modal expose filtering, body handling, preview, ports, and runtime state. Editable filters stay local until the user clicks **Apply**. The modal declares `data-block-runtime-refresh="autonomous"`; `assets/js/block_modal.js` owns the modal hook so block-owned tabs and draft filters stay stable while runtime polling is active.

## Label filtering example

For a triage workflow, configure:

```json
{
  "required_labels": ["todo"],
  "excluded_labels": ["status:done", "closed:*"]
}
```

Only issues carrying `todo` are emitted, unless they also carry `status:done` or a label matching `closed:*`. Labels from GitHub may be strings or objects like `{ "name": "todo" }`. Exact filters remain exact; wildcard matching is enabled only with `*`. The `summary` output reports received, kept, missing-required-label exclusions, and excluded-label exclusions.

## Example

Input from `github_issues`:

```json
{
  "ok": true,
  "action": "list_issues",
  "data": [
    {
      "number": 1,
      "title": "Add GitHub block",
      "state": "open",
      "labels": [{"name": "enhancement"}],
      "user": {"login": "HackInvent"},
      "body": "Add a GitHub block to read issues.",
      "comments_data": [
        {"id": 101, "body": "First comment", "user": {"login": "reviewer"}}
      ]
    }
  ]
}
```

Output:

```json
[
  {
    "item": {
      "number": 1,
      "title": "Add GitHub block",
      "state": "open",
      "labels": ["enhancement"],
      "author": "HackInvent",
      "comments_data": [
        {"id": 101, "body": "First comment", "author": "reviewer"}
      ],
      "body": "Add a GitHub block to read issues.",
      "body_truncated": false
    }
  }
]
```

## Tests

- `tests/F5.25_github_issues_to_list_block.py`: functional compaction, label filters, UI contract, centralized runtime, zeromq_active runtime, and Iterator compatibility tests.

## Compatibility policy

[compatibility.json](compatibility.json) records HackInvent's verified BloxSmith versions and test evidence. Only the versions listed above have been verified, using the block-owned suites in a **bundled-block test installation**. This is not a certification of managed-package installation, every browser/OS, or live provider availability. Other framework versions are unverified, not necessarily incompatible.

The block-version badge follows `model.json`, not a published Git tag. `unversioned` means that no block release version is declared; no number is inferred from the framework version. The framework still uses `model.json` for its runtime/install contract; the tester-owned JSON does not replace it. Official integration tests run in the private `bloxmith-blocs` workspace. Test helpers and the proprietary framework are not bundled in this public block repository.
