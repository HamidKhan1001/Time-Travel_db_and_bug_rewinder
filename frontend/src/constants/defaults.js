/**
 * Pre-filled time-travel prompt for the demo. It names a rewind point, what to keep and that the bug
 * should be fixed, which is everything the backend's rule-based parser needs (no LLM key required).
 */
export const DEFAULT_PROMPT =
  'The warehouse sync wiped inventory while 3 orders came in. Take the business back to before the crash, keep the 3 orders, and fix the bug that caused it.'

/** Rows per page in the Audit log table (the design shows 5). */
export const AUDIT_PAGE_SIZE = 5
