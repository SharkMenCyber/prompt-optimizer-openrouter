from __future__ import annotations

from dataclasses import dataclass


ABUSE_TERMS = {
    "credential_theft": [
        "api key",
        "admin key",
        "password",
        "credential",
        "token theft",
        "steal token",
        "steal login",
        "session token",
        "cookie theft",
        "phishing",
        "extract the key",
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
        category_matches = [term for term in terms if term in lowered]
        if category_matches:
            category = risk_category
            matches.extend(category_matches)

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
