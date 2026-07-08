# =============================================================================
# review.py — Mark the most recent forecast run as human-reviewed
# =============================================================================
# Usage:
#   python review.py
#   python review.py "Chun-Feng Pai"
#
# When a run raises flags, the audit log sets requires_review = true.
# After a person has checked the output, run this to record that the
# review happened, who did it, and when. This keeps the audit log as a
# living record of the human sign-off, not just the machine output.
# =============================================================================

import sys
import json
from datetime import datetime, timezone

from config import AUDIT_LOG


def mark_reviewed(reviewer):
    if not AUDIT_LOG.exists():
        print("No audit log found at {}".format(AUDIT_LOG))
        return

    lines = AUDIT_LOG.read_text(encoding="utf-8").strip().split("\n")
    if not lines or not lines[-1].strip():
        print("Audit log is empty.")
        return

    last = json.loads(lines[-1])

    if last.get("human_reviewed"):
        print("Latest run ({}) was already reviewed by {} at {}.".format(
            last.get("run_id", "?"),
            last.get("reviewed_by", "?"),
            last.get("reviewed_at", "?"),
        ))
        return

    last["human_reviewed"] = True
    last["reviewed_by"]    = reviewer
    last["reviewed_at"]    = datetime.now(timezone.utc).isoformat()
    lines[-1] = json.dumps(last)
    AUDIT_LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("Run {} marked as reviewed by {}.".format(last["run_id"], reviewer))
    if last.get("flags_raised"):
        print("Flags that were reviewed:")
        for flag in last["flags_raised"]:
            print("  - {}".format(flag))


if __name__ == "__main__":
    reviewer = sys.argv[1] if len(sys.argv) > 1 else "Finance reviewer"
    mark_reviewed(reviewer)
