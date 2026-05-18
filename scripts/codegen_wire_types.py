"""Generate TypeScript types for WireEvent from msgspec schemas.

Writes packages/ts-core/src/protocol/wire.ts. CI fails if output differs from
committed file (see .github/workflows/ci.yml codegen job).
"""

from __future__ import annotations

import types
import typing
from pathlib import Path

from ai_accounts_core.protocol.wire import (
    WIRE_PROTOCOL_VERSION,
    ChatDoneEvent,
    ChatTokenEvent,
    ChatToolCallEvent,
    ErrorEvent,
    PtyExitEvent,
    PtyOutputEvent,
    PtyResizeEvent,
    SessionEndEvent,
    SessionStartEvent,
)

OUT = Path(__file__).resolve().parents[1] / "packages/ts-core/src/protocol/wire.ts"

EVENT_TYPES = [
    SessionStartEvent,
    SessionEndEvent,
    ChatTokenEvent,
    ChatToolCallEvent,
    ChatDoneEvent,
    PtyOutputEvent,
    PtyResizeEvent,
    PtyExitEvent,
    ErrorEvent,
]


def py_to_ts(py_type: object) -> str:
    origin = typing.get_origin(py_type)
    args = typing.get_args(py_type)
    if py_type is str:
        return "string"
    if py_type is int or py_type is float:
        return "number"
    if py_type is bool:
        return "boolean"
    if py_type is bytes:
        return "Uint8Array"
    if py_type is type(None):
        return "null"
    if origin is typing.Literal:
        return " | ".join(f'"{a}"' for a in args)
    if origin in (typing.Union, types.UnionType):
        return " | ".join(py_to_ts(a) for a in args)
    return "unknown"


def render_struct(cls: type) -> str:
    tag = cls.__struct_config__.tag
    name = cls.__name__
    lines = [f"export interface {name} {{", f'  type: "{tag}";']
    hints = typing.get_type_hints(cls)
    for field in cls.__struct_fields__:
        ts_type = py_to_ts(hints[field])
        lines.append(f"  {field}: {ts_type};")
    lines.append("}")
    return "\n".join(lines)


def main() -> None:
    header = (
        "// @generated from packages/core/src/ai_accounts_core/protocol/wire.py\n"
        "// Do not edit directly. Run `just codegen` to regenerate.\n\n"
        f"export const WIRE_PROTOCOL_VERSION = {WIRE_PROTOCOL_VERSION};\n\n"
    )
    body = "\n\n".join(render_struct(cls) for cls in EVENT_TYPES)
    union = (
        "\n\nexport type WireEvent =\n"
        + "\n".join(f"  | {cls.__name__}" for cls in EVENT_TYPES)
        + ";\n"
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(header + body + union)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
