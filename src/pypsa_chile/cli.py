"""Command line interface: ``pypsa-chile fetch | run | report``."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import __version__
from .config import load_config


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("-c", "--config", type=Path, help="YAML file overriding the default config")
    p.add_argument("--data-dir", type=Path, default=Path("data"), help="where raw and processed data live")
    p.add_argument("--start", help="first day of the period, YYYY-MM-DD (overrides config)")
    p.add_argument("--end", help="last day of the period, YYYY-MM-DD (overrides config)")


def _load(args) -> dict:
    cfg = load_config(args.config)
    if args.start:
        cfg["period"]["start"] = args.start
    if args.end:
        cfg["period"]["end"] = args.end
    return cfg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pypsa-chile", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="download and process CEN data for the period")
    _common(p_fetch)
    p_fetch.add_argument("--force", action="store_true", help="download and parse again")

    p_run = sub.add_parser("run", help="build the network, solve the dispatch and compare")
    _common(p_run)
    p_run.add_argument("-o", "--out", type=Path, default=Path("results"), help="results directory")
    p_run.add_argument("--report", action="store_true", help="also write the HTML report")

    p_rep = sub.add_parser("report", help="write the HTML report for a results directory")
    p_rep.add_argument("results", type=Path, nargs="?", default=Path("results"))
    p_rep.add_argument("-o", "--out", type=Path, help="output HTML path")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    if not args.verbose:
        logging.getLogger("pypsa_chile").setLevel(logging.INFO)

    if args.command == "fetch":
        from .fetch import fetch

        for path in fetch(_load(args), args.data_dir, force=args.force):
            print(path)
    elif args.command == "run":
        from .run import run

        summary = run(_load(args), args.data_dir, args.out)
        print(f"results written to {args.out}")
        print(f"demand {summary['demand_gwh']:,.1f} GWh, unserved {summary['load_shedding_gwh']:,.2f} GWh")
        if args.report:
            from .report import build_report

            print(build_report(args.out))
    elif args.command == "report":
        from .report import build_report

        print(build_report(args.results, args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
