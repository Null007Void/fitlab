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
_WINDOWS_PATH = re.compile(r"[A-Za-z]:[/\\][^\s\"'<>|]*", re.IGNORECASE)
# Windows file paths: drive-anchored, final filename CONTIGUOUS with its
# suffix. Interior segments are space-free single tokens; the filename tail
# directly before the anchor suffix may contain ONE space, ONLY when the
# pre-space word itself carries no known suffix — so a complete path is
# never extended into following suffixed prose ("model.gguf notes.txt"
# stops at model.gguf) while space-bearing model filenames
# ("My Model.gguf") are consumed whole.
_WINDOWS_FILE_PATH = re.compile(
    r"[A-Za-z]:[/\\][^\s\"'<>|/\\]+"
    r"(?:[/\\][^\s\"'<>|/\\]+)*"
    r"(?:[/\\]"
    r"(?![^\s\"'<>|/\\]*\.(?:gguf|safetensors|bin|pt|pth|onnx|exe|dll|json|txt|md|log)\b)"
    r"[^\s\"'<>|/\\]+ [^\s\"'<>|/\\]+"
    r"|[/\\][^\s\"'<>|/\\]+"
    r")\.(?:gguf|safetensors|bin|pt|pth|onnx|exe|dll|json|txt|md|log)\b",
    re.IGNORECASE,
)
# UNC path, e.g. \\server\share\file.
_UNC_PATH = re.compile(r"\\\\[^\s\"'<>|\\]+\\[^\s\"'<>|]*")
# User-profile identity segments are handled BEFORE generic path grammar.
# A user-directory identity is: the root, the username, then AT MOST ONE
# further space-joined word — and that word is consumed only when it is
# followed IMMEDIATELY by a path separator (one directory whose name
# contains a space, "...\Users\John Smith\model.gguf"). Prose after the
# username ("sampleuser cache docs/README.md") is never taken: three review
# rounds (13, 14, 26) each rejected space-joined extension rules that could
# consume prose, and probe-verified token analysis shows 3+-word usernames
# to be locally indistinguishable from prose after a username; the adopted
# contract is that PROSE PRESERVATION WINS, so 3+-word usernames degrade to
# the same declared generic-tail exception as other space-bearing segments.
# The root must be followed by a separator first, so ordinary prose
# ("the Users group") is untouched.
_WINDOWS_USER = re.compile(
    r"[/\\]Users[/\\](?!\x01)[^\\/\s\"'<>|]+(?: [^\\/\s\"'<>|]+(?=[/\\]))?(?=[/\\]|\s|$)",
    re.IGNORECASE,
)
_POSIX_USER = re.compile(
    r"/(?:home|Users)/(?!\x01)(?![/\s])"
    r"[^\s/\"'<>|]+(?: [^\s/\"'<>|]+(?=[/]))?(?=[/\s]|$)",
    re.IGNORECASE,
)
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
# /srv2/..., custom mounts). Interior segments are space-free single tokens;
# the filename tail directly before the anchor suffix may contain ONE space,
# ONLY when the pre-space word itself carries no known suffix — so a
# complete path is never extended into a following suffixed prose token
# ("model.gguf notes.txt" stops at model.gguf) while space-bearing model
# filenames ("My Model.gguf") are consumed whole. Prose can never be consumed
# across a distant slash-anchored filename. A recognizable file suffix is
# still required to avoid mangling prose that merely starts with a slash.
_ANY_POSIX_FILE = re.compile(
    r"(?<![\w>/.])/"
    r"(?:"
    r"[^\s\"'<>|/]+(?:/[^\s\"'<>|/]+)*"
    r"|)"
    r"/"
    r"(?:"
    r"[^\s\"'<>|/]+"  # unguarded contiguous filename alternative (round-36 A-1)
    r"|"
    r"(?![^\s\"'<>|/]*\.(?:gguf|safetensors|bin|pt|pth|onnx|exe|dll|json|txt|md|log)\b)"
    r"[^\s\"'<>|/]+ [^\s\"'<>|/]+"
    r")"
    r"\.(?:gguf|safetensors|bin|pt|pth|onnx|exe|dll|json|txt|md|log)\b",
    re.IGNORECASE,
)
# Root-level single-segment POSIX file ("/confidential.gguf"): no interior
# segments, filename contiguous on its suffix — a space inside a root-level
# filename is isomorphic to prose ("my secret notes.md"), so per the
# prose-preservation contract only the contiguous form is taken.
_ROOT_POSIX_FILE = re.compile(
    r"(?<![\w>/.])/"
    r"[^\s\"'<>|/]+\.(?:gguf|safetensors|bin|pt|pth|onnx|exe|dll|json|txt|md|log)\b",
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
    markers_found = []
    if "[redacted:" in value:
        # This string carries at least one generated marker from a previous
        # pass in THIS pipeline (round-37/38 A-1). Protect ONLY the marker
        # tokens via placeholders. Placeholder collision handling
        # (round-39 A-1): markers are stashed into \x01-delimited slots, but
        # if \x01 already occurs in the input, the placeholder would be
        # ambiguous — in that case redact NOTHING in this string (fail-safe)
        # and let the publication privacy scan judge it. \x01 cannot appear
        # in strict JSON input, but imported records are not guaranteed.
        import re as _re
        if "\x01" in value:
            return value
        markers_found = []
        def _stash(match):
            markers_found.append(match.group(0))
            return "\x01" + str(len(markers_found) - 1) + "\x01"
        stash_pattern = _re.compile(r"\[redacted:\d+\]")
        result = stash_pattern.sub(_stash, value)
    else:
        result = value
    result = _UNC_PATH.sub(REDACTED, result)
    # User-profile identity segments BEFORE generic path grammar: the user
    # name itself may contain one space, and a generic path cut at the first
    # whitespace would expose the remainder of the identity.
    result = _WINDOWS_USER.sub(lambda match: "\\Users\\" + REDACTED, result)
    result = _POSIX_USER.sub(lambda match: "/" + REDACTED, result)
    result = _WINDOWS_FILE_PATH.sub(REDACTED, result)
    result = _WINDOWS_PATH.sub(REDACTED, result)
    # Two-pass POSIX handling, per the round-10 review direction: the
    # suffix-anchored lazy grammar runs FIRST and consumes space-bearing and
    # unknown-root paths whole. The known-root grammar then catches pure
    # paths without suffixes; its word-boundary guard keeps /optional-style
    # prose intact and its stop-set keeps prose after the path intact.
    result = _ROOT_POSIX_FILE.sub(REDACTED, result)
    result = _ANY_POSIX_FILE.sub(REDACTED, result)
    result = _POSIX_PATH.sub(REDACTED, result)
    result = _IPV6.sub(REDACTED, result)
    result = _HOME_SEGMENT.sub(REDACTED, result)
    result = _EMAIL.sub(REDACTED, result)
    result = _MAC.sub(REDACTED, result)
    result = _IPV4.sub(REDACTED, result)
    result = _RESERVED_HOSTNAME.sub(REDACTED, result)
    for index, token in enumerate(markers_found):
        result = result.replace("\x01" + str(index) + "\x01", token)
    return result


def redact_value(value):
    """Recursively redact every string inside a JSON-compatible structure.

    Dictionary KEYS are owner-controlled content too: a key carrying a
    private identifier is redacted with the same engine. Keys that redact
    away are disambiguated deterministically (":n" ordinal) when collapsing
    would merge two distinct entries, so no data is silently lost.
    """
    if type(value) is str:
        return redact_text(value)
    if type(value) is dict:
        out = {}
        taken = set()
        for key, item in value.items():
            new_key = redact_text(key) if type(key) is str else key
            if new_key in taken:
                suffix = 1
                while str(new_key) + ":" + str(suffix) in taken:
                    suffix += 1
                new_key = str(new_key) + ":" + str(suffix)
            taken.add(new_key)
            out[new_key] = redact_value(item)
        return out
    if type(value) is list:
        return [redact_value(item) for item in value]
    return value


def redact_structure(value, transform):
    """Deeply apply transform to every string in a JSON-like value.

    Strings include dictionary KEYS, so a key passes through the same
    transform as any value — with the project transforms this keeps
    distinct private identities distinct across keys and values alike.
    Containers are rebuilt dict-first, preserving key order.
    """
    if isinstance(value, str):
        return transform(value)
    if isinstance(value, dict):
        return {transform(k): redact_structure(v, transform) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_structure(v, transform) for v in value]
    return value


def redact_with_distinct_identities(document):
    """Sanitize a structured document, keeping distinct identities distinct.

    Owner-supplied strings that redact away (scenario IDs and similar unique
    labels) would otherwise collapse into identical markers and break replay
    validation. Every distinct sanitized value receives a namespaced ordinal
    ("[redacted:k]") that can never collide with an owner-supplied literal:
    every string that survives redaction unchanged — including literals that
    already look like generated markers — is pre-reserved first.

    Returns (sanitized_document, mapping) where mapping yields each distinct
    generated token for its original string.
    """
    primitive = document
    reserved = set()

    def _reserve(value):
        # Reserve EVERY unchanged string, not only marker-shaped ones: a
        # literal such as "[redacted:0]" survives redaction unchanged and
        # yet collides with the generated-token namespace.
        if type(value) is str and redact_value(value) == value:
            reserved.add(value)
        return value

    redact_structure(primitive, _reserve)
    used = set()
    markers = {}

    def _namespaced(text, k):
        i = text.rfind(REDACTED)
        return text[:i] + "[redacted:" + str(k) + "]" + text[i + len(REDACTED):]

    def _uniquify(value):
        sanitized = redact_value(value)
        if sanitized == value or REDACTED not in sanitized:
            return sanitized
        if value not in markers:
            k = 0
            candidate = _namespaced(sanitized, k)
            while candidate in reserved or candidate in used:
                k += 1
                candidate = _namespaced(sanitized, k)
            markers[value] = candidate
            used.add(candidate)
        return markers[value]

    return redact_structure(primitive, _uniquify), markers


def contains_private_detail(value):
    """True when the text still contains a recognisable private detail."""
    if type(value) is not str or not value:
        return False
    for pattern in (
        _WINDOWS_FILE_PATH,
        _WINDOWS_PATH,
        _UNC_PATH,
        _WINDOWS_USER,
        _POSIX_USER,
        _POSIX_PATH,
        _ANY_POSIX_FILE,
        _ROOT_POSIX_FILE,
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
