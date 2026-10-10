"""自动回复的"只回本店商品"闸门。

回归的故障：系统分不清账号在会话里是买家还是卖家 —— 收到消息一律当买家咨询。
用户拿卖家号去别人店里买东西时，对方卖家发来的话被误当成买家咨询，自动回复
就去插话。这里用商品归属兜底：商品不在本店商品库，就判定为买家咨询，不回复。
"""

import unittest
from unittest import mock

import app.db_manager as dbm
from XianyuAutoAsync import XianyuLive


class _FakeSelf:
    cookie_id = "acc-1"

    @staticmethod
    def _safe_str(exc):
        return str(exc)


class OwnItemGateTests(unittest.TestCase):
    def _call(self, item_id, owned):
        with mock.patch.object(dbm.db_manager, "is_own_item", return_value=owned) as m:
            result = XianyuLive._is_own_item_consultation(_FakeSelf(), item_id)
        return result, m

    def test_own_item_is_replied(self):
        result, _ = self._call("1087712352879", True)
        self.assertTrue(result)

    def test_foreign_item_is_skipped(self):
        # 商品不属于本店 —— 说明在当买家，不能插话
        result, _ = self._call("9999999999999", False)
        self.assertFalse(result)

    def test_missing_or_placeholder_item_is_skipped(self):
        # 归属不明时保守跳过，宁可漏回也不插话
        self.assertFalse(XianyuLive._is_own_item_consultation(_FakeSelf(), ""))
        self.assertFalse(XianyuLive._is_own_item_consultation(_FakeSelf(), None))
        self.assertFalse(XianyuLive._is_own_item_consultation(_FakeSelf(), "auto_123_456"))


if __name__ == "__main__":
    unittest.main()
