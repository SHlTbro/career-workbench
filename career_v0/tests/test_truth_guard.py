from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


path = Path(__file__).parents[2] / "tools" / "truth-guard.py"
spec = importlib.util.spec_from_file_location("career_truth_guard", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TruthGuardRegressionTests(unittest.TestCase):
    def test_true_prefix_plus_invented_claim_is_not_supported(self):
        master = ["- 使用 Python 构建检索工作流。"]
        self.assertTrue(module.exact_master_line_match(master[0], master))
        self.assertFalse(module.exact_master_line_match(
            "- 使用 Python 构建检索工作流，并为某客户提升营收 300%。", master))


if __name__ == "__main__":
    unittest.main()
