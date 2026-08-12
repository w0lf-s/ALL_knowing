from __future__ import annotations

from dataclasses import asdict, dataclass

from src.free_email_domains import FREE_EMAIL_DOMAINS


@dataclass
class ParsedEmail:
    email: str
    domain: str
    is_corporate: bool
    name: str
    company: str

    def to_dict(self) -> dict:
        return asdict(self)


def get_email_domain(email: str = "") -> str:
    parts = str(email).lower().split("@")
    return parts[1] if len(parts) == 2 else ""


def is_corporate_email(email: str = "") -> bool:
    domain = get_email_domain(email)
    if not domain:
        return False
    return domain not in FREE_EMAIL_DOMAINS


def name_from_email(email: str = "") -> str:
    local = str(email).split("@")[0] if email else ""
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "" for ch in local)
    tokens = [t for t in cleaned.replace("_", ".").replace("-", ".").split(".") if t]
    if not tokens:
        return ""
    return " ".join(t[:1].upper() + t[1:].lower() for t in tokens)


def company_from_domain(domain: str = "") -> str:
    root = str(domain).split(".")[0] if domain else ""
    if not root:
        return ""
    return root[:1].upper() + root[1:].lower()


def classify_email(email: str) -> ParsedEmail:
    normalized = str(email).strip().lower()
    domain = get_email_domain(normalized)
    return ParsedEmail(
        email=normalized,
        domain=domain,
        is_corporate=is_corporate_email(normalized),
        name=name_from_email(normalized),
        company=company_from_domain(domain),
    )
