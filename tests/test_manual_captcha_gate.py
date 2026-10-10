"""人工验证会话的准入判定：冷却结束后仍能进入能回写 Cookie 的入口。

回归的缺口：本地熔断（risk_control）是进程内状态，最长 20 分钟就自动过期，
而闲鱼侧要求过滑块要真正过掉才解除。原入口只卡本地熔断，冷却一结束用户就
被 409 拒绝，前端只能引导去外部标签页 —— 那里过的 Cookie 留在用户浏览器里，
同步不回服务端。这里验证放宽后的判定：本地熔断之外，新鲜的滑块事件也放行。
"""

import os
import unittest
from datetime import datetime, timedelta
from unittest import mock

from app.reply_server import _fresh_verification_type


def _log(
    event_type='slider_captcha',
    description='slider_captcha action=captcha',
    minutes_ago=1,
    processing_result=None,
    error_message=None,
):
    created = datetime.now() - timedelta(minutes=minutes_ago)
    return {
        'event_type': event_type,
        'event_description': description,
        'processing_result': processing_result,
        'error_message': error_message,
        'created_at': created.strftime('%Y-%m-%d %H:%M:%S'),
    }


class FreshVerificationTypeTests(unittest.TestCase):
    def _call(self, logs):
        with mock.patch(
            'app.db_manager.db_manager.get_risk_control_logs',
            return_value=logs,
        ):
            return _fresh_verification_type('acc-1', 1)

    def test_fresh_slider_event_is_slider(self):
        self.assertEqual(self._call([_log()]), 'slider')

    def test_stale_slider_event_is_ignored(self):
        # punish 链接里的 x5secdata 约 1 小时失效，旧事件不能当成"当前仍需验证"
        self.assertEqual(self._call([_log(minutes_ago=61)]), 'none')

    def test_no_logs_is_none(self):
        self.assertEqual(self._call([]), 'none')

    def test_fresh_face_event_is_face(self):
        self.assertEqual(
            self._call([_log(event_type='face', description='需要人脸 face verify')]),
            'face',
        )

    def test_successful_slider_event_is_none(self):
        # 已经处理成功的事件不算"当前需要验证"
        self.assertEqual(
            self._call([_log(processing_result='滑块验证成功')]),
            'none',
        )


class AutoSliderSolveToggleTests(unittest.TestCase):
    """自动解滑块默认关闭：命中滑块应转人工，而不是自动重试。"""

    def test_disabled_by_default(self):
        from XianyuAutoAsync import XianyuLive

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('AUTO_SLIDER_SOLVE', None)
            self.assertFalse(XianyuLive._auto_slider_solve_enabled())

    def test_enabled_by_env(self):
        from XianyuAutoAsync import XianyuLive

        with mock.patch.dict(os.environ, {'AUTO_SLIDER_SOLVE': 'true'}):
            self.assertTrue(XianyuLive._auto_slider_solve_enabled())


if __name__ == '__main__':
    unittest.main()
