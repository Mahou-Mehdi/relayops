"""Portable local launcher: python -m relayops."""

import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="RelayOps local agent control center")
    parser.add_argument("--port", type=int, default=int(os.getenv("RELAYOPS_PORT", "8765")))
    parser.add_argument("--db", default=os.getenv("RELAYOPS_DB", "runtime/relayops.sqlite"))
    parser.add_argument("--evaluate", action="store_true", help="Run isolated deterministic regression scenarios and print the report")
    parser.add_argument("--report", type=Path, help="With --evaluate, also save the JSON report to this file")
    args = parser.parse_args()
    if args.report and not args.evaluate:
        parser.error("--report requires --evaluate")
    if os.getenv("RELAYOPS_ENV", "local") != "local":
        parser.error("This release supports the local demonstration environment only.")
    if not 1024 <= args.port <= 65535:
        parser.error("Choose a port between 1024 and 65535.")
    if args.evaluate:
        import json
        from .evaluation import evaluate
        result = evaluate()
        serialized = json.dumps(result, indent=2, allow_nan=False) + "\n"
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(serialized, encoding="utf-8")
        print(serialized, end="")
        if result["passed"] != result["total"]:
            raise SystemExit(1)
        return
    from .app import create_app
    import uvicorn
    Path(args.db).resolve().parent.mkdir(parents=True, exist_ok=True)
    print(f"RelayOps local demo: http://127.0.0.1:{args.port}", flush=True)
    print("Fixture mode is deterministic; live mode requires your own configured model credentials.", flush=True)
    uvicorn.run(create_app(args.db), host="127.0.0.1", port=args.port, workers=1, log_level="info")
