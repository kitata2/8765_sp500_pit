from __future__ import annotations

import argparse
import json
import sys

from .data import fetch, load
from .server import make_server
from .symbols import FORMATS


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="sp500-pit")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info", help="dataset metadata")
    sub.add_parser("check", help="list snapshots with implausible member counts")
    sub.add_parser("fetch", help="download the latest CSV into the local cache")
    members = sub.add_parser("members", help="members on a date")
    members.add_argument("date")
    members.add_argument("--fmt", choices=sorted(FORMATS), default="raw")
    serve = sub.add_parser("serve", help="run the local JSON service")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    if args.cmd == "fetch":
        print(fetch())
    elif args.cmd == "serve":
        if args.host not in ("127.0.0.1", "localhost", "::1"):
            print("Refusing non-loopback host: the service has no authentication", file=sys.stderr)
            return 2
        server = make_server(args.host, args.port)
        print(f"Serving on http://{args.host}:{args.port}")
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
        else:
            print("\n".join(m.members_asof(args.date, args.fmt)))
    return 0
