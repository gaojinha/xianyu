import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.db_manager import DBManager
from app.product_automation import ProductAutomationService
from app import reply_server


class ProductAutomationBulkApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = DBManager(os.path.join(self.temp_dir.name, "bulk.db"))
        self.manager.conn.execute(
            """
            INSERT INTO users (id, username, email, password_hash)
            VALUES (91234, 'bulk-owner', 'bulk-owner@example.test', 'hash')
            """
        )
        self.manager.conn.execute(
            "INSERT INTO cookies (id, value, user_id) VALUES ('bulk-account', 'cookie', 91234)"
        )
        self.manager.conn.commit()
        self.service = ProductAutomationService(self.manager)
        self.db_patch = patch("app.db_manager.db_manager", self.manager)
        self.service_patch = patch.object(reply_server, "product_automation", self.service)
        self.db_patch.start()
        self.service_patch.start()
        self.old_overrides = reply_server.app.dependency_overrides.copy()
        reply_server.app.dependency_overrides[reply_server.get_current_user] = lambda: {
            "user_id": 91234,
            "username": "bulk-owner",
        }
        self.client = TestClient(reply_server.app)

    def tearDown(self):
        self.client.close()
        reply_server.app.dependency_overrides.clear()
        reply_server.app.dependency_overrides.update(self.old_overrides)
        self.service_patch.stop()
        self.db_patch.stop()
        self.manager.close()
        self.temp_dir.cleanup()

    @staticmethod
    def _csv():
        return (
            "source_item_id,title,description,category,price,images,source_url,delivery_content\n"
            "bulk-1,Test item,Description,Digital,9.9,https://example.test/image.jpg,"
            "https://example.test/item,delivery\n"
        )

    def test_preflight_and_explicit_import_create_local_draft_without_publishing(self):
        response = self.client.post(
            "/product-automation/bulk/preflight",
            data={"cookie_id": "bulk-account"},
            files={"upload_file": ("items.csv", self._csv().encode(), "text/csv")},
        )

        self.assertEqual(200, response.status_code, response.text)
        result = response.json()["data"]
        self.assertEqual(1, result["valid_count"])
        imported = self.client.post(
            f"/product-automation/bulk/preflight/{result['run_id']}/import",
            json={"confirmed": True},
        )

        self.assertEqual(200, imported.status_code, imported.text)
        self.assertEqual(1, imported.json()["data"]["imported_count"])
        material = self.service.list_materials(91234)[0]
        self.assertEqual("draft", material["publish_status"])
        self.assertEqual("", material["published_item_id"])
        repeated = self.client.post(
            f"/product-automation/bulk/preflight/{result['run_id']}/import",
            json={"confirmed": True},
        )
        self.assertEqual(400, repeated.status_code)

    def test_rejects_unsupported_encoding_headers_and_unconfirmed_import(self):
        wrong_extension = self.client.post(
            "/product-automation/bulk/preflight",
            data={"cookie_id": "bulk-account"},
            files={"upload_file": ("items.xlsx", b"book", "application/octet-stream")},
        )
        invalid_headers = self.client.post(
            "/product-automation/bulk/preflight",
            data={"cookie_id": "bulk-account"},
            files={"upload_file": ("items.csv", b"wrong,headers\n1,2\n", "text/csv")},
        )
        invalid_encoding = self.client.post(
            "/product-automation/bulk/preflight",
            data={"cookie_id": "bulk-account"},
            files={"upload_file": ("items.csv", b"\xff\xfe", "text/csv")},
        )

        self.assertEqual(400, wrong_extension.status_code)
        self.assertEqual(400, invalid_headers.status_code)
        self.assertEqual(400, invalid_encoding.status_code)
        result = self.client.post(
            "/product-automation/bulk/preflight",
            data={"cookie_id": "bulk-account"},
            files={"upload_file": ("items.csv", self._csv().encode(), "text/csv")},
        ).json()["data"]
        unconfirmed = self.client.post(
            f"/product-automation/bulk/preflight/{result['run_id']}/import",
            json={"confirmed": False},
        )
        self.assertEqual(400, unconfirmed.status_code)
        self.assertEqual([], self.service.list_materials(91234))

    def test_accepts_tsv_and_enforces_file_and_row_limits(self):
        tsv = (
            "source_item_id\ttitle\tdescription\tcategory\tprice\timages\tsource_url\tdelivery_content\n"
            "tsv-1\tTest item\tDescription\tDigital\t9.9\t\thttps://example.test/item\t"
        )
        accepted = self.client.post(
            "/product-automation/bulk/preflight",
            data={"cookie_id": "bulk-account"},
            files={"upload_file": ("items.tsv", tsv.encode(), "text/tab-separated-values")},
        )
        too_many_rows = self.client.post(
            "/product-automation/bulk/preflight",
            data={"cookie_id": "bulk-account"},
            files={
                "upload_file": (
                    "items.csv",
                    (self._csv() + (self._csv().splitlines()[1] + "\n") * 200).encode(),
                    "text/csv",
                )
            },
        )
        oversized = self.client.post(
            "/product-automation/bulk/preflight",
            data={"cookie_id": "bulk-account"},
            files={"upload_file": ("items.csv", b"x" * (5 * 1024 * 1024 + 1), "text/csv")},
        )

        self.assertEqual(200, accepted.status_code, accepted.text)
        self.assertEqual(1, accepted.json()["data"]["valid_count"])
        self.assertEqual(400, too_many_rows.status_code)
        self.assertEqual(400, oversized.status_code)


if __name__ == "__main__":
    unittest.main()
