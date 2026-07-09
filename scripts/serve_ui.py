#!/usr/bin/env python3
"""簡易UIサーバの起動入口。

  python -m scripts.serve_ui            # http://127.0.0.1:8787
  python -m scripts.serve_ui --port 9000
"""
import argparse

from webui.server import serve


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8787)
    args = ap.parse_args()
    serve(args.port)


if __name__ == "__main__":
    main()
