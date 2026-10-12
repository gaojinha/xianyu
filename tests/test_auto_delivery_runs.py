import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from app.db_manager import DBManager


class AutoDeliveryRunTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = DBManager(os.path.join(self.temp_dir.name, "delivery-runs.db"))
        with self.db.lock:
            self.db.conn.executemany(
                """
                INSERT OR IGNORE INTO users (id, username, email, password_hash)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (1, "owner-1", "owner1@example.com", "hash"),
                    (2, "owner-2", "owner2@example.com", "hash"),
                ],
            )
            self.db.conn.executemany(
                "INSERT INTO cookies (id, value, user_id) VALUES (?, ?, ?)",
                [
                    ("seller-1", "cookie-value", 1),
                    ("seller-2", "cookie-value", 2),
                ],
            )
            self.db.conn.commit()

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_claim_is_durable_and_duplicate_events_are_not_reclaimed(self):
        claimed, run = self.db.claim_auto_delivery_run(
            "seller-1", "order-1", "item-1", "buyer-1", "chat-1"
        )

        self.assertTrue(claimed)
        self.assertEqual("processing", run["status"])
        self.assertEqual("claimed", run["current_step"])

        duplicate_claimed, duplicate = self.db.claim_auto_delivery_run(
            "seller-1", "order-1", "item-1", "buyer-1", "chat-1"
        )

        self.assertFalse(duplicate_claimed)
        self.assertEqual(run["id"], duplicate["id"])

    def test_concurrent_connections_only_claim_one_delivery(self):
        second_db = DBManager(self.db.db_path)
        barrier = threading.Barrier(2)

        def claim(manager):
            barrier.wait()
            return manager.claim_auto_delivery_run("seller-1", "concurrent-order")[0]

        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(claim, (self.db, second_db)))
        finally:
            second_db.close()

        self.assertEqual(1, sum(results))
        self.assertEqual(
            1,
            len(self.db.get_auto_delivery_runs(user_id=1, cookie_id="seller-1")),
        )

    def test_progress_and_manual_review_state_are_persisted(self):
        _, run = self.db.claim_auto_delivery_run(
            "seller-1",
            "order-2",
            trigger_name="manual_full_delivery",
            operator_reason="Buyer confirmed prior key failed; accessToken=private",
        )
        self.assertNotIn("private", run["operator_reason"])
        self.assertIn("Buyer confirmed prior key failed", run["operator_reason"])
        updated = self.db.update_auto_delivery_run(
            run["id"],
            status="needs_review",
            current_step="partial_delivery",
            expected_count=3,
            acquired_count=3,
            sent_count=1,
            error_summary="delivery acknowledgement uncertain accessToken=token-secret",
        )

        self.assertTrue(updated)
        listed = self.db.get_auto_delivery_runs(
            user_id=1, status="needs_review"
        )
        self.assertEqual(1, len(listed))
        self.assertEqual(3, listed[0]["expected_count"])
        self.assertEqual(1, listed[0]["sent_count"])
        self.assertEqual("partial_delivery", listed[0]["current_step"])
        self.assertEqual(run["operator_reason"], listed[0]["operator_reason"])
        self.assertIn("delivery acknowledgement uncertain", listed[0]["error_summary"])
        self.assertNotIn("token-secret", listed[0]["error_summary"])

    def test_only_unconsumed_failure_can_be_retried_automatically(self):
        _, run = self.db.claim_auto_delivery_run("seller-1", "order-retry")
        self.db.update_auto_delivery_run(
            run["id"],
            status="failed",
            current_step="content_unavailable",
            error_summary="no delivery rule matched",
        )

        retry_claimed, retry = self.db.claim_auto_delivery_run(
            "seller-1", "order-retry"
        )

        self.assertTrue(retry_claimed)
        self.assertEqual("processing", retry["status"])
        self.assertEqual(2, retry["attempt_count"])
        self.assertEqual("safe_retry_claimed", retry["current_step"])

        self.db.update_auto_delivery_run(
            retry["id"],
            status="failed",
            current_step="content_unavailable",
        )
        retry_claimed, retry = self.db.claim_auto_delivery_run(
            "seller-1", "order-retry"
        )
        self.assertTrue(retry_claimed)
        self.assertEqual(3, retry["attempt_count"])

        self.db.update_auto_delivery_run(
            retry["id"],
            status="failed",
            current_step="content_unavailable",
        )
        retry_claimed, exhausted = self.db.claim_auto_delivery_run(
            "seller-1", "order-retry"
        )
        self.assertFalse(retry_claimed)
        self.assertEqual(3, exhausted["attempt_count"])

        self.db.update_auto_delivery_run(
            retry["id"],
            status="needs_review",
            current_step="partial_delivery",
            acquired_count=1,
            sent_count=1,
        )
        manual_claimed, manual = self.db.claim_auto_delivery_run(
            "seller-1", "order-retry"
        )

        self.assertFalse(manual_claimed)
        self.assertEqual("needs_review", manual["status"])

    def test_manual_reconciliation_closes_run_without_reopening_delivery(self):
        _, run = self.db.claim_auto_delivery_run("seller-1", "order-reviewed")
        self.db.update_auto_delivery_run(
            run["id"],
            status="needs_review",
            current_step="partial_delivery",
            acquired_count=1,
            sent_count=1,
        )

        self.assertTrue(
            self.db.resolve_auto_delivery_run(
                run_id=run["id"],
                user_id=1,
                note="Verified buyer received the sent content",
            )
        )
        claimed_again, reviewed = self.db.claim_auto_delivery_run(
            "seller-1", "order-reviewed"
        )

        self.assertFalse(claimed_again)
        self.assertEqual("Verified buyer received the sent content", reviewed["resolution_note"])
        self.assertIsNotNone(reviewed["resolved_at"])
        self.assertFalse(
            self.db.resolve_auto_delivery_run(
                run_id=run["id"],
                user_id=2,
                note="wrong owner",
            )
        )

    def test_processing_run_requires_timeout_before_reconciliation(self):
        _, run = self.db.claim_auto_delivery_run("seller-1", "order-stalled")

        self.assertFalse(
            self.db.resolve_auto_delivery_run(
                run_id=run["id"],
                user_id=1,
                note="Still processing",
            )
        )
        self.db.conn.execute(
            """
            UPDATE auto_delivery_runs
            SET updated_at = datetime('now', '-31 minutes')
            WHERE id = ?
            """,
            (run["id"],),
        )
        self.db.conn.commit()

        self.assertTrue(
            self.db.resolve_auto_delivery_run(
                run_id=run["id"],
                user_id=1,
                note="Account was stopped and the order was manually checked",
            )
        )

    def test_different_trigger_cannot_redeliver_after_prior_content_was_sent(self):
        _, run = self.db.claim_auto_delivery_run("seller-1", "order-cross-trigger")
        self.db.update_auto_delivery_run(
            run["id"],
            status="completed",
            current_step="completed",
            acquired_count=1,
            sent_count=1,
        )

        claimed, prior_run = self.db.claim_auto_delivery_run(
            "seller-1",
            "order-cross-trigger",
            trigger_name="manual_full_delivery",
            operator_reason="Attempted manual follow-up",
        )

        self.assertFalse(claimed)
        self.assertEqual("paid_delivery", prior_run["trigger_name"])
        self.assertEqual("completed", prior_run["status"])

    def test_runs_are_filtered_by_owner_and_account(self):
        self.db.claim_auto_delivery_run("seller-1", "order-3")
        self.db.claim_auto_delivery_run("seller-2", "order-4")

        self.assertEqual([], self.db.get_auto_delivery_runs(user_id=2, cookie_id="seller-1"))
        owner_runs = self.db.get_auto_delivery_runs(user_id=1, cookie_id="seller-1")
        self.assertEqual(["order-3"], [run["order_id"] for run in owner_runs])

    def test_invalid_status_and_unknown_account_fail_explicitly(self):
        with self.assertRaises(ValueError):
            self.db.claim_auto_delivery_run("missing-account", "order-5")

        with self.assertRaises(ValueError):
            self.db.get_auto_delivery_runs(user_id=1, status="retry_automatically")


if __name__ == "__main__":
    unittest.main()
