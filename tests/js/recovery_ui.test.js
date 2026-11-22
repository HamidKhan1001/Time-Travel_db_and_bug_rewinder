const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const data = require(path.join(__dirname, "..", "..", "web", "js", "recovery_data.js"));
const view = require(path.join(__dirname, "..", "..", "web", "js", "recovery_view.js"));

class FakeText {
  constructor(value) {
    this.nodeType = 3;
    this.data = String(value);
    this.parentNode = null;
  }
  get textContent() {
    return this.data;
  }
}

class FakeElement {
  constructor(tag) {
    this.nodeType = 1;
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.firstChild = null;
    this.parentNode = null;
    this.className = "";
    this.title = "";
    this.attributes = {};
  }
  appendChild(child) {
    this.children.push(child);
    child.parentNode = this;
    this.firstChild = this.children[0] || null;
    return child;
  }
  removeChild(child) {
    const index = this.children.indexOf(child);
    if (index >= 0) {
      this.children.splice(index, 1);
    }
    this.firstChild = this.children[0] || null;
    child.parentNode = null;
    return child;
  }
  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }
  get textContent() {
    return this.children.map((child) => child.textContent).join("");
  }
}

class FakeDocument {
  createElement(tag) {
    return new FakeElement(tag);
  }
  createTextNode(value) {
    return new FakeText(value);
  }
}

function root() {
  return new FakeDocument().createElement("div");
}

function walk(node, callback) {
  (node.children || []).forEach((child) => {
    callback(child);
    walk(child, callback);
  });
}

function textOf(node) {
  return node.textContent;
}

function withClass(node, className) {
  const found = [];
  walk(node, (child) => {
    if (String(child.className || "").split(/\s+/).includes(className)) {
      found.push(child);
    }
  });
  return found;
}

function previewWith(rows, overrides) {
  return Object.assign({
    label: "PROPOSED RECOVERY PROJECTION — NOT APPLIED",
    generated_at: 1000,
    source: "test plan",
    row_count: rows.length,
    rows: rows,
    tables: [...new Set(rows.map((row) => row.table))],
    operation_counts: {INSERT: 0, UPDATE: 0, DELETE: 0},
    conflicts: [],
    validation: {dry_run_ok: true, checks: []},
    delete_semantics: "No DELETE statements are proposed."
  }, overrides || {});
}

function row(operation, overrides) {
  return Object.assign({
    id: `${operation.toLowerCase()}-row`,
    table: "inventory",
    key: "APX-0007",
    field: "stock",
    operation: operation,
    before: 0,
    after: 42,
    note: null
  }, overrides || {});
}

test("formatValue handles null, empty, scalar, and structured values", () => {
  assert.deepEqual(data.formatValue(null), {label: "null", type: "null"});
  assert.deepEqual(data.formatValue(undefined), {label: "null", type: "null"});
  assert.equal(data.formatValue("").label, "(empty string)");
  assert.equal(data.formatValue(true).label, "true");
  assert.equal(data.formatValue(42).label, "42");
  assert.deepEqual(JSON.parse(data.formatValue({a: [1, null]}).label), {a: [1, null]});
});

test("projection is labelled proposed and uses backend operation counts", () => {
  const session = {
    phase: "awaiting_approval",
    recovery_preview: previewWith([row("UPDATE")], {
      operation_counts: {INSERT: 7, UPDATE: 3, DELETE: 0},
      row_count: 10,
      sample_truncated: true
    })
  };
  const projection = data.buildProjection(session);
  assert.equal(projection.state, "proposed");
  assert.equal(projection.label, "PROPOSED — NOT APPLIED");
  assert.deepEqual(projection.operationCounts, {INSERT: 7, UPDATE: 3, DELETE: 0});
  assert.equal(projection.rowCount, 10);
  assert.equal(projection.sampleTruncated, true);
  assert.equal(projection.actualAvailable, false);
});

test("actual recovered values are not rendered before execution", () => {
  const session = {
    phase: "awaiting_approval",
    recovery_preview: previewWith([row("UPDATE", {after: 42})]),
    actual_recovery: {values: {"update-row": 999}, captured_at: 2000}
  };
  const projection = data.buildProjection(session);
  const container = root();
  view.renderProjection(container, projection, new FakeDocument());
  const markup = textOf(container);
  assert.equal(projection.actualAvailable, false);
  assert.ok(markup.includes("Not executed — unavailable"));
  assert.ok(!markup.includes("999"));
});

