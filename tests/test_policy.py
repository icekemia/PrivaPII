import unittest

from policy import ALL_CATEGORIES, selected_indices
from privapii import Span


class PolicyTests(unittest.TestCase):
    def test_category_policy_and_exclusion_use_existing_findings(self):
        findings = [Span(0, 5, "PER"), Span(6, 18, "EMAIL"), Span(20, 25, "PER")]
        self.assertEqual(selected_indices(findings, ALL_CATEGORIES, set()), [0, 1, 2])
        self.assertEqual(selected_indices(findings, {"PER"}, {findings[2]}), [0])
        self.assertEqual(selected_indices(findings, set(), set()), [])
