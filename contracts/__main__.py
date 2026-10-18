"""CLI entry: python3 -m contracts <subcommand> ..."""

from __future__ import annotations

import argparse
import sys

from . import cli

sys.exit(cli.main(sys.argv[1:]))
