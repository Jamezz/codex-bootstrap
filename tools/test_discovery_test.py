from __future__ import annotations

import unittest


class ToolsDiscoveryTest(unittest.TestCase):
    def test_root_tools_discovery_includes_velocity_tool_tests(self) -> None:
        suite = unittest.defaultTestLoader.discover("tools", pattern="*_test.py")
        test_ids = sorted(iter_test_ids(suite))

        self.assertTrue(
            any(test_id.startswith("supermeta-check.check_test.") for test_id in test_ids),
            "tools/supermeta-check/check_test.py must be included by root tools discovery",
        )
        self.assertTrue(
            any(test_id.startswith("supermeta-fix.fix_test.") for test_id in test_ids),
            "tools/supermeta-fix/fix_test.py must be included by root tools discovery",
        )


def iter_test_ids(suite: unittest.TestSuite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from iter_test_ids(item)
        else:
            yield item.id()
