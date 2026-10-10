"""本地 AI 网关的单元测试（不依赖真实 opencode）。

覆盖三块纯逻辑：
- 把 OpenAI 的 messages 拆成 opencode 要的 system + 对话文本；
- 从 opencode 消息响应里取正文；
- 组装标准 OpenAI 响应体（ai_reply_engine 依赖这个格式）。
以及凭据解析：环境变量优先、拿不到返回 None（走降级）。
"""

import os
import unittest
from unittest import mock

import app.local_ai_gateway as g


class FlattenMessagesTests(unittest.TestCase):
    def test_system_split_and_role_prefix(self):
        system, convo = g._flatten_messages([
            {"role": "system", "content": "你是客服"},
            {"role": "user", "content": "在吗"},
            {"role": "assistant", "content": "在的"},
            {"role": "user", "content": "多少钱"},
        ])
        self.assertEqual(system, "你是客服")
        self.assertEqual(convo, "买家：在吗\n卖家：在的\n买家：多少钱")

    def test_list_content_is_joined(self):
        _, convo = g._flatten_messages([
            {"role": "user", "content": [{"type": "text", "text": "你好"}, {"type": "text", "text": "老板"}]},
        ])
        self.assertEqual(convo, "买家：你好老板")

    def test_empty_messages(self):
        self.assertEqual(g._flatten_messages([]), ("", ""))


class ExtractTextTests(unittest.TestCase):
    def test_join_text_parts(self):
        msg = {"parts": [
            {"type": "text", "text": "在的，"},
            {"type": "tool", "text": "ignored"},
            {"type": "text", "text": "直接拍。"},
        ]}
        self.assertEqual(g._extract_text(msg), "在的，直接拍。")

    def test_raises_when_no_text(self):
        with self.assertRaises(RuntimeError):
            g._extract_text({"parts": [{"type": "tool"}]})


class OpenaiResponseTests(unittest.TestCase):
    def test_shape_matches_openai(self):
        resp = g._openai_response("你好", "deepseek-v4.1-flash")
        self.assertEqual(resp["object"], "chat.completion")
        self.assertEqual(resp["model"], "deepseek-v4.1-flash")
        self.assertEqual(resp["choices"][0]["message"]["content"], "你好")
        self.assertEqual(resp["choices"][0]["message"]["role"], "assistant")
        self.assertEqual(resp["choices"][0]["finish_reason"], "stop")


class CredentialTests(unittest.TestCase):
    def setUp(self):
        g._cred_cache.clear()
        g._cred_cache.update({"username": None, "password": None, "loaded": False})

    def test_env_credentials_used(self):
        with mock.patch.dict(os.environ, {
            "OPENCODE_SERVER_USERNAME": "opencode",
            "OPENCODE_SERVER_PASSWORD": "secret",
        }):
            self.assertEqual(g._opencode_credentials(), ("opencode", "secret"))

    def test_missing_returns_none(self):
        env = {k: v for k, v in os.environ.items() if k != "OPENCODE_SERVER_PASSWORD"}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(g, "_scan_proc_for_credentials", return_value=None):
                self.assertIsNone(g._opencode_credentials())


if __name__ == "__main__":
    unittest.main()