test("INSERT, UPDATE, and DELETE rows render with explicit operation labels", () => {
  const rows = [
    row("INSERT", {id: "i1", table: "orders", field: "record", before: null, after: {id: 1041, status: "paid"}}),
    row("UPDATE", {id: "u1", table: "inventory", key: "APX-0007", before: 0, after: 42}),
    row("DELETE", {id: "d1", table: "inventory", key: "APX-0042", before: "stale", after: null})
  ];
  const container = root();
  view.renderProjection(container, data.buildProjection({
    phase: "applied",
    recovery_preview: previewWith(rows),
    actual_recovery: {values: {i1: {id: 1041, status: "paid"}, u1: 42, d1: "unavailable"}, captured_at: 2}
  }), new FakeDocument());
  const markup = textOf(container);
  assert.ok(markup.includes("[INSERT]"));
  assert.ok(markup.includes("[UPDATE]"));
  assert.ok(markup.includes("[DELETE]"));
  assert.equal(withClass(container, "operation-insert").length, 1);
  assert.equal(withClass(container, "operation-update").length, 1);
  assert.equal(withClass(container, "operation-delete").length, 1);
});

test("null, empty, and structured values render with readable labels", () => {
  const rows = [
    row("UPDATE", {id: "null-row", before: null, after: 1}),
    row("UPDATE", {id: "empty-row", before: "", after: "new"}),
    row("INSERT", {id: "json-row", before: null, after: {"flag": true, "list": [1, 2]}})
  ];
  const container = root();
  view.renderProjection(container, data.buildProjection({
    phase: "applied",
    recovery_preview: previewWith(rows),
    actual_recovery: {values: {}, captured_at: 2}
  }), new FakeDocument());
  const markup = textOf(container);
  assert.ok(markup.includes("null"));
  assert.ok(markup.includes("(empty string)"));
  assert.ok(markup.includes('{"flag":true,"list":[1,2]}'));
});

test("untrusted strings are rendered as text and never as elements", () => {
  const payload = '<img src=x onerror="alert(1)">';
  const container = root();
  view.renderProjection(container, data.buildProjection({
    phase: "applied",
    recovery_preview: previewWith([row("UPDATE", {after: payload})]),
    actual_recovery: {values: {}, captured_at: 2}
  }), new FakeDocument());
  assert.ok(textOf(container).includes(payload));
  const tags = [];
  walk(container, (child) => tags.push(child.tagName));
  assert.ok(!tags.includes("IMG"));
});

test("missing and invalid preview data produce safe empty or error states", () => {
  const missing = data.buildProjection({phase: "awaiting_approval"});
  assert.equal(missing.state, "unavailable");
  const invalid = data.buildProjection({phase: "applied", recovery_preview: {rows: "bad", operation_counts: {}}});
  assert.equal(invalid.state, "error");
  const container = root();
  view.renderProjection(container, missing, new FakeDocument());
  assert.ok(textOf(container).includes("No recovery preview was provided by the backend."));
  const errorContainer = root();
  view.renderProjection(errorContainer, invalid, new FakeDocument());
  assert.ok(textOf(errorContainer).includes("unsupported shape"));
});

test("lifecycle events are normalized, deduplicated by stable id, and ordered", () => {
  const merged = data.mergeLifecycle([
    {id: 3, event_type: "recovery_completed", status: "completed", timestamp: 30, payload: {code_patched: true}},
    {id: 1, event_type: "session_started", status: "started", ts: 10, detail: {}},
    {id: 3, event_type: "recovery_completed", status: "completed", timestamp: 30, payload: {code_patched: true}},
    null,
    {event_type: "without_id"}
  ]);
  assert.deepEqual(merged.map((event) => event.id), ["1", "3"]);
  assert.equal(merged[1].name, "recovery_completed");
  assert.deepEqual(merged[1].details, {code_patched: true});
});

