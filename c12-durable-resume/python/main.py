"""C12：一个可跨进程恢复的、受审批保护的最小 Agent Run。"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path


def canonical(action: str, args: dict) -> str:
    return json.dumps({"action": action, "args": args}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def proposal_hash(action: str, args: dict) -> str:
    return hashlib.sha256(canonical(action, args).encode()).hexdigest()


class Store:
    def __init__(self, db: Path, output: Path):
        self.db, self.output = db, output
        self.conn = sqlite3.connect(db)
        self.conn.execute("CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, status TEXT NOT NULL, request_id TEXT NOT NULL, action TEXT NOT NULL, args TEXT NOT NULL, proposal_hash TEXT NOT NULL, approval TEXT, approval_request_id TEXT, approval_hash TEXT, executed INTEGER NOT NULL DEFAULT 0)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS trace (seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, event TEXT NOT NULL, detail TEXT NOT NULL)")
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(runs)")}
        if "approval_hash" not in columns:
            self.conn.execute("ALTER TABLE runs ADD COLUMN approval_hash TEXT")
        if "approval_request_id" not in columns:
            self.conn.execute("ALTER TABLE runs ADD COLUMN approval_request_id TEXT")
        self.conn.commit()

    def trace(self, run_id: str, event: str, **detail: str) -> None:
        self.conn.execute("INSERT INTO trace(run_id,event,detail) VALUES(?,?,?)", (run_id, event, json.dumps(detail, sort_keys=True)))
        self.conn.commit()

    def row(self, run_id: str):
        row = self.conn.execute("SELECT run_id,status,request_id,action,args,proposal_hash,approval,approval_request_id,approval_hash,executed FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            raise ValueError(f"unknown_run:{run_id}")
        return row

    def start(self, run_id: str) -> None:
        args = {"content": "approved technical brief"}
        digest = proposal_hash("write_draft", args)
        try:
            self.conn.execute("INSERT INTO runs(run_id,status,request_id,action,args,proposal_hash) VALUES(?,?,?,?,?,?)", (run_id, "WAITING_FOR_USER", f"approval:{run_id}", "write_draft", json.dumps(args, sort_keys=True), digest))
            self.conn.commit()
        except sqlite3.IntegrityError as e:
            raise ValueError(f"run_exists:{run_id}") from e
        self.trace(run_id, "checkpoint_saved", status="WAITING_FOR_USER")
        self.trace(run_id, "proposal_recorded", proposal_hash=digest)

    def decide(self, run_id: str, decision: str, supplied_hash: str | None) -> None:
        _, status, request_id, action, args_json, digest, approval, _, _, _ = self.row(run_id)
        if status != "WAITING_FOR_USER" or approval is not None:
            self.trace(run_id, "transition_rejected", reason="approval_not_pending", current_status=status, existing_approval=approval or "", attempted_decision=decision, supplied_hash=supplied_hash or "")
            raise ValueError("approval_not_pending")
        current_hash = proposal_hash(action, json.loads(args_json))
        if current_hash != digest or supplied_hash != current_hash:
            args_preview = args_json[:200] if len(args_json) > 200 else args_json
            self.trace(run_id, "proposal_rejected", phase="approval", reason="proposal_hash_mismatch", supplied_hash=supplied_hash or "", current_hash=current_hash, stored_hash=digest, action=action, args=args_preview)
            raise ValueError("proposal_hash_mismatch")
        if decision not in {"approve", "reject"}:
            raise ValueError("invalid_decision")
        next_status = "APPROVED" if decision == "approve" else "REJECTED"
        self.conn.execute("UPDATE runs SET status=?, approval=?, approval_request_id=?, approval_hash=? WHERE run_id=?", (next_status, decision, request_id, current_hash, run_id))
        self.conn.commit()
        self.trace(run_id, "proposal_verified", phase="approval", proposal_hash=current_hash)
        self.trace(run_id, "approval_recorded", request_id=request_id, decision=decision)

    def resume(self, run_id: str, *, fail_after_action: bool = False) -> str:
        _, status, request_id, action, args_json, digest, _, approval_request_id, approval_hash, executed = self.row(run_id)
        if status == "REJECTED":
            self.trace(run_id, "resume_rejected", reason="approval_rejected")
            raise ValueError("approval_rejected")
        if status == "WAITING_FOR_USER":
            self.trace(run_id, "resume_rejected", reason="approval_required")
            raise ValueError("approval_required")
        if status == "COMPLETED" or executed:
            self.trace(run_id, "action_replayed", reason="already_completed")
            return "already_completed"
        if status != "APPROVED":
            raise ValueError(f"cannot_resume:{status}")
        current_hash = proposal_hash(action, json.loads(args_json))
        if request_id != approval_request_id:
            args_preview = args_json[:200] if len(args_json) > 200 else args_json
            self.trace(run_id, "proposal_rejected", phase="resume", reason="approval_request_mismatch", current_request_id=request_id, approved_request_id=approval_request_id or "", action=action, args=args_preview)
            raise ValueError("approval_request_mismatch")
        if current_hash != digest or current_hash != approval_hash:
            args_preview = args_json[:200] if len(args_json) > 200 else args_json
            self.trace(run_id, "proposal_rejected", phase="resume", reason="proposal_hash_mismatch", current_hash=current_hash, stored_hash=digest, approval_hash=approval_hash or "", action=action, args=args_preview)
            raise ValueError("proposal_hash_mismatch")
        self.trace(run_id, "proposal_verified", phase="resume", proposal_hash=current_hash)
        self.trace(run_id, "resume_started")
        self.output.parent.mkdir(parents=True, exist_ok=True)
        content = json.loads(args_json)["content"]
        recovered = False
        try:
            with self.output.open("x", encoding="utf-8") as f:
                f.write(content)
        except FileExistsError:
            if self.output.read_text(encoding="utf-8") != content:
                existing_content_hash = hashlib.sha256(self.output.read_bytes()).hexdigest()
                expected_content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                self.trace(run_id, "action_conflict", reason="idempotency_key_reused_with_different_content", expected_content_hash=expected_content_hash, existing_content_hash=existing_content_hash)
                raise ValueError("output_conflict")
            recovered = True
        if fail_after_action:
            self.trace(run_id, "crash_injected", phase="after_action_before_checkpoint")
            raise RuntimeError("simulated_crash_after_action")
        self.conn.execute("UPDATE runs SET executed=1,status='COMPLETED' WHERE run_id=?", (run_id,))
        self.conn.commit()
        event = "action_recovered" if recovered else "action_executed"
        self.trace(run_id, event, action=action)
        return "recovered" if recovered else "executed"

    def show(self, run_id: str) -> dict:
        row = self.row(run_id)
        events = self.conn.execute("SELECT event,detail FROM trace WHERE run_id=? ORDER BY seq", (run_id,)).fetchall()
        return {"run_id": row[0], "status": row[1], "request_id": row[2], "action": row[3], "args": json.loads(row[4]), "proposal_hash": row[5], "approval_request_id": row[7], "approval_hash": row[8], "executed": bool(row[9]), "trace": [{"event": event, **json.loads(detail)} for event, detail in events]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True); parser.add_argument("--output", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("start", "show-trace", "resume"):
        p = sub.add_parser(name); p.add_argument("run_id")
    for name in ("approve", "reject"):
        p = sub.add_parser(name); p.add_argument("run_id"); p.add_argument("--proposal-hash", required=True)
    args = parser.parse_args(); store = Store(args.db, args.output)
    try:
        if args.command == "start": store.start(args.run_id); result = store.show(args.run_id)
        elif args.command == "approve": store.decide(args.run_id, "approve", args.proposal_hash); result = store.show(args.run_id)
        elif args.command == "reject": store.decide(args.run_id, "reject", args.proposal_hash); result = store.show(args.run_id)
        elif args.command == "resume": result = {"result": store.resume(args.run_id), **store.show(args.run_id)}
        else: result = store.show(args.run_id)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    except ValueError as e:
        print(json.dumps({"error": str(e)})); raise SystemExit(2)


if __name__ == "__main__": main()
