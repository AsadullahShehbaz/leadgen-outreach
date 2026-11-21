import pytest

from app.services.compliance.footer import build_footer


def test_build_footer_contains_required_values():
    footer = build_footer(
        "Example Sales",
        "123 Main St, Lahore",
        "https://example.com/unsubscribe",
    )

    assert "Example Sales" in footer
    assert "123 Main St, Lahore" in footer
    assert "https://example.com/unsubscribe" in footer
    assert "Unsubscribe" in footer


@pytest.mark.parametrize(
    ("sender", "address"),
    [
        (None, "123 Main St"),
        ("", "123 Main St"),
        ("   ", "123 Main St"),
        ("Example Sales", None),
        ("Example Sales", ""),
        ("Example Sales", "   "),
    ],
)
def test_missing_sender_or_address_is_rejected(sender, address):
    with pytest.raises(ValueError):
        build_footer(sender, address, "https://example.com/unsubscribe")


@pytest.mark.parametrize("url", [None, "", "   "])
def test_missing_opt_out_url_is_rejected(url):
    with pytest.raises(ValueError):
        build_footer("Example Sales", "123 Main St", url)


def test_surrounding_whitespace_is_trimmed():
    footer = build_footer(
        "  Example Sales  ",
        "  123 Main St  ",
        "  https://example.com/unsubscribe  ",
    )

    assert footer.startswith("Example Sales\n123 Main St")
    assert footer.endswith("https://example.com/unsubscribe")
