import unittest

from privapii.detection import Case, Span
from privapii.token_review import compare_tokens


class TokenReviewTests(unittest.TestCase):
    def test_distinguishes_missing_repeated_and_unknown_tokens(self):
        case = Case()
        tokens = [case.transform(name, [Span(0, len(name), "PER")])
                  for name in ("Jonas", "Rūta", "Ona", "Mantas")]
        first, missing, other, foreign = tokens
        report = compare_tokens([first, missing], f"{first} {first} {other} {foreign} {missing[:-2]}",
                                set(tokens[:3]))
        self.assertEqual((report.expected, report.returned, report.missing), (2, 1, 1))
        self.assertEqual((report.other_workspace_tokens, report.unknown_tokens), (1, 1))
        self.assertEqual((report.malformed_mentions, report.repeated_occurrences), (1, 1))
        with self.assertRaises(ValueError):
            compare_tokens([foreign], first, set(tokens[:3]))
