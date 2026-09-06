"""Validate fresh phase output and archive source evidence; no model/network calls."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path

from execution_evidence import fingerprint
from market_session import now_central
from tool_evidence_hook import connect, put


def validate_b(before, after):
    if not after.startswith(before):
        raise ValueError("Phase B rewrote historical trade records")
    if before and not before.endswith(b"\n"):
        raise ValueError("Existing trade log has no final newline")
    rows = [json.loads(line) for line in after[len(before):].decode("utf-8").splitlines() if line.strip()]
    if not rows or rows[-1].get("stage") != "cycle_summary" or sum(r.get("stage") == "cycle_summary" for r in rows) != 1:
        raise ValueError("Phase B must append exactly one new final cycle_summary")
    return rows


def finalize(root, phase, before, run_id, now):
    if phase == "A":
        raw = (root / "pending_proposals.jsonl").read_bytes()
        folder = root / "logs/phase-a-snapshots"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (now.strftime("%Y%m%d-%H%M%S") + "-" + hashlib.sha256(raw).hexdigest()[:16] + ".jsonl")
        if not path.exists():
            path.write_bytes(raw)
        return {"phase_a_snapshot": str(path)}
    rows = validate_b(before.read_bytes(), (root / "trade_log.jsonl").read_bytes())
    if any(r.get("date") != now.date().isoformat() for r in rows):
        raise ValueError("Phase B appended a stale or mismatched date")
    if rows[-1].get("mode") not in ("dry_run", "live"):
        raise ValueError("invalid completed cycle mode")
    with closing(connect(root / "logs/runtime-evidence.sqlite")) as db, db:
        put(db, fingerprint([run_id, "complete"]), fingerprint(run_id), "phase_b_completed", "", now,
            {"mode": rows[-1]["mode"], "new_record_count": len(rows)})
    return {"phase_b_new_records": len(rows)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=["A", "B"], required=True)
    parser.add_argument("--before", type=Path)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    print(json.dumps(finalize(Path(__file__).resolve().parent.parent, args.phase, args.before, args.run_id, now_central())))
