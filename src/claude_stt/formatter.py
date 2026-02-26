"""Post-processing text formatter for transcribed speech."""

import re

# Common Whisper mis-transcriptions (German phonetics).
# Keys are case-insensitive patterns, values are replacements.
# Use word boundaries to avoid false positives.
_CORRECTIONS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\bSurfer\b'), 'Server'),
    (re.compile(r'\bsurfer\b'), 'server'),
]

# Greeting patterns (German + English)
_GREETING_RE = re.compile(
    r'^('
    r'(?:Hi|Hallo|Hey|Moin|Servus|Yo|Hello)'
    r'(?:\s+\w+)?'  # optional name
    r'[,!.]?'
    r')\s+',
    re.IGNORECASE,
)

_FORMAL_GREETING_RE = re.compile(
    r'^('
    r'(?:Sehr geehrte[rs]?|Liebe[rs]?|Guten (?:Tag|Morgen|Abend))'
    r'(?:\s+(?:Frau|Herr|Damen und Herren))?'
    r'(?:\s+\w+)?'
    r'[,!.]?'
    r')\s+',
    re.IGNORECASE,
)

# Closing patterns (German + English)
_CLOSING_RE = re.compile(
    r'\s+'
    r'('
    r'(?:VG|LG|MfG|BG|SG)'
    r'|(?:(?:Viele|Beste|Liebe|Schöne|Herzliche|Freundliche)\s+Grüße)'
    r'|(?:Mit (?:freundlichen|besten|herzlichen|lieben) Grüßen)'
    r'|(?:Grüße)'
    r'|(?:Bis (?:dann|bald|später|morgen|gleich))'
    r'|(?:Tschüss|Ciao|Cheers|Best regards|Kind regards|Thanks|Danke)'
    r')'
    r'(?:[,.]?\s*\w+)*[.,!\s]*$',  # optional name + trailing punctuation
    re.IGNORECASE,
)


def fix_transcription_errors(text: str, user_corrections: dict | None = None) -> str:
    """Fix common Whisper mis-transcriptions (hardcoded + user-defined)."""
    for pattern, replacement in _CORRECTIONS:
        text = pattern.sub(replacement, text)
    if user_corrections:
        for wrong, right in user_corrections.items():
            pat = re.compile(r'\b' + re.escape(wrong) + r'\b')
            text = pat.sub(right, text)
    return text


def format_paragraphs(text: str) -> str:
    """Format transcribed text with paragraph breaks.

    Rules:
    - Greeting line (Hi/Hallo/Hey + name) gets its own line
    - Closing (VG/LG/Grüße etc.) gets its own line
    - Body text stays as continuous paragraph
    """
    if not text or len(text) < 10:
        return text

    result = text

    # Extract greeting to its own line
    for pattern in (_GREETING_RE, _FORMAL_GREETING_RE):
        match = pattern.match(result)
        if match:
            greeting = match.group(1).rstrip()
            rest = result[match.end():].lstrip()
            if rest:
                result = greeting + "\n\n" + rest
            break

    # Extract closing to its own line
    match = _CLOSING_RE.search(result)
    if match:
        before = result[:match.start()].rstrip()
        closing = match.group(0).strip()
        if before:
            result = before + "\n\n" + closing

    return result
