def build_footer(
    sender_identity: str | None,
    postal_address: str | None,
    opt_out_url: str,
) -> str:
    sender = sender_identity.strip() if isinstance(sender_identity, str) else ""
    address = postal_address.strip() if isinstance(postal_address, str) else ""
    url = opt_out_url.strip() if isinstance(opt_out_url, str) else ""

    if not sender:
        raise ValueError("Sender identity is required")
    if not address:
        raise ValueError("Postal address is required")
    if not url:
        raise ValueError("Opt-out URL is required")

    return (
        f"{sender}\n"
        f"{address}\n\n"
        f"Not interested? Unsubscribe: {url}"
    )
