"""Source-specific importers for official exchange metadata and market data.

Each module here talks to exactly one external source and is responsible for capturing the
**raw** response before anything is parsed. `CLAUDE_TFEX.md` section 2 requires retrieval
date, fingerprint and fallback behaviour to be recorded for every source; a parser that
discards the bytes it parsed makes that impossible to audit later.

No credentials are stored in this package. Anything that needs authentication reads it from
the environment and never logs it.
"""
