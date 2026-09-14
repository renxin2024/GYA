import tempfile
import unittest
from pathlib import Path
from main import Store, proposal_hash


class DurableResumeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); root = Path(self.tmp.name)
        self.store, self.out = Store(root / "runs.db", root / "draft.txt"), root / "draft.txt"
        self.run = "run-1"; self.store.start(self.run)
        self.digest = self.store.show(self.run)["proposal_hash"]

    def tearDown(self): self.tmp.cleanup()
    def test_approval_then_cross_process_resume_is_idempotent(self):
        self.store.decide(self.run, "approve", self.digest)
        second_process = Store(self.store.db, self.out)
        self.assertEqual("executed", second_process.resume(self.run)); self.assertEqual("already_completed", second_process.resume(self.run))
        self.assertEqual("approved technical brief", self.out.read_text())
        self.assertEqual(1, sum(e["event"] == "action_executed" for e in second_process.show(self.run)["trace"]))
        self.assertEqual(1, sum(e["event"] == "action_replayed" for e in second_process.show(self.run)["trace"]))
    def test_crash_after_file_creation_is_recovered_without_rewrite(self):
        self.store.decide(self.run, "approve", self.digest)
        with self.assertRaisesRegex(RuntimeError, "simulated_crash_after_action"):
            self.store.resume(self.run, fail_after_action=True)
        before = self.out.stat().st_mtime_ns
        second_process = Store(self.store.db, self.out)
        self.assertEqual("recovered", second_process.resume(self.run))
        self.assertEqual(before, self.out.stat().st_mtime_ns)
        self.assertEqual(1, sum(e["event"] == "action_recovered" for e in second_process.show(self.run)["trace"]))
    def test_unapproved_resume_cannot_write(self):
        with self.assertRaisesRegex(ValueError, "approval_required"): self.store.resume(self.run)
        self.assertFalse(self.out.exists())
    def test_tampered_proposal_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "proposal_hash_mismatch"): self.store.decide(self.run, "approve", proposal_hash("write_draft", {"content": "tampered"}, str(self.out)))
        self.assertFalse(self.out.exists())
    def test_post_approval_storage_tampering_is_rejected(self):
        self.store.decide(self.run, "approve", self.digest)
        tampered_args = '{"content":"tampered after approval"}'
        tampered_hash = proposal_hash("write_draft", {"content": "tampered after approval"}, str(self.out))
        self.store.conn.execute("UPDATE runs SET args=?, proposal_hash=? WHERE run_id=?", (tampered_args, tampered_hash, self.run))
        self.store.conn.commit()
        with self.assertRaisesRegex(ValueError, "proposal_hash_mismatch"):
            self.store.resume(self.run)
        self.assertFalse(self.out.exists())
    def test_post_approval_request_replacement_is_rejected(self):
        self.store.decide(self.run, "approve", self.digest)
        self.store.conn.execute("UPDATE runs SET request_id=? WHERE run_id=?", ("approval:replacement", self.run))
        self.store.conn.commit()
        with self.assertRaisesRegex(ValueError, "approval_request_mismatch"):
            self.store.resume(self.run)
        self.assertFalse(self.out.exists())
    def test_existing_different_output_is_not_overwritten(self):
        self.store.decide(self.run, "approve", self.digest)
        self.out.write_text("belongs to another operation", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "output_conflict"):
            self.store.resume(self.run)
        self.assertEqual("belongs to another operation", self.out.read_text(encoding="utf-8"))
    def test_repeated_decision_is_rejected(self):
        self.store.decide(self.run, "reject", self.digest)
        with self.assertRaisesRegex(ValueError, "approval_not_pending"): self.store.decide(self.run, "approve", self.digest)
        with self.assertRaisesRegex(ValueError, "approval_rejected"): self.store.resume(self.run)
    def test_post_approval_output_swap_is_rejected(self):
        self.store.decide(self.run, "approve", self.digest)
        # 恢复时换一个输出路径，等于篡改副作用目标
        other_output = self.out.parent / "other.txt"
        second_process = Store(self.store.db, other_output)
        with self.assertRaisesRegex(ValueError, "output_mismatch"):
            second_process.resume(self.run)
        self.assertFalse(other_output.exists())
        self.assertFalse(self.out.exists())
    def test_cross_language_canonical_hash_contract(self):
        # 两端对同一个 action+args+output 组合算出相同 hash（固定 output 作契约锚点）
        self.assertEqual(
            "2bba1bb36ae552812b4b9e0d730249a3447adfc3ed100e0f4d92e3a8c28e7573",
            proposal_hash("write_draft", {"content": "approved technical brief"}, "/tmp/c12-draft.txt"),
        )


if __name__ == "__main__": unittest.main()
