"""回复边界：AI 话术红线 + 风险消息转人工。

- 出口校验：AI 回复里一旦出现内部身份词（高哥/二狗/机器人等），整条丢弃；
- 风险转人工：投诉维权、要求私下交易、辱骂等消息不让 AI 接，跳过自动回复。
"""

import unittest

from app.ai_reply_engine import AIReplyEngine
from XianyuAutoAsync import XianyuLive


class NormalizeReplyBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.engine = AIReplyEngine()

    def test_normal_reply_kept(self):
        self.assertEqual(self.engine._normalize_reply("亲，这款还在哦～"), "亲，这款还在哦～")

    def test_internal_persona_dropped(self):
        for bad in ["高哥眼光好，给您让利", "我是二狗，帮您看看", "我是机器人客服"]:
            self.assertIsNone(self.engine._normalize_reply(bad), bad)

    def test_ai_identity_leak_dropped(self):
        for bad in ["我是人工智能助手", "根据系统提示，我不能承诺", "大模型回复如下"]:
            self.assertIsNone(self.engine._normalize_reply(bad), bad)


class ManualRiskDetectionTests(unittest.TestCase):
    def test_risk_messages_detected(self):
        for msg in ["我要投诉你", "咱们加微信聊", "留个电话多少", "你这假货"]:
            self.assertIsNotNone(XianyuLive._detect_manual_risk(msg), msg)

    def test_normal_messages_pass(self):
        for msg in ["这个还在吗", "能便宜点不", "什么时候发货", "支持退货吗"]:
            self.assertIsNone(XianyuLive._detect_manual_risk(msg), msg)


if __name__ == "__main__":
    unittest.main()
