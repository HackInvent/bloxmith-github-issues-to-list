# -----------------------------------------------------------------------------
# Role: Transforms raw GitHub Issues responses into Iterator-compatible lists.
# File Name: block.py
# Author: Alexandre EL
# Email: alex@hackinvent.com
# Created Date: 2026-05-25
# -----------------------------------------------------------------------------

from __future__ import annotations

from fnmatch import fnmatchcase
from html import escape
from typing import Any
import json

from bloxsmith_app.block_api import (
    APPLICATION_JSON,
    BlockDefinition,
    BlockRuntimeContext,
    BlockRuntimeOutput,
    BlockRuntimeResult,
    render_inspector_template,
    render_node_card_template,
    render_ports_rows,
    TEXT_PLAIN,
)


DEFAULT_MAX_BODY_CHARS = 6000
MAX_BODY_CHARS = 200000
LIST_KEYS = ("data", "items", "liste", "list", "values")


# Functional behavior:
# FB1 - Accept a raw GitHub Issues block result, a direct issue array, or a list-wrapper payload as input.
# FB2 - Compact each issue to fields useful for workflow analysis and development follow-up.
# FB3 - Emit an Iterator-compatible JSON list shaped as [{"item": compact_issue}, ...].
# FB4 - Optionally keep/skip closed issues, include/truncate body text, and expose truncation metadata.
# FB5 - Render an ergonomic block-owned inspector, wide modal, and node card.
# FB6 - Run through the generic block runtime path used by both centralized and zeromq_active execution modes.
# FB7 - Filter issues by exact or wildcard required/excluded labels before emitting the Iterator-compatible list.
# FB8 - Preserve GitHub issue comment contents when upstream github_issues provides comments_data.
class GitHubIssuesToListBlockError(ValueError):
    """Raised when the GitHub Issues to List block cannot parse or compact its input."""


