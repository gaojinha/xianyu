import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.logistics_quote import (
    _notify_quote_parse_failure,
    create_logistics_quote_router,
)
from app.notification_events import resolve_event_type


class LogisticsQuoteNotificationTests(unittest.TestCase):
    def test_password_login_failure_maps_to_its_subscription(self):
        self.assertEqual(resolve_event_type("password_login_failed"), "login_failed")

    def test_quote_parse_failure_is_filtered_and_audited(self):
        db = Mock()
        db.get_account_notifications.return_value = [{
            "id": 8,
            "channel_id": 3,
            "enabled": True,
            "channel_type": "webhook",
            "channel_config": '{"webhook_url":"https://example.test/hook"}',
        }]
        sender = Mock()
        sender.send = AsyncMock()

        with patch(
            "app.routers.logistics_quote.NotificationSender",
            return_value=sender,
        ):
            asyncio.run(
                _notify_quote_parse_failure(
                    db, cookie_id="account-1", user_id=7
                )
            )

        db.get_account_notifications.assert_called_once_with(
            "account-1", user_id=7, event_type="logistics_quote"
        )
        db.add_notification_delivery_log.assert_called_once()
        db.update_notification_delivery_log.assert_called_once_with(
            db.add_notification_delivery_log.return_value, 7, "success"
        )
        self.assertEqual(
            sender.send.call_args.args[2],
            "物流报价文本未能识别出有效的首重/续重价格，请检查报价内容并转人工核对。",
        )

    def test_audit_failure_prevents_quote_notification_send(self):
        db = Mock()
        db.get_account_notifications.return_value = [{
            "id": 8,
            "channel_id": 3,
            "enabled": True,
            "channel_type": "webhook",
            "channel_config": "{}",
        }]
        db.add_notification_delivery_log.side_effect = RuntimeError("database error")
        sender = Mock()
        sender.send = AsyncMock()

        with patch(
            "app.routers.logistics_quote.NotificationSender",
            return_value=sender,
        ):
            asyncio.run(
                _notify_quote_parse_failure(
                    db, cookie_id="account-1", user_id=7
                )
            )

        sender.send.assert_not_awaited()

    def test_parse_endpoint_notifies_only_for_owned_account(self):
        db = Mock()
        db.get_cookie_owner_user.return_value = 7
        db.get_account_notifications.return_value = []
        get_current_user = lambda: {"id": 7}
        app = FastAPI()
        app.include_router(create_logistics_quote_router(get_current_user, db))

        with TestClient(app) as client:
            response = client.post(
                "/logistics-quote/parse",
                json={"text": "无法识别的报价", "cookie_id": "account-1"},
            )

        self.assertEqual(response.status_code, 422)
        db.get_account_notifications.assert_called_once_with(
            "account-1", user_id=7, event_type="logistics_quote"
        )

        db.get_cookie_owner_user.return_value = 9
        with TestClient(app) as client:
            response = client.post(
                "/logistics-quote/parse",
                json={"text": "无法识别的报价", "cookie_id": "other-account"},
            )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(db.get_account_notifications.call_count, 1)


if __name__ == "__main__":
    unittest.main()
