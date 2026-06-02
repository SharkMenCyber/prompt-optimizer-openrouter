from __future__ import annotations

import re
from dataclasses import dataclass


ABUSE_TERMS = {
    "credential_theft": [
        # Contextual attack phrases. Bare nouns such as "password", "api key",
        # "credential", or "session token" are intentionally NOT here because
        # they are common in legitimate defensive and documentation prompts.
        "credential theft",
        "token theft",
        "cookie theft",
        "phishing",
        "steal password",
        "steal passwords",
        "steal credential",
        "steal credentials",
        "steal api key",
        "steal admin key",
        "steal token",
        "steal login",
        "dump password",
        "dump passwords",
        "dump credential",
        "dump credentials",
        "dump api key",
        "harvest credential",
        "harvest credentials",
        "harvest password",
        "harvest passwords",
        "extract the key",
        "extract api key",
        "extract secret key",
        "exfiltrate credential",
        "exfiltrate credentials",
        "exfiltrate token",
        "exfiltrate tokens",
        "hijack session",
    ],
    "malware": [
        "keylogger",
        "keystroke logger",
        "capture keystrokes",
        "malware",
        "ransomware",
        "spyware",
        "trojan",
        "backdoor",
        "botnet",
        "exfiltrate",
        "exfiltration",
    ],
    "abuse_bypass": [
        "bypass security",
        "evade detection",
        "evasion",
        "disable antivirus",
        "disable anti virus",
        "windows defender",
        "avoid detection",
        "undetected",
        "stealth",
        "minimal detection footprint",
        "low detection footprint",
        "hide from security",
        "jailbreak",
        "unauthorized access",
    ],
    "covert_monitoring": [
        "hid input",
        "system-wide listener",
        "global keyboard hook",
        "keyboard hook",
        "capture input events",
        "background listener",
    ],
}

# Catch credential-theft variants not spelled out in ABUSE_TERMS, while still
# allowing benign uses of security nouns by requiring an attack verb nearby.
CREDENTIAL_ATTACK_VERBS = (
    "steal",
    "dump",
    "harvest",
    "hijack",
    "crack",
    "exfiltrate",
    "extract",
)
SENSITIVE_CREDENTIAL_NOUNS = (
    "password",
    "passwords",
    "api key",
    "api keys",
    "admin key",
    "admin keys",
    "secret key",
    "secret keys",
    "credential",
    "credentials",
    "session token",
    "session tokens",
    "token",
    "tokens",
    "login",
    "logins",
    "cookie",
    "cookies",
)


@dataclass(frozen=True)
class PolicyAssessment:
    is_disallowed: bool
    mode: str
    category: str | None
    matched_terms: list[str]
    action: str
    guidance: str

    def as_dict(self) -> dict:
        return {
            "is_disallowed": self.is_disallowed,
            "mode": self.mode,
            "category": self.category,
            "matched_terms": self.matched_terms,
            "action": self.action,
            "guidance": self.guidance,
        }


def assess_prompt_policy(text: str, mode: str = "strict") -> PolicyAssessment:
    normalized_mode = mode if mode in {"standard", "strict"} else "standard"
    lowered = text.lower()
    matches: list[str] = []
    category = None
    for risk_category, terms in ABUSE_TERMS.items():
        category_matches = [term for term in terms if _phrase_in_text(term, lowered)]
        if category_matches:
            if category is None:
                category = risk_category
            matches.extend(category_matches)

    contextual_matches = _credential_theft_context_matches(lowered)
    if contextual_matches:
        if category is None:
            category = "credential_theft"
        matches.extend(contextual_matches)

    is_disallowed = bool(matches)
    action = "redirect" if is_disallowed else "allow"
    if normalized_mode == "strict" and is_disallowed:
        action = "refuse_and_redirect"

    guidance = (
        "Refuse to strengthen the risky instruction and redirect toward safe, defensive, educational, "
        "or authorization-bound help. Do not optimize instructions that enable credential theft, malware, "
        "stealth, covert monitoring, evasion, or unauthorized access."
        if is_disallowed
        else "No disallowed abuse intent detected by the local policy layer."
    )
    return PolicyAssessment(
        is_disallowed=is_disallowed,
        mode=normalized_mode,
        category=category,
        matched_terms=sorted(set(matches)),
        action=action,
        guidance=guidance,
    )


def _phrase_in_text(phrase: str, lowered: str) -> bool:
    """Match a risk phrase as words, not as arbitrary substring fragments."""
    return re.search(rf"\b{re.escape(phrase)}\b", lowered) is not None


def _credential_theft_context_matches(lowered: str) -> list[str]:
    matches: list[str] = []
    for verb in CREDENTIAL_ATTACK_VERBS:
        for noun in SENSITIVE_CREDENTIAL_NOUNS:
            # Allow up to three words between the attack verb and sensitive noun:
            # "steal the user's password", "extract an admin api key", etc.
            pattern = rf"\b{re.escape(verb)}\b(?:\W+\w+){{0,3}}\W+{re.escape(noun)}\b"
            if re.search(pattern, lowered):
                matches.append(f"{verb} ... {noun}")
    return matches
