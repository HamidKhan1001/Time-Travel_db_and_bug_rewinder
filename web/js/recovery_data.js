(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.RecoveryData = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  var OPERATIONS = ["INSERT", "UPDATE", "DELETE"];

  function isObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function formatValue(value) {
    if (value === null || value === undefined) {
      return {label: "null", type: "null"};
    }
    if (typeof value === "boolean") {
      return {label: String(value), type: "boolean"};
    }
    if (typeof value === "number") {
      return {label: Number.isFinite(value) ? String(value) : String(value), type: "number"};
    }
    if (typeof value === "string") {
      return {label: value === "" ? "(empty string)" : value, type: "string"};
    }
    if (Array.isArray(value) || isObject(value)) {
      try {
        return {label: JSON.stringify(value), type: "structured"};
      } catch (error) {
        return {label: "[unserializable value]", type: "unavailable"};
      }
    }
    return {label: String(value), type: "unavailable"};
  }

  function normalizeCounts(counts) {
    var result = {INSERT: null, UPDATE: null, DELETE: null};
    OPERATIONS.forEach(function (operation) {
      var value = counts && counts[operation];
      if (typeof value === "number" && Number.isFinite(value) && value >= 0) {
        result[operation] = value;
      }
    });
    return result;
  }

  function buildProjection(session) {
    if (!isObject(session)) {
      return {state: "error", error: "Invalid session data.", rows: [], actualAvailable: false};
    }
    var preview = session.recovery_preview;
    if (!isObject(preview)) {
      return {
        state: "unavailable",
        error: "No recovery preview was provided by the backend.",
        rows: [],
        actualAvailable: false
      };
    }
    if (!Array.isArray(preview.rows) || !isObject(preview.operation_counts)) {
      return {
        state: "error",
        error: "The recovery preview has an unsupported shape.",
        rows: [],
        actualAvailable: false
      };
    }

    var phase = typeof session.phase === "string" ? session.phase : "unknown";
    var executed = phase === "applied" || phase === "undone";
    var actual = isObject(session.actual_recovery) ? session.actual_recovery : null;
    var actualAvailable = executed && isObject(actual) && isObject(actual.values);
    var rows = [];

    for (var index = 0; index < preview.rows.length; index += 1) {
      var source = preview.rows[index];
      if (!isObject(source) || typeof source.id !== "string" ||
          typeof source.table !== "string" || typeof source.key !== "string" ||
          typeof source.field !== "string") {
        return {
          state: "error",
          error: "The recovery preview contains an invalid comparison row.",
          rows: [],
          actualAvailable: false
        };
      }
      var operation = typeof source.operation === "string" ? source.operation.toUpperCase() : "UNKNOWN";
      var observed = actualAvailable && Object.prototype.hasOwnProperty.call(actual.values, source.id)
        ? actual.values[source.id]
        : {unavailable: "not captured by the backend"};
      rows.push({
        id: source.id,
        table: source.table,
        key: source.key,
        field: source.field,
        operation: operation,
        before: source.before,
        after: source.after,
        actual: observed,
        note: source.note || null
      });
    }

    var counts = normalizeCounts(preview.operation_counts);
    return {
      state: "proposed",
      label: "PROPOSED — NOT APPLIED",
      sourceLabel: preview.label || "Proposed recovery projection",
      generatedAt: typeof preview.generated_at === "number" ? preview.generated_at : null,
      source: typeof preview.source === "string" ? preview.source : null,
      rows: rows,
      rowCount: typeof preview.row_count === "number" ? preview.row_count : rows.length,
      sampleTruncated: Boolean(preview.sample_truncated),
      tables: Array.isArray(preview.tables) ? preview.tables.slice() : [],
      operationCounts: counts,
      countsUnavailable: OPERATIONS.some(function (operation) { return counts[operation] === null; }),
      validation: isObject(preview.validation) ? preview.validation : {},
      conflicts: Array.isArray(preview.conflicts) ? preview.conflicts.slice() : [],
      deleteSemantics: typeof preview.delete_semantics === "string" ? preview.delete_semantics : null,
      actualAvailable: actualAvailable,
      actualCapturedAt: actualAvailable && typeof actual.captured_at === "number" ? actual.captured_at : null,
      undone: phase === "undone"
    };
  }

  function mergeLifecycle(events) {
    if (!Array.isArray(events)) {
      return [];
    }
    var byId = new Map();
    events.forEach(function (envelope) {
      if (!isObject(envelope)) {
        return;
      }
      var id = envelope.id === undefined || envelope.id === null ? "" : String(envelope.id);
      if (!/^\d+$/.test(id)) {
        return;
      }
      if (byId.has(id)) {
        return;
      }
      var timestamp = envelope.timestamp !== undefined && envelope.timestamp !== null
        ? envelope.timestamp
        : (envelope.ts !== undefined && envelope.ts !== null ? envelope.ts : null);
      var payload = envelope.payload !== undefined && envelope.payload !== null
        ? envelope.payload
        : (envelope.detail !== undefined && envelope.detail !== null ? envelope.detail : {});
      byId.set(id, {
        id: id,
        name: String(envelope.event_type || envelope.event || envelope.name || "unknown"),
        status: String(envelope.status || "info"),
        timestamp: typeof timestamp === "number" ? timestamp : null,
        details: payload
      });
    });
    return Array.from(byId.values()).sort(function (left, right) {
      return Number(left.id) - Number(right.id);
    });
  }

  function deriveVerification(session) {
    if (!isObject(session)) {
      return {state: "unavailable", label: "Verification unavailable", checks: []};
    }
    var report = session.verification;
    var phase = typeof session.phase === "string" ? session.phase : "unknown";
    if (!isObject(report)) {
      if (phase === "applied" || phase === "undone") {
        return {
          state: "unavailable",
          label: "Verification unavailable",
          message: "The backend did not report verification results for this session.",
          checks: []
        };
      }
      return {
        state: "pending",
        label: "Not yet verified",
        message: "Recovery has not been applied, so no verification result exists.",
        checks: []
      };
    }
    var state = report.status === "passed" || report.status === "failed" ? report.status : "unavailable";
    var labels = {passed: "Verification passed", failed: "Verification failed", unavailable: "Verification unavailable"};
    return {
      state: state,
      label: labels[state],
      method: typeof report.method === "string" ? report.method : null,
      checks: Array.isArray(report.checks) ? report.checks.slice() : [],
      completedAt: typeof report.completed_at === "number" ? report.completed_at : null,
      checksum: isObject(report.checksum) ? report.checksum : {status: "unavailable"}
    };
  }

  function deriveUndo(session) {
    if (!isObject(session)) {
      return {state: "unavailable", label: "Undo status unavailable", available: false};
    }
    var state = isObject(session.undo_state) ? session.undo_state : {};
    var succeeded = Boolean(state.succeeded) || session.phase === "undone";
    var failed = Boolean(state.failed);
    var initiated = Boolean(state.initiated) || succeeded || failed;
    var backendAllows = Boolean(session.can_undo);
    if (!Object.prototype.hasOwnProperty.call(session, "can_undo") && typeof state.available === "boolean") {
      backendAllows = state.available;
    }
    var available = backendAllows && !succeeded;
    var key = succeeded ? "succeeded" : failed ? "failed" : initiated ? "initiated" : available ? "available" : "unavailable";
    var labels = {
      succeeded: "Undo succeeded",
      failed: "Undo failed",
      initiated: "Undo initiated",
      available: "Undo available",
      unavailable: "Undo not available"
    };
    return {
      state: key,
      label: labels[key],
      available: available,
      initiated: initiated,
      succeeded: succeeded,
      failed: failed,
      detail: typeof state.detail === "string" ? state.detail : null,
      completedAt: typeof state.completed_at === "number" ? state.completed_at : null
    };
  }

  function buildStatus(session, verification) {
    if (!isObject(session)) {
      return [];
    }
    var phase = typeof session.phase === "string" ? session.phase : "unknown";
    var states = [{key: "original", label: "ORIGINAL", detail: "Compared with live state captured at plan time."}];
    if (session.recovery_preview) {
      states.push({key: "proposed", label: "PROPOSED", detail: "Read-only projection; not applied."});
    }
    if (phase === "awaiting_approval") {
      states.push({key: "awaiting", label: "AWAITING APPROVAL", detail: "No database change has been approved."});
    }
    if (phase === "applying") {
      states.push({key: "approved", label: "APPROVED", detail: "Approval granted; execution in progress."});
    }
    if (phase === "applied") {
      states.push({key: "applied", label: "APPLIED", detail: "Approved recovery committed."});
    }
    if (phase === "undone") {
      states.push({key: "undone", label: "UNDONE", detail: "Pre-recovery snapshot restored."});
    }
    if (phase === "error" || (verification && verification.state === "failed")) {
      states.push({key: "failed", label: "FAILED", detail: "The backend reported a failure."});
    }
    if (verification && verification.state === "passed") {
      states.push({key: "verified", label: "VERIFIED", detail: "Backend verification checks passed."});
    }
    return states;
  }

  return {
    OPERATIONS: OPERATIONS,
    formatValue: formatValue,
    buildProjection: buildProjection,
    mergeLifecycle: mergeLifecycle,
    deriveVerification: deriveVerification,
    deriveUndo: deriveUndo,
    buildStatus: buildStatus
  };
});
