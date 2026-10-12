import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.services.notification_sender import (
    NotificationProviderRejected,
    NotificationSendTimeout,
)
from XianyuAutoAsync import XianyuLive


class RuntimeNotificationEventTests(unittest.TestCase):
    def setUp(self):
        self.live = XianyuLive.__new__(XianyuLive)
        self.live.cookie_id = "account-1"
        self.live.user_id = 7
        self.notifications = [{
            "id": 12,
            "channel_id": 4,
            "enabled": True,
            "channel_type": "webhook",
            "channel_config": '{"webhook_url":"https://example.test/hook"}',
        }]
        self.db_patcher = patch("app.db_manager.db_manager")
        self.db = self.db_patcher.start()
        self.addCleanup(self.db_patcher.stop)
        self.db.get_cookie_owner_user.return_value = 7
        self.db.add_notification_delivery_log.return_value = 22
        self.sender = Mock()
        self.sender.send = AsyncMock()
        self.sender_patcher = patch(
            "app.services.notification_sender.NotificationSender",
            return_value=self.sender,
        )
        self.sender_patcher.start()
        self.addCleanup(self.sender_patcher.stop)

    def run_async(self, awaitable):
        return asyncio.run(awaitable)

    def test_system_notification_filters_subscriptions_and_audits_success(self):
        self.db.get_account_notifications.return_value = self.notifications

        sent = self.run_async(
            self.live.send_system_notification("订单发货超时", "delivery_timeout")
        )

        self.assertEqual(sent, 1)
        self.db.get_account_notifications.assert_called_once_with(
            "account-1", event_type="delivery_timeout"
        )
        self.db.add_notification_delivery_log.assert_called_once()
        self.db.update_notification_delivery_log.assert_called_once_with(
            22, 7, "success"
        )

    def test_delivery_outcomes_use_distinct_subscriptions(self):
        self.db.get_account_notifications.return_value = self.notifications

        for result, expected_event in (
            ("发货成功", "delivery_success"),
            ("确认发货失败，请人工处理", "delivery_confirm_failed"),
            ("未找到匹配的发货规则", "delivery_failed"),
        ):
            with self.subTest(event=expected_event):
                awaitable = self.live.send_delivery_failure_notification(
                    "buyer", "buyer-id", "item-1", result
                )
                self.run_async(awaitable)
                self.assertEqual(
                    self.db.get_account_notifications.call_args.kwargs["event_type"],
                    expected_event,
                )
                self.db.get_account_notifications.reset_mock()

    def test_password_login_failure_is_filtered_and_audited(self):
        self.live.last_notification_time = {}
        self.live.notification_cooldown = 60
        self.live.token_refresh_notification_cooldown = 3600
        self.db.get_account_notifications.return_value = self.notifications

        self.run_async(
            self.live.send_token_refresh_notification(
                "账号密码登录失败，未能获取有效Cookie。",
                "password_login_failed",
            )
        )

        self.db.get_account_notifications.assert_called_once_with(
            "account-1", event_type="login_failed"
        )
        self.db.add_notification_delivery_log.assert_called_once()
        self.db.update_notification_delivery_log.assert_called_once_with(
            22, 7, "success"
        )

    def test_audit_creation_failure_prevents_notification_send(self):
        self.db.add_notification_delivery_log.side_effect = RuntimeError("db offline")

        sent = self.run_async(
            self.live._send_audited_notification_event(
                self.notifications, "test message", "buyer_message"
            )
        )

        self.assertEqual(sent, 0)
        self.sender.send.assert_not_awaited()
        self.db.update_notification_delivery_log.assert_not_called()

    def test_provider_rejection_is_failed_and_timeout_is_unknown(self):
        for error, expected_status in (
            (NotificationProviderRejected(503), "failed"),
            (NotificationSendTimeout(), "unknown"),
        ):
            with self.subTest(expected_status=expected_status):
                self.db.add_notification_delivery_log.reset_mock()
                self.db.update_notification_delivery_log.reset_mock()
                self.sender.send.reset_mock()
                self.sender.send.side_effect = error

                self.run_async(
                    self.live._send_audited_notification_event(
                        self.notifications, "test message", "buyer_message"
                    )
                )

                self.assertEqual(
                    self.db.update_notification_delivery_log.call_args.args[:3],
                    (22, 7, expected_status),
                )


if __name__ == "__main__":
    unittest.main()