class GitHubIssuesToListBlock(BlockDefinition):
    """Autonomous block that turns GitHub Issues JSON into compact list items."""

    kind = "github_issues_to_list"

    def ui_assets(self, surface: str = "modal") -> list[dict[str, str]]:
        """Return block-owned frontend assets for the requested UI surface.

        Args:
            surface: UI surface requesting assets.
        """

        if surface == "modal":
            return [
                {"kind": "css", "path": "assets/css/block_modal.css"},
                {"kind": "js", "path": "assets/js/block_modal.js"},
            ]
        return []

    def render_node_card(self, *, node: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Render the compact GitHub Issues transformer canvas card."""

        config = self.normalize_config(node.get("config") if isinstance(node.get("config"), dict) else {})
        body_mode = "body" if config["include_body"] else "sans body"
        return render_node_card_template(
            block=self,
            node=node,
            node_classes=["github-issues-to-list-node"],
            replacements={
                "title": node.get("title") or self.default_title(),
                "preview": "Issues -> liste item",
                "mode": f"{body_mode}, max {config['max_body_chars']}",
            },
        )

    def render_inspector_panel(self, *, node: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Render a one-field-per-line inspector for transformation options."""

        config = self.normalize_config(node.get("config") if isinstance(node.get("config"), dict) else {})
        template = (self.directory / "inspector_panel.html").read_text(encoding="utf-8")
        html = render_inspector_template(
            template=template,
            node={**node, "type": self.kind, "kind": self.kind},
            payload=payload,
            replacements={
                "include_body_checked": "checked" if config["include_body"] else "",
                "max_body_chars": config["max_body_chars"],
                "include_closed_checked": "checked" if config["include_closed"] else "",
                "empty_body_placeholder": escape(config["empty_body_placeholder"], quote=True),
                "required_labels": escape(self._labels_config_text(config["required_labels"])),
                "excluded_labels": escape(self._labels_config_text(config["excluded_labels"])),
            },
        )
        return {"html": html, "context": {"node_id": str(node.get("id") or ""), "full_panel": True}}

    def render_modal(self, *, node: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Render a wide tabbed modal owned by this block package."""

        payload = payload or {}
        title = str(node.get("title") or self.default_title())
        config = self.normalize_config(node.get("config") if isinstance(node.get("config"), dict) else {})
        template = (self.directory / "block_modal.html").read_text(encoding="utf-8")
        replacements = {
            "node_id": escape(str(node.get("id") or ""), quote=True),
            "node_title": escape(title),
            "node_kind": escape(self.kind, quote=True),
            "node_kind_title": escape(str(self.model.get("title") or self.default_title())),
            "modal_body_html": self._render_modal_body(node=node, title=title, config=config, payload=payload),
        }
        html = template
        for key, value in replacements.items():
            html = html.replace(f"{{{{ {key} }}}}", str(value))
        return {"html": html, "context": {"node_id": str(node.get("id") or ""), "node_kind": self.kind}}

    def normalize_config(self, config: dict[str, Any] | None) -> dict[str, Any]:
        """Normalize durable block options used by UI and runtime.

        Args:
            config: Raw block configuration dictionary from the graph document.
        """

        config = config if isinstance(config, dict) else {}
        return {
            "include_body": self._as_bool(config.get("include_body"), default=True),
            "max_body_chars": self._bounded_int(config.get("max_body_chars"), default=DEFAULT_MAX_BODY_CHARS, minimum=0, maximum=MAX_BODY_CHARS),
            "include_closed": self._as_bool(config.get("include_closed"), default=True),
            "empty_body_placeholder": str(config.get("empty_body_placeholder") or ""),
            "required_labels": self._normalize_label_filters(config.get("required_labels")),
            "excluded_labels": self._normalize_label_filters(config.get("excluded_labels")),
        }

    def execute_runtime(self, context: BlockRuntimeContext) -> BlockRuntimeResult:
        """Compact GitHub Issues payloads and emit a List-compatible JSON payload.

        Args:
            context: Generic runtime context injected by centralized or active execution.
        """

        config = self.normalize_config(context.config)
        try:
            raw_payload = self._input_payload(context)
            issues = self.parse_issues_payload(raw_payload)
            compact_items, metadata = self.compact_issues(issues, config=config)
        except GitHubIssuesToListBlockError as exc:
            return BlockRuntimeResult(
                status="failed",
                outputs=[],
                logs=[f"[github-issues-to-list-error] {context.node_id}: {exc}"],
                error=str(exc),
                exit_code=1,
                last_message=str(exc),
                content_type=TEXT_PLAIN,
                worker_received="-",
            )

        wrappers = [{"item": item} for item in compact_items]
        list_payload = json.dumps(wrappers, ensure_ascii=False, indent=2)
        summary = self.format_summary(metadata)
        outputs = self._runtime_outputs(context, list_payload=list_payload, summary=summary)
        logs = [
            (
                f"[github-issues-to-list] {context.node_id}: "
                f"{metadata['received_count']} issue(s) recues, "
                f"{metadata['published_count']} issue(s) conservees, "
                f"{metadata['skipped_missing_required_label_count']} exclue(s) par absence de label requis, "
                f"{metadata['skipped_excluded_label_count']} exclue(s) par label interdit."
            )
        ]
        if metadata["skipped_closed_count"]:
            logs.append(f"[github-issues-to-list] {context.node_id}: {metadata['skipped_closed_count']} issue(s) fermee(s) ignoree(s).")
        if metadata["truncated_body_count"]:
            logs.append(f"[github-issues-to-list] {context.node_id}: {metadata['truncated_body_count']} body(s) tronque(s).")
        return BlockRuntimeResult(
            status="success",
            outputs=outputs,
            logs=logs,
            last_message=list_payload,
            content_type=APPLICATION_JSON,
            worker_received=summary,
            metadata={"github_issues_to_list": metadata},
        )

    def parse_issues_payload(self, raw_payload: Any) -> list[Any]:
        """Extract issue-like objects from supported payload shapes.

        Args:
            raw_payload: Raw runtime input, usually JSON text from the GitHub Issues block.
        """

        if raw_payload is None:
            return []
        parsed = self._decode_json_if_text(raw_payload)
        issues = self._extract_issue_sequence(parsed)
        if issues is None:
            raise GitHubIssuesToListBlockError("input JSON does not contain an issue list")
        return issues

    def compact_issues(self, issues: list[Any], *, config: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
        """Compact and filter extracted GitHub issue objects.

        Args:
            issues: Issue objects extracted from input payload.
            config: Normalized block configuration controlling filters and body handling.
        """

        compact_items: list[dict[str, Any]] = []
        skipped_closed_count = 0
        truncated_body_count = 0
        skipped_missing_required_label_count = 0
        skipped_excluded_label_count = 0
        required_labels = list(config["required_labels"])
        excluded_labels = list(config["excluded_labels"])
        for issue in issues:
            if isinstance(issue, dict) and issue.get("item") is not None and self._looks_like_issue(issue.get("item")):
                issue = issue["item"]
            issue_labels = self._issue_label_keys(issue)
            if excluded_labels and self._any_label_filter_matches(excluded_labels, issue_labels):
                skipped_excluded_label_count += 1
                continue
            if required_labels and not self._all_label_filters_match(required_labels, issue_labels):
                skipped_missing_required_label_count += 1
                continue
            if isinstance(issue, dict) and str(issue.get("state") or "").lower() == "closed" and not config["include_closed"]:
                skipped_closed_count += 1
                continue
            item, was_truncated = self.compact_issue(issue, config=config)
            compact_items.append(item)
            if was_truncated:
                truncated_body_count += 1
        metadata = {
            "received_count": len(issues),
            "published_count": len(compact_items),
            "skipped_closed_count": skipped_closed_count,
            "truncated_body_count": truncated_body_count,
            "skipped_missing_required_label_count": skipped_missing_required_label_count,
            "skipped_excluded_label_count": skipped_excluded_label_count,
        }
        return compact_items, metadata

    def compact_issue(self, issue: Any, *, config: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Build one compact issue dictionary for downstream analysis.

        Args:
            issue: Raw GitHub issue object, or a fallback non-dict value.
            config: Normalized block configuration controlling body handling.
        """

        if not isinstance(issue, dict):
            text = str(issue or "")
            return {
                "number": 0,
                "title": text,
                "state": "",
                "state_reason": "",
                "labels": [],
                "milestone": "",
                "author": "",
                "assignees": [],
                "comments": 0,
                "url": "",
                "created_at": "",
                "updated_at": "",
                "closed_at": "",
                "is_pull_request": False,
            }, False

        item: dict[str, Any] = {
            "number": self._safe_int(issue.get("number")),
            "title": str(issue.get("title") or ""),
            "state": str(issue.get("state") or ""),
            "state_reason": str(issue.get("state_reason") or ""),
            "labels": self._label_names(issue.get("labels")),
            "milestone": self._milestone_title(issue.get("milestone")),
            "author": self._user_login(issue.get("user")),
            "assignees": self._user_logins(issue.get("assignees")),
            "comments": self._safe_int(issue.get("comments")),
            "url": str(issue.get("html_url") or issue.get("url") or ""),
            "created_at": str(issue.get("created_at") or ""),
            "updated_at": str(issue.get("updated_at") or ""),
            "closed_at": str(issue.get("closed_at") or ""),
            "is_pull_request": isinstance(issue.get("pull_request"), dict),
        }
        comments_data = self._compact_comments(issue.get("comments_data"))
        if comments_data:
            item["comments_data"] = comments_data
        truncated = False
        if config["include_body"]:
            body = str(issue.get("body") or config["empty_body_placeholder"] or "")
            max_chars = int(config["max_body_chars"])
            if max_chars >= 0 and len(body) > max_chars:
                body = body[:max_chars]
                truncated = True
            item["body"] = body
            item["body_truncated"] = truncated
        return item, truncated

    def format_summary(self, metadata: dict[str, int]) -> str:
        """Format a short human-readable runtime summary.

        Args:
            metadata: Runtime counters produced while compacting issues.
        """

        parts = [
            f"{metadata['received_count']} issue(s) recue(s)",
            f"{metadata['published_count']} issue(s) conservee(s)",
            f"{metadata.get('skipped_missing_required_label_count', 0)} exclue(s) par absence de label requis",
            f"{metadata.get('skipped_excluded_label_count', 0)} exclue(s) par label interdit",
        ]
        if metadata.get("skipped_closed_count"):
            parts.append(f"{metadata['skipped_closed_count']} fermee(s) ignoree(s)")
        if metadata.get("truncated_body_count"):
            parts.append(f"{metadata['truncated_body_count']} body(s) tronque(s)")
        return ", ".join(parts)

    def _render_modal_body(
        self,
        *,
        node: dict[str, Any],
        title: str,
        config: dict[str, Any],
        payload: dict[str, Any],
    ) -> str:
        """Render the tabbed body used by the block modal."""

        node_dom_id = self._modal_dom_id(node)
        tabs = [
            self._render_modal_tab(node_dom_id=node_dom_id, tab_id="transform", label="Transformation", summary="Champs et filtres", selected=True),
            self._render_modal_tab(node_dom_id=node_dom_id, tab_id="preview", label="Preview", summary="Format de sortie", selected=False),
            self._render_modal_tab(node_dom_id=node_dom_id, tab_id="status", label="Ports & etat", summary="Runtime", selected=False),
        ]
        panels = [
            self._render_transform_panel(node_dom_id=node_dom_id, title=title, config=config, selected=True),
            self._render_preview_panel(node_dom_id=node_dom_id, config=config, selected=False),
            self._render_status_panel(node_dom_id=node_dom_id, node=node, payload=payload, selected=False),
        ]
        return (
            '<div class="github-issues-to-list-modal-body" data-github-issues-to-list-modal-tabs>'
            '<nav class="github-issues-to-list-modal-tablist" role="tablist" aria-label="Configuration GitHub Issues to List">'
            + "".join(tabs)
            + "</nav>"
            + '<div class="github-issues-to-list-modal-panels">'
            + "".join(panels)
            + "</div>"
            + "</div>"
        )

    def _render_modal_tab(self, *, node_dom_id: str, tab_id: str, label: str, summary: str, selected: bool) -> str:
        """Render one tab button for the block modal."""

        tab_dom_id = f"github-issues-to-list-{node_dom_id}-tab-{tab_id}"
        panel_dom_id = f"github-issues-to-list-{node_dom_id}-panel-{tab_id}"
        return (
            '<button class="github-issues-to-list-modal-tab" type="button" role="tab" '
            f'id="{escape(tab_dom_id, quote=True)}" aria-controls="{escape(panel_dom_id, quote=True)}" '
            f'aria-selected="{str(selected).lower()}" tabindex="{0 if selected else -1}" '
            f'data-github-issues-to-list-modal-tab data-github-issues-to-list-tab-id="{escape(tab_id, quote=True)}">'
            f'<span>{escape(label)}</span><small>{escape(summary)}</small>'
            '</button>'
        )

    def _render_transform_panel(self, *, node_dom_id: str, title: str, config: dict[str, Any], selected: bool) -> str:
        """Render editable transformation settings."""

        panel_id = f"github-issues-to-list-{node_dom_id}-panel-transform"
        tab_id = f"github-issues-to-list-{node_dom_id}-tab-transform"
        include_body = "checked" if config["include_body"] else ""
        include_closed = "checked" if config["include_closed"] else ""
        return (
            '<section class="github-issues-to-list-modal-panel" data-github-issues-to-list-modal-panel '
            f'data-github-issues-to-list-tab-id="transform" id="{escape(panel_id, quote=True)}" role="tabpanel" '
            f'aria-labelledby="{escape(tab_id, quote=True)}"{ "" if selected else " hidden" }>'
            '<div class="github-issues-to-list-modal-layout">'
            '<section class="github-issues-to-list-modal-section">'
            '<div class="ports-editor-header"><span class="group-label">Identite</span></div>'
            f'{self._render_title_field(title)}'
            '</section>'
            '<section class="github-issues-to-list-modal-section">'
            '<div class="ports-editor-header"><span class="group-label">Options de transformation</span></div>'
            '<label class="checkbox-line">'
            f'<input data-block-config-field="include_body" data-block-value-type="boolean" type="checkbox" {include_body} />'
            '<span>Inclure le body dans chaque item</span>'
            '</label>'
            '<div class="field-group">'
            '<label>Taille max du body</label>'
            f'<input data-block-config-field="max_body_chars" data-block-value-type="integer" type="number" min="0" max="{MAX_BODY_CHARS}" step="100" value="{config["max_body_chars"]}" />'
            '</div>'
            '<label class="checkbox-line">'
            f'<input data-block-config-field="include_closed" data-block-value-type="boolean" type="checkbox" {include_closed} />'
            '<span>Conserver les issues fermees recues</span>'
            '</label>'
            '<div class="field-group">'
            '<label>Placeholder body vide</label>'
            f'<input data-block-config-field="empty_body_placeholder" type="text" autocomplete="off" spellcheck="false" placeholder="Optionnel" value="{escape(config["empty_body_placeholder"], quote=True)}" />'
            '</div>'
            '<div class="field-group">'
            '<label>Labels obligatoires</label>'
            f'<textarea data-block-config-field="required_labels" data-block-value-type="json" rows="4" spellcheck="false" placeholder="[&quot;todo&quot;]">{escape(self._labels_config_text(config["required_labels"]))}</textarea>'
            '</div>'
            '<div class="field-group">'
            '<label>Labels interdits</label>'
            f'<textarea data-block-config-field="excluded_labels" data-block-value-type="json" rows="4" spellcheck="false" placeholder="[&quot;status:done&quot;]">{escape(self._labels_config_text(config["excluded_labels"]))}</textarea>'
            '</div>'
            '<p class="github-issues-to-list-modal-help">Les labels sont compares en minuscules. Le caractere * est accepte, par exemple closed:*. Les labels interdits sont prioritaires sur les labels obligatoires.</p>'
            '<p class="github-issues-to-list-modal-help">Le bloc ne contacte pas GitHub. Il transforme uniquement une reponse deja recue ou un tableau JSON.</p>'
            '</section>'
            '</div>'
            '</section>'
        )

    def _render_preview_panel(self, *, node_dom_id: str, config: dict[str, Any], selected: bool) -> str:
        """Render a stable example of the emitted JSON list shape."""

        panel_id = f"github-issues-to-list-{node_dom_id}-panel-preview"
        tab_id = f"github-issues-to-list-{node_dom_id}-tab-preview"
        sample_issue = {
            "number": 1,
            "title": "Example issue",
            "state": "open",
            "labels": ["enhancement"],
            "milestone": "1.0.7",
            "author": "octocat",
            "assignees": [],
            "comments": 0,
            "url": "https://github.com/owner/repo/issues/1",
            "created_at": "2026-05-25T21:03:35Z",
            "updated_at": "2026-05-25T21:04:47Z",
            "closed_at": "",
            "is_pull_request": False,
        }
        if config["include_body"]:
            sample_issue["body"] = "Compact issue body"
            sample_issue["body_truncated"] = False
        sample = json.dumps([{"item": sample_issue}], ensure_ascii=False, indent=2)
        return (
            '<section class="github-issues-to-list-modal-panel" data-github-issues-to-list-modal-panel '
            f'data-github-issues-to-list-tab-id="preview" id="{escape(panel_id, quote=True)}" role="tabpanel" '
            f'aria-labelledby="{escape(tab_id, quote=True)}"{ "" if selected else " hidden" }>'
            '<section class="github-issues-to-list-modal-section">'
            '<div class="ports-editor-header"><span class="group-label">Sortie liste JSON</span></div>'
            '<p class="github-issues-to-list-modal-help">Chaque issue devient un wrapper <code>{"item": {...}}</code>. Iterator emettra ensuite un item par trigger.</p>'
            f'<pre class="github-issues-to-list-preview"><code>{escape(sample)}</code></pre>'
            '</section>'
            '</section>'
        )

    def _render_status_panel(self, *, node_dom_id: str, node: dict[str, Any], payload: dict[str, Any], selected: bool) -> str:
        """Render ports and latest runtime state inside the modal."""

        panel_id = f"github-issues-to-list-{node_dom_id}-panel-status"
        tab_id = f"github-issues-to-list-{node_dom_id}-tab-status"
        runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
        status = str(runtime.get("status") or "Aucun etat runtime disponible.")
        last_message = str(runtime.get("last_message") or "")
        return (
            '<section class="github-issues-to-list-modal-panel" data-github-issues-to-list-modal-panel '
            f'data-github-issues-to-list-tab-id="status" id="{escape(panel_id, quote=True)}" role="tabpanel" '
            f'aria-labelledby="{escape(tab_id, quote=True)}"{ "" if selected else " hidden" }>'
            '<div class="github-issues-to-list-modal-layout">'
            '<section class="github-issues-to-list-modal-section">'
            '<div class="ports-editor-header"><span class="group-label">Entrees</span></div>'
            f'{render_ports_rows(node, "input", payload=payload)}'
            '</section>'
            '<section class="github-issues-to-list-modal-section">'
            '<div class="ports-editor-header"><span class="group-label">Sorties</span></div>'
            f'{render_ports_rows(node, "output", payload=payload)}'
            '</section>'
            '</div>'
            '<section class="github-issues-to-list-modal-section github-issues-to-list-status-section">'
            '<div class="ports-editor-header"><span class="group-label">Dernier etat</span></div>'
            f'<p class="github-issues-to-list-modal-help">{escape(status)}</p>'
            f'<pre class="github-issues-to-list-preview"><code>{escape(last_message[:4000])}</code></pre>'
            '</section>'
            '</section>'
        )

    def _render_title_field(self, title: str) -> str:
        """Render a standard node title editor field for modals."""

        return (
            '<div class="field-group">'
            '<label>Nom du bloc</label>'
            f'<input data-node-title-input data-block-title-field type="text" autocomplete="off" spellcheck="false" value="{escape(title, quote=True)}" />'
            '</div>'
        )

    def _runtime_outputs(self, context: BlockRuntimeContext, *, list_payload: str, summary: str) -> list[BlockRuntimeOutput]:
        """Map logical outputs to the concrete ports declared on the node."""

        outputs: list[BlockRuntimeOutput] = []
        for port in context.output_ports:
            port_id = int(getattr(port, "id", 0) or 0)
            name = str(getattr(port, "name", "") or "").strip().lower()
            if name == "liste" or port_id == 1:
                outputs.append(
                    BlockRuntimeOutput(
                        port_id=port_id,
                        port_name=str(getattr(port, "name", "") or ""),
                        value=list_payload,
                        content_type=APPLICATION_JSON,
                    )
                )
            elif name == "summary" or port_id == 2:
                outputs.append(
                    BlockRuntimeOutput(
                        port_id=port_id,
                        port_name=str(getattr(port, "name", "") or ""),
                        value=summary,
                        content_type=TEXT_PLAIN,
                    )
                )
        return outputs

    def _input_payload(self, context: BlockRuntimeContext) -> Any:
        """Return the primary runtime input in declared input-port order."""

        for port in sorted(context.input_ports, key=lambda item: int(getattr(item, "id", 0) or 0)):
            name = str(getattr(port, "name", "") or "").strip()
            port_id = str(int(getattr(port, "id", 0) or 0))
            value = context.input_value(name, port_id)
            if value not in (None, ""):
                return value
        return context.first_input_value(default=context.input_message)

    def _decode_json_if_text(self, raw_payload: Any) -> Any:
        """Decode JSON strings while preserving already structured values."""

        if isinstance(raw_payload, (dict, list)):
            return raw_payload
        text = str(raw_payload or "").strip()
        if not text:
            return []
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise GitHubIssuesToListBlockError("input is not valid JSON") from exc

    def _extract_issue_sequence(self, payload: Any) -> list[Any] | None:
        """Return a list of issues from supported raw response shapes."""

        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            return None
        if self._looks_like_issue(payload):
            return [payload]
        if "item" in payload:
            return self._extract_issue_sequence(payload.get("item"))
        for key in LIST_KEYS:
            value = payload.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                extracted = self._extract_issue_sequence(value)
                if extracted is not None:
                    return extracted
        return None

    def _looks_like_issue(self, value: Any) -> bool:
        """Return whether a value resembles one GitHub issue object."""

        return isinstance(value, dict) and ("number" in value or "title" in value or "html_url" in value)

    def _compact_comments(self, comments: Any) -> list[dict[str, Any]]:
        """Return compact comment objects from GitHub comments_data payloads.

        Args:
            comments: Raw GitHub comments array provided by github_issues when include_comments is enabled.
        """

        if not isinstance(comments, list):
            return []
        compacted: list[dict[str, Any]] = []
        for comment in comments:
            if not isinstance(comment, dict):
                continue
            compacted.append(
                {
                    "id": self._safe_int(comment.get("id")),
                    "author": self._user_login(comment.get("user")),
                    "body": str(comment.get("body") or ""),
                    "created_at": str(comment.get("created_at") or ""),
                    "updated_at": str(comment.get("updated_at") or ""),
                    "url": str(comment.get("html_url") or comment.get("url") or ""),
                }
            )
        return compacted

    def _label_names(self, labels: Any) -> list[str]:
        """Normalize GitHub label payloads to label names."""

        if not isinstance(labels, list):
            return []
        result: list[str] = []
        for label in labels:
            if isinstance(label, dict):
                name = str(label.get("name") or label.get("title") or "").strip()
            else:
                name = str(label or "").strip()
            if name:
                result.append(name)
        return result

    def _normalize_label_filters(self, value: Any) -> list[str]:
        """Normalize user-configured label filters to lowercase comparison keys.

        Args:
            value: JSON array, comma/newline separated text, or GitHub-like label objects.
        """

        if value is None:
            candidates: list[Any] = []
        elif isinstance(value, str):
            text = value.strip()
            if not text:
                candidates = []
            else:
                try:
                    decoded = json.loads(text)
                except json.JSONDecodeError:
                    candidates = [part for line in text.splitlines() for part in line.split(",")]
                else:
                    candidates = decoded if isinstance(decoded, list) else [decoded]
        elif isinstance(value, list):
            candidates = value
        else:
            candidates = [value]

        normalized: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if isinstance(candidate, dict):
                label = candidate.get("name") or candidate.get("title") or candidate.get("label")
            else:
                label = candidate
            key = self._label_key(label)
            if key and key not in seen:
                seen.add(key)
                normalized.append(key)
        return normalized

    def _labels_config_text(self, labels: list[str]) -> str:
        """Render label filter configuration as stable JSON for textarea fields."""

        return json.dumps(labels, ensure_ascii=False, indent=2)

    def _issue_label_keys(self, issue: Any) -> set[str]:
        """Return normalized label names present on one issue-like value."""

        labels = issue.get("labels") if isinstance(issue, dict) else []
        keys: set[str] = set()
        for label in self._label_names(labels):
            key = self._label_key(label)
            if key:
                keys.add(key)
        return keys

    def _all_label_filters_match(self, filters: list[str], issue_labels: set[str]) -> bool:
        """Return whether every configured required label filter matches the issue labels.

        Args:
            filters: Normalized exact labels or `*` wildcard patterns from block configuration.
            issue_labels: Normalized labels present on one issue.
        """

        return all(self._label_filter_matches(label_filter, issue_labels) for label_filter in filters)

    def _any_label_filter_matches(self, filters: list[str], issue_labels: set[str]) -> bool:
        """Return whether at least one configured excluded label filter matches the issue labels.

        Args:
            filters: Normalized exact labels or `*` wildcard patterns from block configuration.
            issue_labels: Normalized labels present on one issue.
        """

        return any(self._label_filter_matches(label_filter, issue_labels) for label_filter in filters)

    def _label_filter_matches(self, label_filter: str, issue_labels: set[str]) -> bool:
        """Match one exact label or `*` wildcard pattern against issue labels.

        Args:
            label_filter: Normalized label filter. Without `*`, matching stays exact.
            issue_labels: Normalized labels present on one issue.
        """

        if "*" not in label_filter:
            return label_filter in issue_labels
        return any(fnmatchcase(label, label_filter) for label in issue_labels)

    def _label_key(self, value: Any) -> str:
        """Normalize one label value for case-insensitive comparisons."""

        return str(value or "").strip().lower()

    def _milestone_title(self, milestone: Any) -> str:
        """Normalize a GitHub milestone payload to its title."""

        if isinstance(milestone, dict):
            return str(milestone.get("title") or "")
        return str(milestone or "")

    def _user_login(self, user: Any) -> str:
        """Normalize a GitHub user payload to its login."""

        if isinstance(user, dict):
            return str(user.get("login") or "")
        return str(user or "")

    def _user_logins(self, users: Any) -> list[str]:
        """Normalize a list of GitHub users to logins."""

        if not isinstance(users, list):
            return []
        return [login for login in (self._user_login(user).strip() for user in users) if login]

    def _safe_int(self, value: Any) -> int:
        """Convert numeric GitHub fields to int without raising."""

        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _as_bool(self, value: Any, *, default: bool) -> bool:
        """Normalize booleans accepted from JSON or generic UI fields."""

        if isinstance(value, bool):
            return value
        if value is None:
            return default
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        return default

    def _bounded_int(self, value: Any, *, default: int, minimum: int, maximum: int) -> int:
        """Clamp integer configuration values to a safe range."""

        try:
            number = int(value)
        except (TypeError, ValueError):
            number = default
        return min(max(number, minimum), maximum)

    def _modal_dom_id(self, node: dict[str, Any]) -> str:
        """Return a DOM-safe suffix for modal tab ids."""

        raw = str(node.get("id") or self.kind)
        return "".join(character if character.isalnum() else "-" for character in raw)
