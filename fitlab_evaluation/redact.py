"""Redaction of private detail from report-bound free text.

The Capability Passport is the artifact most likely to be shared, and it
carries owner-declared prose (scenario labels, residency assumptions, runtime
overhead bases). A declaration may innocently mention a local path, a user
name, a host name or a private network address. Those must not leak into a
document whose whole purpose is to be shareable.

Redaction is deliberately conservative and structural. It removes recognisable
private identifiers and leaves scientific identifiers, formula names, model
names and version strings intact, because those carry the report's meaning.
"""

import re

REDACTED = "[redacted]"

# Windows drive-letter path without spaces.
_WINDOWS_PATH = re.compile(r"[A-Za-z]:[\\/][^\s\"'<>|]*")
# Windows file paths: drive-anchored with a CONTIGUOUS final filename
# anchored directly on its suffix. Interior segments may contain spaces
# (whole-segment tokens), but the final segment may not, so a path match can
# never extend across prose to a distant filename later in the sentence.
_WINDOWS_FILE_PATH = re.compile(
    r"[A-Za-z]:[/\\]"
    r"(?:[^\s\"'<>|/\\]+(?: +[^\s\"'<>|/\\]+)*)"
    r"(?:[/\\](?:[^\s\"'<>|/\\]+(?: +[^\s\"'<>|/\\]+)*))*"
    r"[/\\][^\s\"'<>|/\\]+\.(?:gguf|safetensors|bin|pt|pth|onnx|exe|dll|json|txt|md|log)\b",
    re.IGNORECASE,
)
# UNC path, e.g. \\server\share\file.
_UNC_PATH = re.compile(r"\\\\[^\s\"'<>|\\]+\\[^\s\"'<>|]*")
# Absolute POSIX path under a system or home root. Two-pass design:
#   1) suffix-anchored lazy grammar (_ANY_POSIX_FILE) runs first and consumes
#      space-bearing and unknown-root paths whole, stopping at a file suffix;
#   2) the known-root grammar then runs with a word-boundary guard so the
#      root word can not be a prefix of a longer word (/opt vs /optional),
#      and its own charset stops the match at the next whitespace.
_POSIX_PATH = re.compile(
    r"(?<![\w>/.])/(?:home|Users|usr|var|opt|etc|mnt|media|srv|root|tmp|private|data|Volumes|snap|flatpak)"
    r"(?=[/\s\"'<>|]|$)(?:/[^\s\"'<>|]+)*",
    re.IGNORECASE,
)
# Any other absolute POSIX-looking path with a file suffix (covers /data/...,
# /srv2/..., custom mounts). Interior segments may contain spaces
# (whole-segment tokens), but the final filename is CONTIGUOUS with its
# suffix, so ordinary prose containing a distant filename ("...consult
# README.md") can never extend a path match. A recognizable file suffix is
# still required to avoid mangling prose that merely starts with a slash.
_ANY_POSIX_FILE = re.compile(
    r"(?<![\w>/.])/"
    r"(?:[^\s\"'<>|/]+(?: +[^\s\"'<>|/]+)*)"
    r"(?:/(?:[^\s\"'<>|/]+(?: +[^\s\"'<>|/]+)*))*"
    r"/[^\s\"'<>|/]+\.(?:gguf|safetensors|bin|pt|pth|onnx|exe|dll|json|txt|md|log)\b",
    re.IGNORECASE,
)
# IPv6: full form (8 groups) or compressed form containing "::" (including
# leading "::" like ::1 and suffix forms like fd00::1234). Ordinary clock or
# duration strings (12:34:56) contain no "::" and fewer than 8 groups, so
# they survive.
_IPV6 = re.compile(
    r"(?<![\w:])"
    r"(?:[A-Fa-f0-9]{1,4}:){7}[A-Fa-f0-9]{1,4}"
    r"|(?:[A-Fa-f0-9]{0,4}:){1,7}:(?:[A-Fa-f0-9]{1,4}(?::[A-Fa-f0-9]{0,4}){0,6})?"
    r"(?![\w:])"
)
# Bare user-home fragment such as Users/name or home/name.
_HOME_SEGMENT = re.compile(r"\b(?:Users|home)/[^\s\"'<>]+")
# Windows user profile segment, e.g. \Users\name\.
_WINDOWS_USER = re.compile(r"\\Users\\[^\\\s\"'<>]+")
# Email address.
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
# IPv4 address with an optional port.
_IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?(?![\w.])")
# MAC address.
_MAC = re.compile(r"(?<![\w-])(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}(?![\w-])")
# Reserved/internal DNS names that should never appear in a shareable report.
_RESERVED_HOSTNAME = re.compile(
    r"\b(?:[A-Za-z0-9-]+\.)+(?:local|lan|internal|example|test|invalid)\b",
    re.IGNORECASE,
)

# Identifiers that must survive redaction even though they contain dots.
_PRESERVE = (
    "fitlab.",
    "LFM2.5",
    "llamacpp",
    "gguf",
    "GGUF",
)


def _preserved(text):
    """True when the text is a known-safe scientific or product identifier."""
    return any(marker in text for marker in _PRESERVE)


def redact_text(value):
    """Return the text with private identifiers replaced by a marker.

    Non-string input is returned unchanged so callers can pass values that
    are already structured.
    """
    if type(value) is not str or not value:
        return value
    result = value
    result = _UNC_PATH.sub(REDACTED, result)
    result = _WINDOWS_FILE_PATH.sub(REDACTED, result)
    result = _WINDOWS_PATH.sub(REDACTED, result)
    # A lambda replacement avoids backslash-escape interpretation of "\Users".
    result = _WINDOWS_USER.sub(lambda match: "\\Users\\" + REDACTED, result)
    # Two-pass POSIX handling, per the round-10 review direction: the
    # suffix-anchored lazy grammar runs FIRST and consumes space-bearing and
    # unknown-root paths whole. The known-root grammar then catches pure
    # paths without suffixes; its word-boundary guard keeps /optional-style
    # prose intact and its stop-set keeps prose after the path intact.
    result = _ANY_POSIX_FILE.sub(REDACTED, result)
    result = _POSIX_PATH.sub(REDACTED, result)
    result = _IPV6.sub(REDACTED, result)
    result = _HOME_SEGMENT.sub(REDACTED, result)
    result = _EMAIL.sub(REDACTED, result)
    result = _MAC.sub(REDACTED, result)
    result = _IPV4.sub(REDACTED, result)
    result = _RESERVED_HOSTNAME.sub(REDACTED, result)
    return result


def redact_value(value):
    """Recursively redact every string inside a JSON-compatible structure."""
    if type(value) is str:
        return redact_text(value)
    if type(value) is dict:
        return {key: redact_value(item) for key, item in value.items()}
    if type(value) is list:
        return [redact_value(item) for item in value]
    return value


def contains_private_detail(value):
    """True when the text still contains a recognisable private detail."""
    if type(value) is not str or not value:
        return False
    for pattern in (
        _WINDOWS_FILE_PATH,
        _WINDOWS_PATH,
        _UNC_PATH,
        _POSIX_PATH,
        _ANY_POSIX_FILE,
        _IPV6,
        _HOME_SEGMENT,
        _EMAIL,
        _IPV4,
        _MAC,
        _RESERVED_HOSTNAME,
    ):
        if pattern.search(value):
            return True
    return False
