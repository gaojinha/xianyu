import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import reply_server
from app.db_manager import DBManager
from app.product_automation import ProductAutomationService


class DashboardOperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = DBManager(os.path.join(self.temp_dir.name, "dashboard.db"))
        self.service = ProductAutomationService(self.manager)
        self.manager.conn.executemany(
            "INSERT INTO users (id, username, email, password_hash) VALUES (?, ?, ?, 'hash')",
            [
                (301, "dashboard-owner", "dashboard@example.test"),
                (302, "other-owner", "other-dashboard@example.test"),
            ],
        )
        self.manager.conn.executemany(
            "INSERT INTO cookies (id, value, user_id) VALUES (?, 'cookie', ?)",
            [("dashboard-account", 301), ("other-account", 302)],
        )
        channel_id = self.manager.create_notification_channel(
            "dashboard-channel", "webhook", "{}", user_id=301
        )
        self.manager.add_notification_delivery_log(
            "dashboard-account",
            channel_id,
            "unknown",
            event_type="buyer_message",
            request_id="safe-id",
        )
        self.manager.conn.execute(
            """
            INSERT INTO auto_delivery_runs (user_id, cookie_id, order_id, status, error_summary)
            VALUES (301, 'dashboard-account', 'order-safe', 'needs_review', 'inventory check')
            """
        )
        self.manager.conn.execute(
            """
            INSERT INTO auto_delivery_runs (user_id, cookie_id, order_id, status)
            VALUES (302, 'other-account', 'other-order', 'failed')
            """
        )
        self.manager.conn.execute(
            """
            INSERT INTO automation_task_runs (
                user_id, cookie_id, task_type, failed_count, summary
            ) VALUES (301, 'dashboard-account', 'material_filter', 1, 'one row failed')
            """
        )
        self.manager.conn.execute(
            """
            INSERT INTO auto_reply_message_logs (
                cookie_id, item_id, process_status, reply_strategy, send_status,
                decision_reason
            ) VALUES (
                'dashboard-account', 'item-safe', 'success', 'ai', 'unknown',
                'model send outcome uncertain'
            )
            """
        )
        self.manager.conn.commit()

        self.old_overrides = reply_server.app.dependency_overrides.copy()
        reply_server.app.dependency_overrides[reply_server.require_auth] = lambda: {
            "user_id": 301,
            "username": "dashboard-owner",
        }
        self.db_patch = patch("app.reply_server.db_manager", self.manager)
        self.db_patch.start()
        self.client = TestClient(reply_server.app)

    def tearDown(self):
        self.client.close()
        self.db_patch.stop()
        reply_server.app.dependency_overrides.clear()
        reply_server.app.dependency_overrides.update(self.old_overrides)
        self.manager.close()
        self.temp_dir.cleanup()

    def test_dashboard_returns_owner_scoped_metrics_and_traceable_records(self):
        response = self.client.get("/dashboard/operations")

        self.assertEqual(200, response.status_code, response.text)
        data = response.json()
        self.assertEqual(7, data["period_days"])
        self.assertEqual(1, data["delivery_runs"]["needs_review"])
        self.assertEqual(1, data["notification_deliveries"]["unknown"])
        self.assertEqual(1, data["automation_runs"]["failed"])
        self.assertEqual(1, data["ai_replies"]["uncertain"])
        self.assertTrue(data["generated_at"])
        records = data["recent_records"]
        self.assertEqual(
            {"order-safe", "buyer_message", "material_filter", "item-safe"},
            {record["reference"] for record in records},
        )
        self.assertTrue(all(record["cookie_id"] != "other-account" for record in records))
        ai_record = next(record for record in records if record["kind"] == "ai_reply")
        self.assertEqual("item-safe", ai_record["reference"])
        self.assertEqual("unknown", ai_record["status"])

    def test_health_includes_release_metadata(self):
        with patch.dict(os.environ, {"APP_BUILD_REVISION": "abc123def456"}), patch.object(
            reply_server.cookie_manager, "manager", object()
        ):
            response = self.client.get("/health")

        self.assertEqual(200, response.status_code, response.text)
        self.assertTrue(response.json()["version"])
        self.assertEqual("abc123def456", response.json()["revision"])


if __name__ == "__main__":
    unittest.main()
