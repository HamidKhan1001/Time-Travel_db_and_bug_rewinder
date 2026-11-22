(function (root, factory) {
  var data = typeof module === "object" && module.exports
    ? require("./recovery_data.js")
    : root.RecoveryData;
  var api = factory(data);
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.RecoveryView = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function (data) {
  "use strict";

  function clear(node) {
    while (node && node.firstChild) {
      node.removeChild(node.firstChild);
    }
  }

  function node(doc, tag, className, text) {
    var element = doc.createElement(tag);
    if (className) {
      element.className = className;
    }
    if (text !== undefined && text !== null) {
      element.appendChild(doc.createTextNode(String(text)));
    }
    return element;
  }

  function valueCell(doc, value) {
    var formatted = data.formatValue(value);
    return node(doc, "td", "value value-" + formatted.type, formatted.label);
  }

  function appendEmpty(root, doc, message) {
    root.appendChild(node(doc, "div", "empty-state", message));
  }

  function renderStatus(root, states, doc) {
    clear(root);
    if (!Array.isArray(states) || states.length === 0) {
      appendEmpty(root, doc, "No recovery state reported.");
      return;
    }
    states.forEach(function (state) {
      var badge = node(doc, "span", "state state-" + state.key, state.label);
      if (state.detail) {
        badge.title = state.detail;
      }
      root.appendChild(badge);
    });
  }

  function renderProjection(root, projection, doc) {
    clear(root);
    if (!projection || projection.state === "error" || projection.state === "unavailable") {
      appendEmpty(root, doc, projection && projection.error ? projection.error : "Recovery projection unavailable.");
      return;
    }

    var banner = node(doc, "div", "projection-banner", "PROPOSED — NOT APPLIED");
    root.appendChild(banner);

    var counts = projection.operationCounts || {};
    var summary = node(doc, "div", "projection-summary");
    [
      ["Tables affected", projection.tables.length ? projection.tables.join(", ") : "Not reported"],
      ["Comparison rows", String(projection.rowCount)],
      ["INSERT", counts.INSERT === null ? "Unavailable" : String(counts.INSERT)],
      ["UPDATE", counts.UPDATE === null ? "Unavailable" : String(counts.UPDATE)],
      ["DELETE", counts.DELETE === null ? "Unavailable" : String(counts.DELETE)],
      ["Dry run", projection.validation && projection.validation.dry_run_ok === true ? "PASSED" :
        projection.validation && projection.validation.dry_run_ok === false ? "FAILED" : "Unavailable"],
      ["Conflicts", String(projection.conflicts.length)]
    ].forEach(function (pair) {
      var item = node(doc, "div", "summary-item");
      item.appendChild(node(doc, "span", "summary-label", pair[0]));
      item.appendChild(node(doc, "strong", "summary-value", pair[1]));
      summary.appendChild(item);
    });
    root.appendChild(summary);

    if (projection.sampleTruncated) {
      root.appendChild(node(doc, "div", "notice", "Showing a bounded sample of the backend rows; counts above cover the full plan."));
    }
    if (projection.deleteSemantics) {
      root.appendChild(node(doc, "div", "notice", projection.deleteSemantics));
    }
    projection.conflicts.forEach(function (conflict) {
      var detail = conflict && typeof conflict.detail === "string" ? conflict.detail : "Conflict details unavailable";
      root.appendChild(node(doc, "div", "notice notice-warn", "Conflict: " + detail));
    });

    if (!projection.rows.length) {
      appendEmpty(root, doc, "No per-record comparison data was reported by the backend.");
      return;
    }

    var table = doc.createElement("table");
    table.className = "diff-table";
    var head = doc.createElement("thead");
    var headRow = doc.createElement("tr");
    ["Operation", "Table", "Record / key", "Field", "Original", "Proposed", "Actual recovered"].forEach(function (title) {
      headRow.appendChild(node(doc, "th", null, title));
    });
    head.appendChild(headRow);
    table.appendChild(head);

    var body = doc.createElement("tbody");
    projection.rows.forEach(function (row) {
      var tr = doc.createElement("tr");
      tr.className = "diff-row diff-" + row.operation.toLowerCase();
      var operation = node(doc, "span", "operation operation-" + row.operation.toLowerCase(),
        "[" + row.operation + "]");
      var opCell = doc.createElement("td");
      opCell.appendChild(operation);
      tr.appendChild(opCell);
      tr.appendChild(node(doc, "td", "mono", row.table));
      tr.appendChild(node(doc, "td", "mono", row.key));
      var fieldCell = node(doc, "td", "mono", row.field);
      if (row.note) {
        fieldCell.appendChild(node(doc, "div", "row-note", row.note));
      }
      tr.appendChild(fieldCell);
      tr.appendChild(valueCell(doc, row.before));
      tr.appendChild(valueCell(doc, row.after));
      if (projection.actualAvailable) {
        tr.appendChild(valueCell(doc, row.actual));
      } else {
        tr.appendChild(node(doc, "td", "value value-unavailable", "Not executed — unavailable"));
      }
      body.appendChild(tr);
    });
    table.appendChild(body);
    root.appendChild(table);

    if (projection.undone) {
      root.appendChild(node(doc, "div", "notice notice-warn",
        "Actual values were observed immediately after apply; the database has since been undone."));
    }
  }

  function timestampText(timestamp) {
    if (typeof timestamp !== "number" || !Number.isFinite(timestamp)) {
      return "timestamp unavailable";
    }
    var date = new Date(timestamp * 1000);
    return Number.isNaN(date.getTime()) ? "timestamp unavailable" : date.toISOString();
  }

  function renderLifecycle(root, events, doc) {
    clear(root);
    if (!Array.isArray(events) || events.length === 0) {
      appendEmpty(root, doc, "No lifecycle events have been reported for this session.");
      return;
    }
    var list = doc.createElement("ol");
    list.className = "timeline";
    events.forEach(function (event) {
      var item = doc.createElement("li");
      item.className = "timeline-item timeline-" + event.status;
      if (item.setAttribute) {
        item.setAttribute("data-event-id", event.id);
      }
      var header = node(doc, "div", "timeline-header");
      header.appendChild(node(doc, "span", "event-name", event.name));
      header.appendChild(node(doc, "span", "event-status", "[" + event.status.toUpperCase() + "]"));
      header.appendChild(node(doc, "time", "event-time", timestampText(event.timestamp)));
      item.appendChild(header);
      item.appendChild(node(doc, "div", "event-id", "event #" + event.id));
      var details = event.details;
      if (details !== null && details !== undefined &&
          !(typeof details === "object" && Object.keys(details).length === 0)) {
        var rendered = typeof details === "string" ? details : JSON.stringify(details);
        item.appendChild(node(doc, "div", "event-details", rendered || "no details"));
      }
      list.appendChild(item);
    });
    root.appendChild(list);
  }

  function renderVerification(root, verification, doc) {
    clear(root);
    if (!verification) {
      appendEmpty(root, doc, "Verification unavailable.");
      return;
    }
    var badge = node(doc, "span", "verification verification-" + verification.state, verification.label);
    root.appendChild(badge);
    if (verification.message) {
      root.appendChild(node(doc, "p", "verification-message", verification.message));
    }
    if (verification.method) {
      root.appendChild(node(doc, "p", "verification-method", verification.method));
    }

    var checksum = verification.checksum || {status: "unavailable"};
    var checksumText = "Checksum result: " + checksum.status;
    if (checksum.expected !== undefined && checksum.actual !== undefined) {
      checksumText += " | expected: " + JSON.stringify(checksum.expected) +
        " | actual: " + JSON.stringify(checksum.actual);
    } else if (checksum.reason) {
      checksumText += " — " + checksum.reason;
    }
    root.appendChild(node(doc, "p", "checksum-status", checksumText));

    if (verification.completedAt !== null) {
      root.appendChild(node(doc, "p", "verification-time", "Completed: " + timestampText(verification.completedAt)));
    }
    if (!verification.checks.length) {
      appendEmpty(root, doc, "No verification checks were reported.");
      return;
    }
    var list = doc.createElement("ul");
    list.className = "verification-checks";
    verification.checks.forEach(function (check) {
      var item = node(doc, "li", check.ok ? "check check-ok" : "check check-failed",
        (check.ok ? "PASS" : "FAIL") + " — " + (check.name || "unnamed check"));
      if (check.detail) {
        item.appendChild(node(doc, "span", "check-detail", " · " + check.detail));
      }
      list.appendChild(item);
    });
    root.appendChild(list);
  }

  function renderUndo(root, undo, doc) {
    clear(root);
    if (!undo) {
      appendEmpty(root, doc, "Undo status unavailable.");
      return;
    }
    root.appendChild(node(doc, "span", "undo undo-" + undo.state, undo.label));
    if (undo.detail) {
      root.appendChild(node(doc, "p", "undo-detail", undo.detail));
    }
    if (undo.completedAt !== null) {
      root.appendChild(node(doc, "p", "undo-time", "Completed: " + timestampText(undo.completedAt)));
    }
    if (undo.available) {
      root.appendChild(node(doc, "p", "undo-note",
        "Undo is permitted by the backend only while the applied session is active."));
    }
  }

  return {
    clear: clear,
    renderStatus: renderStatus,
    renderProjection: renderProjection,
    renderLifecycle: renderLifecycle,
    renderVerification: renderVerification,
    renderUndo: renderUndo
  };
});
