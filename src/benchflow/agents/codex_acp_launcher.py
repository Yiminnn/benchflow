#!/usr/bin/env python3
"""Launch wrapper for codex-acp — bridges BENCHFLOW_PROVIDER_* to Codex config.

Codex CLI (Rust binary in openai/codex) does NOT honor OPENAI_BASE_URL as
an env var (verified against codex-rs/core/src/config/mod.rs and
codex-rs/model-provider-info/src/lib.rs). Routing to a relay/proxy/self-
hosted endpoint requires writing the provider into $CODEX_HOME/config.toml
*before* the codex binary starts.

This wrapper reads the standard BENCHFLOW_PROVIDER_* contract emitted by
benchflow's _agent_env.py, writes the appropriate config.toml, then
exec's codex-acp with the original argv. When BENCHFLOW_PROVIDER_BASE_URL
is unset, the wrapper is a no-op pass-through and codex-acp uses its
built-in OpenAI provider as before.

Wire protocol selection:
  - Default: "chat" (works for vLLM, OpenRouter, most OAI-compat relays)
  - Set CODEX_WIRE_API=responses for endpoints that mimic the OpenAI
    Responses API (e.g. gptsapi.net, Azure-Responses).
"""

import json
import os
import pathlib
import sys


def _resolve(*names: str) -> str | None:
    """Return the first env var with a non-empty value among `names`."""
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value
    return None


def main() -> None:
    base_url = _resolve("BENCHFLOW_PROVIDER_BASE_URL", "OPENAI_BASE_URL")
    api_key = _resolve("BENCHFLOW_PROVIDER_API_KEY", "OPENAI_API_KEY")
    provider_name = _resolve("BENCHFLOW_PROVIDER_NAME") or "custom"
    wire_api = _resolve("CODEX_WIRE_API") or (
        "responses" if provider_name == "openai" else "chat"
    )

    if base_url:
        codex_home = pathlib.Path(
            os.environ.get("CODEX_HOME") or (pathlib.Path.home() / ".codex")
        )
        codex_home.mkdir(parents=True, exist_ok=True)

        # Auth.json for downstream codex auth resolution. Codex CLI prefers
        # auth.json over the OPENAI_API_KEY env var when both are present.
        if api_key:
            (codex_home / "auth.json").write_text(
                json.dumps({"OPENAI_API_KEY": api_key})
            )

        # Provider routing — the part the env var alone cannot handle.
        config_lines = [
            f'model_provider = "{provider_name}"',
            "",
            f"[model_providers.{provider_name}]",
            f'name = "{provider_name}"',
            f"base_url = {json.dumps(base_url)}",
            'env_key = "OPENAI_API_KEY"',
            f'wire_api = "{wire_api}"',
            "",
        ]
        (codex_home / "config.toml").write_text("\n".join(config_lines))

    os.execvp("codex-acp", ["codex-acp", *sys.argv[1:]])


if __name__ == "__main__":
    main()
