from __future__ import annotations

import argparse
import json
import sys

from .data import fetch, load
from .membership import Membership
from .server import make_server, resolve_port
from .symbols import FORMATS


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="sp500-pit")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info", help="dataset metadata")
    sub.add_parser("check", help="list snapshots with implausible member counts")
    sub.add_parser("audit", help="structural audit as JSON; exit 1 on ERROR")
    diff = sub.add_parser("diff", help="historical rows an older CSV and the current one disagree on")
    diff.add_argument("old_csv")
    sub.add_parser("fetch", help="download the latest CSV into the local cache")
    members = sub.add_parser("members", help="members on a date")
    members.add_argument("date")
    members.add_argument("--fmt", choices=sorted(FORMATS), default="raw")
    serve = sub.add_parser("serve", help="run the local JSON service")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, help="default: PORT env/.env, else 4 digits in the folder name, else 8765")
    args = parser.parse_args(argv)

    if args.cmd == "fetch":
        print(fetch())
    elif args.cmd == "serve":
        if args.host not in ("127.0.0.1", "localhost", "::1"):
            print("Refusing non-loopback host: the service has no authentication", file=sys.stderr)
            return 2
        port = args.port or resolve_port()
        server = make_server(args.host, port)
        print(f"Serving on http://{args.host}:{port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    else:
        m = load()
        if args.cmd == "info":
            print(json.dumps(m.meta(), indent=2))
        elif args.cmd == "check":
            for when, n in m.validate():
                print(f"{when}: {n} members")
        elif args.cmd == "audit":
            report = m.audit()
            print(json.dumps(report, indent=2))
            return 1 if report["status"] == "ERROR" else 0
        elif args.cmd == "diff":
            for row in Membership.from_csv(args.old_csv).restatements(m):
                print(f"{row['date']}: +{','.join(row['added'])} -{','.join(row['removed'])}")
        else:
            print("\n".join(m.members_asof(args.date, args.fmt)))
    return 0