test("lifecycle rendering includes names, statuses, timestamps, details, and stable ids", () => {
  const container = root();
  view.renderLifecycle(container, data.mergeLifecycle([
    {id: 4, event_type: "approval_rejected", status: "rejected", timestamp: 40, payload: {current_phase: "applied"}},
    {id: 5, event_type: "undo_completed", status: "completed", timestamp: 41, payload: {}}
  ]), new FakeDocument());
  const markup = textOf(container);
  assert.ok(markup.includes("approval_rejected"));
  assert.ok(markup.includes("[REJECTED]"));
  assert.ok(markup.includes("undo_completed"));
  assert.ok(markup.includes("event #4"));
  assert.ok(markup.includes("current_phase"));
  const items = withClass(container, "timeline-item");
  assert.equal(items.length, 2);
  assert.equal(items[0].attributes["data-event-id"], "4");
});

test("SSE and polling fallback events merge without duplicate timeline entries", () => {
  const sseEvent = {id: 7, event_type: "approval_granted", status: "approved", timestamp: 7, payload: {}};
  const auditEvent = {id: 7, event_type: "approval_granted", status: "approved", ts: 7, detail: {}};
  const later = {id: 8, event_type: "recovery_started", status: "started", ts: 8, detail: {}};
  const merged = data.mergeLifecycle([sseEvent, auditEvent, later]);
  assert.deepEqual(merged.map((event) => event.id), ["7", "8"]);
});

test("status distinguishes applied, failed, verified, and undone states", () => {
  const applied = data.buildStatus({phase: "applied", recovery_preview: {}},
    data.deriveVerification({phase: "applied", verification: {status: "passed", checks: []}}));
  assert.ok(applied.some((state) => state.key === "applied"));
  assert.ok(applied.some((state) => state.key === "verified"));
  const failed = data.buildStatus({phase: "error", recovery_preview: {}},
    data.deriveVerification({phase: "error", verification: {status: "failed", checks: []}}));
  assert.ok(failed.some((state) => state.key === "failed"));
  const undone = data.buildStatus({phase: "undone", recovery_preview: {}}, data.deriveVerification({phase: "undone"}));
  assert.ok(undone.some((state) => state.key === "undone"));
});

test("verification distinguishes pending, passed, failed, and unavailable", () => {
  assert.equal(data.deriveVerification({phase: "awaiting_approval"}).state, "pending");
  assert.equal(data.deriveVerification({phase: "applied"}).state, "unavailable");
  assert.equal(data.deriveVerification({phase: "applied", verification: {status: "passed", checks: []}}).state, "passed");
  assert.equal(data.deriveVerification({phase: "applied", verification: {status: "failed", checks: []}}).state, "failed");
  const container = root();
  view.renderVerification(container, data.deriveVerification({phase: "awaiting_approval"}), new FakeDocument());
  assert.ok(textOf(container).includes("Not yet verified"));
});

test("verification rendering shows method, checks, and unavailable checksum honestly", () => {
  const container = root();
  view.renderVerification(container, data.deriveVerification({
    phase: "applied",
    verification: {
      status: "passed",
      method: "Post-apply smoke checks",
      checks: [{name: "Foreign keys intact", ok: true, detail: "0 violations"}],
      completed_at: 50,
      checksum: {status: "unavailable", reason: "not exposed by this session"}
    }
  }), new FakeDocument());
  const markup = textOf(container);
  assert.ok(markup.includes("Verification passed"));
  assert.ok(markup.includes("Post-apply smoke checks"));
  assert.ok(markup.includes("PASS — Foreign keys intact"));
  assert.ok(markup.includes("Checksum result: unavailable"));
  assert.ok(markup.includes("not exposed by this session"));
});

test("undo rendering respects backend availability and reflects success or failure", () => {
  const available = data.deriveUndo({phase: "applied", can_undo: true, undo_state: {available: true}});
  assert.equal(available.state, "available");
  assert.equal(available.available, true);
  const succeeded = data.deriveUndo({phase: "undone", can_undo: false,
    undo_state: {succeeded: true, initiated: true, completed_at: 9, detail: "snapshot restored"}});
  assert.equal(succeeded.state, "succeeded");
  assert.equal(succeeded.available, false);
  const failed = data.deriveUndo({phase: "applied", can_undo: true,
    undo_state: {failed: true, initiated: true, available: true, detail: "snapshot missing"}});
  assert.equal(failed.state, "failed");
  const container = root();
  view.renderUndo(container, failed, new FakeDocument());
  assert.ok(textOf(container).includes("Undo failed"));
  assert.ok(textOf(container).includes("snapshot missing"));
});
