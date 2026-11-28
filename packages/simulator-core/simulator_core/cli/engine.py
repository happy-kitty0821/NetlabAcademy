"""
Command-tree engine: ``Cmd`` nodes, keyword and argument matching,
``?`` help formatting and IOS error messages.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional



@dataclass
class Cmd:
    """
    One node in the command trie.

    *keyword*  — the full keyword for this level (e.g. "show", "ip").
    *help_str* — short description shown in ? output.
    *children* — sub-commands at the next level.
    *handler*  — callable(tokens, session) → str when this is a leaf.
    *args_hint*— shown after this node in ? output (e.g. "<ip-address>").
    *fallback* — when True and the next token matches no child, the
                 handler runs with the full token list instead of an
                 "invalid input" error (used where the argument is an
                 abbreviated interface name the handler resolves itself).
    """
    keyword: str
    help_str: str = ""
    children: list["Cmd"] = field(default_factory=list)
    handler: Optional[Callable[["CLISession", list[str]], str]] = None
    args_hint: str = ""
    fallback: bool = False
    # Argument placeholder: when set, the node stands for a value (its
    # keyword is the label shown in ? help, e.g. "WORD" or "<0-61440>") and
    # matches any token this predicate accepts.
    arg: Optional[Callable[[str], bool]] = None

    def child(self, keyword: str) -> Optional["Cmd"]:
        """Return the child with the given keyword, or None."""
        for c in self.children:
            if c.keyword == keyword:
                return c
        return None


def _match(token: str, keywords: list[str]) -> list[str]:
    """
    Return all keywords that *token* is a valid prefix of.
    Case-insensitive comparison.
    Exact match wins: if token == one keyword exactly, return just that one.
    """
    tl = token.lower()
    exact = [k for k in keywords if k.lower() == tl]
    if exact:
        return exact
    return [k for k in keywords if k.lower().startswith(tl)]


def _step(token: str, nodes: list["Cmd"]) -> tuple[list[str], Optional["Cmd"]]:
    """
    Match *token* at one level of the command tree.

    Returns (matching keywords, node): one keyword and its node on a match,
    several keywords and None when ambiguous, ([], None) when nothing fits.
    Keywords win over argument placeholders.
    """
    keywords = [c.keyword for c in nodes if c.arg is None]
    found = _match(token, keywords)
    if len(found) == 1:
        return found, next(c for c in nodes if c.keyword == found[0] and c.arg is None)
    if found:
        return found, None
    for c in nodes:
        if c.arg is not None and c.arg(token):
            return [c.keyword], c
    return [], None


def _parse_vlan_ids(text: str) -> Optional[list[int]]:
    """'1,3-5,7' -> [1, 3, 4, 5, 7]; None unless every VLAN is 1-4094."""
    result: set[int] = set()
    for part in text.split(","):
        lo, sep, hi = part.partition("-")
        if not lo.isdigit() or (sep and not hi.isdigit()):
            return None
        a = int(lo)
        b = int(hi) if sep else a
        if not 1 <= a <= b <= 4094:
            return None
        result.update(range(a, b + 1))
    return sorted(result)


def _int_in(lo: int, hi: int) -> Callable[[str], bool]:
    return lambda tok: tok.isdigit() and lo <= int(tok) <= hi


_VLAN_RANGE_HELP = "vlan range, example: 1,3-5,7,9-11"


def _vlan_arg(children: list["Cmd"], handler=None) -> "Cmd":
    return Cmd("WORD", _VLAN_RANGE_HELP, arg=lambda t: _parse_vlan_ids(t) is not None,
               children=children, handler=handler)


def _parse_mac(text: str) -> Optional[str]:
    """'0000.1111.2222', '00:00:11:11:22:22' or '0000-1111-2222' -> colon form."""
    digits = re.sub(r"[.:-]", "", text.lower())
    if len(digits) != 12 or not re.fullmatch(r"[0-9a-f]{12}", digits):
        return None
    return ":".join(digits[i:i + 2] for i in range(0, 12, 2))


class CLIMode(Enum):
    USER_EXEC     = auto()
    PRIV_EXEC     = auto()
    GLOBAL_CONFIG = auto()
    IFACE_CONFIG  = auto()
    VLAN_CONFIG   = auto()
    LINE_CONFIG   = auto()


# show commands that need privileged EXEC on IOS
_PRIVILEGED_SHOW = {"running-config", "startup-config", "logging"}


_CONFIG_MODES = (
    CLIMode.GLOBAL_CONFIG, CLIMode.IFACE_CONFIG,
    CLIMode.VLAN_CONFIG, CLIMode.LINE_CONFIG,
)


def _format_help(cmds: list[Cmd]) -> str:
    """
    IOS ? layout: keywords padded to the longest one, then the help text.
    Nodes that still describe their arguments with ``args_hint`` show it
    in a middle column.
    """
    if not cmds:
        return ""
    width = max(len(c.keyword) for c in cmds)
    hint_width = max((len(c.args_hint) for c in cmds), default=0)
    lines = []
    for c in cmds:
        if hint_width:
            lines.append(f"  {c.keyword:<{width}}  {c.args_hint:<{hint_width}}  {c.help_str}".rstrip())
        else:
            lines.append(f"  {c.keyword:<{width}}  {c.help_str}".rstrip())
    return "\n".join(lines)


_INVALID_HEADER = "% Invalid input detected at '^' marker."


# _invalid/_invalid_at return the header followed by a machine-readable
# marker (typed prefix + offending token).  CLISession.execute() replaces it
# with IOS layout: a caret under the offending token, aligned with the
# prompt line, then the header.
_INVALID_MARK = re.compile(re.escape(_INVALID_HEADER) + "\x00([^\x00]*)\x00([^\x01]*)\x01")


def _invalid(tok: str) -> str:
    return f"{_INVALID_HEADER}\x00{tok}\x00{tok}\x01"


def _invalid_at(line: str, bad_tok: str) -> str:
    return f"{_INVALID_HEADER}\x00{line}\x00{bad_tok}\x01"


def _render_invalid(output: str, raw: str, prompt: str) -> str:
    """
    IOS error layout::

        Switch#shwo version
               ^
        % Invalid input detected at '^' marker.

    The caret sits under the offending token of the line as typed.
    """
    if "\x00" not in output:
        return output
    typed = raw.split("|", 1)[0]
    starts = [m.start() for m in re.finditer(r"\S+", typed)]

    def repl(m: re.Match) -> str:
        parts = m.group(1).split()
        bad = m.group(2).lower()
        idx = max((i for i, t in enumerate(parts) if t.lower() == bad), default=len(parts) - 1)
        col = starts[idx] if 0 <= idx < len(starts) else len(typed.rstrip())
        return " " * (len(prompt) + col) + "^\n" + _INVALID_HEADER

    return _INVALID_MARK.sub(repl, output)


def _ambiguous(tok: str, matches: list[str]) -> str:
    return (
        f"% Ambiguous command: \"{tok}\"\n"
        f"  Possible completions: {', '.join(sorted(matches))}"
    )
