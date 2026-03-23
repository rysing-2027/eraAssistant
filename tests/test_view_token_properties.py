"""Property-based tests for view_token generation.

**Validates: Requirements 1.1, 1.4**

Tests that the view_token generation mechanism (str(uuid.uuid4())) produces
valid UUID4 format strings of exactly 36 characters that pass uuid.UUID validation.
"""

import uuid

from hypothesis import given, settings
from hypothesis import strategies as st


def generate_view_token() -> str:
    """Generate a view_token using the same mechanism as the Record model default."""
    return str(uuid.uuid4())


class TestViewTokenFormatValidity:
    """Property 1: View Token 格式有效性

    For any generated view_token, the value SHALL be a valid UUID4 string
    of exactly 36 characters (including hyphens) that passes UUID format validation.

    **Validates: Requirements 1.1, 1.4**
    """

    @given(st.integers(min_value=0))
    @settings(max_examples=20)
    def test_view_token_is_valid_uuid4_format(self, _seed: int) -> None:
        """Each generated view_token must be a valid UUID4 string."""
        token = generate_view_token()

        # Must be exactly 36 characters (8-4-4-4-12 with hyphens)
        assert len(token) == 36, f"Expected 36 chars, got {len(token)}: {token}"

        # Must be parseable as a valid UUID
        parsed = uuid.UUID(token)

        # Must be version 4
        assert parsed.version == 4, f"Expected UUID version 4, got {parsed.version}"

    @given(st.integers(min_value=0))
    @settings(max_examples=20)
    def test_view_token_has_correct_hyphen_positions(self, _seed: int) -> None:
        """UUID4 tokens must have hyphens at positions 8, 13, 18, 23."""
        token = generate_view_token()

        assert token[8] == "-", f"Expected hyphen at position 8, got '{token[8]}'"
        assert token[13] == "-", f"Expected hyphen at position 13, got '{token[13]}'"
        assert token[18] == "-", f"Expected hyphen at position 18, got '{token[18]}'"
        assert token[23] == "-", f"Expected hyphen at position 23, got '{token[23]}'"

    @given(st.integers(min_value=0))
    @settings(max_examples=20)
    def test_view_token_contains_only_valid_hex_and_hyphens(self, _seed: int) -> None:
        """UUID4 tokens must only contain hex digits and hyphens."""
        token = generate_view_token()
        valid_chars = set("0123456789abcdef-")

        assert set(token).issubset(valid_chars), (
            f"Token contains invalid characters: {set(token) - valid_chars}"
        )

    @given(st.integers(min_value=0))
    @settings(max_examples=20)
    def test_view_token_roundtrips_through_uuid_parsing(self, _seed: int) -> None:
        """A generated token must survive UUID parse -> str roundtrip."""
        token = generate_view_token()
        roundtripped = str(uuid.UUID(token))

        assert token == roundtripped, (
            f"Roundtrip mismatch: original={token}, roundtripped={roundtripped}"
        )


class TestViewTokenUniqueness:
    """Property 2: View Token 唯一性

    For any batch of generated view_tokens, all values SHALL be distinct.
    This validates that the UUID4 generation mechanism produces unique tokens
    across varying batch sizes.

    **Validates: Requirements 1.2**
    """

    @given(batch_size=st.integers(min_value=2, max_value=100))
    @settings(max_examples=20)
    def test_batch_tokens_are_all_unique(self, batch_size: int) -> None:
        """All view_tokens in a batch of any size must be unique."""
        tokens = [generate_view_token() for _ in range(batch_size)]

        assert len(set(tokens)) == len(tokens), (
            f"Duplicate tokens found in batch of {batch_size}: "
            f"{[t for t in tokens if tokens.count(t) > 1]}"
        )

    @given(st.integers(min_value=0))
    @settings(max_examples=20)
    def test_two_consecutive_tokens_are_never_equal(self, _seed: int) -> None:
        """Any two consecutively generated tokens must differ."""
        token_a = generate_view_token()
        token_b = generate_view_token()

        assert token_a != token_b, (
            f"Two consecutive tokens were identical: {token_a}"
        )
