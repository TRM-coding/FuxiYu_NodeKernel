import re

# Reject shell metacharacters and line breaks
_META_RE = re.compile(r"[;&|`$<>\\\n]")
# Reject obvious dangerous command keywords
_DANGEROUS_WORDS = re.compile(r"\b(rm|shutdown|reboot|init|mkfs|dd|curl|wget|nc|ncat|perl|python|bash|sh)\b", re.IGNORECASE)


def validate_shell_arg(value: str) -> bool:
    """Raise ValueError if the value looks like it could be used in shell injection.

    This is a conservative heuristic: it rejects values containing shell metacharacters
    or obvious dangerous command words. It does NOT guarantee safety but helps
    catch common cases.
    """
    if value is None:
        return True
    if not isinstance(value, str):
        raise ValueError("invalid argument type")
    if _META_RE.search(value):
        raise ValueError("argument contains shell metacharacters")
    if _DANGEROUS_WORDS.search(value):
        raise ValueError("argument contains dangerous keyword")
    return True


def validate_username(username: str) -> bool:
    """Validate username/container-name-like tokens: allow letters, digits, underscore, hyphen."""
    if username is None:
        return True
    if not isinstance(username, str):
        raise ValueError("invalid username type")
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", username):
        raise ValueError("invalid characters in username")
    return True
