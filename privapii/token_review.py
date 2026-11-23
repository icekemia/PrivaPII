"""Compare a returned document with the tokens from selected exports."""

from dataclasses import dataclass

from .detection import TOKEN, TOKEN_START


@dataclass(frozen=True)
class TokenReview:
    expected: int
    returned: int
    missing: int
    other_workspace_tokens: int
    unknown_tokens: int
    malformed_mentions: int
    repeated_occurrences: int


def compare_tokens(originals, returned, known):
    expected = {token for text in originals for token in TOKEN.findall(text)}
    if not expected or not expected <= known:
        raise ValueError("Choose pseudonymized exports created by the open workspace.")
    occurrences = TOKEN.findall(returned)
    observed = set(occurrences)
    return TokenReview(len(expected), len(observed & expected), len(expected - observed),
                       len((observed & known) - expected), len(observed - known),
                       len(TOKEN_START.findall(TOKEN.sub(" ", returned))),
                       len(occurrences) - len(observed))
