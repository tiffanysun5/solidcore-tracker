"""
mitmproxy addon — captures Wellhub API calls and saves them to wellhub_flows.json.

Run with:
  mitmproxy -s intercept/capture.py --listen-port 8080

Then on iPhone: set HTTP proxy to 192.168.1.204:8080, install cert at http://mitm.it
Open Wellhub app → browse Solidcore classes → tap Book on one.
Press Q to quit mitmproxy when done. Results saved to intercept/wellhub_flows.json.
"""

import json
import re
from datetime import datetime
from pathlib import Path

OUTPUT = Path(__file__).parent / "wellhub_flows.json"
TARGETS = ("gympass", "wellhub", "gympass.com", "wellhub.com")
flows_captured = []


class WellhubCapture:
    def response(self, flow):
        host = flow.request.host or ""
        if not any(t in host for t in TARGETS):
            return

        try:
            req_body = flow.request.get_text() or ""
        except Exception:
            req_body = ""

        try:
            resp_text = flow.response.get_text() or ""
            resp_json = json.loads(resp_text)
        except Exception:
            resp_json = None
            resp_text = flow.response.get_text() if flow.response else ""

        entry = {
            "timestamp":   datetime.now().isoformat(),
            "method":      flow.request.method,
            "url":         flow.request.pretty_url,
            "req_headers": dict(flow.request.headers),
            "req_body":    req_body,
            "status":      flow.response.status_code if flow.response else None,
            "resp_json":   resp_json,
            "resp_text":   resp_text[:2000] if not resp_json else None,
        }
        flows_captured.append(entry)

        # Print summary line in mitmproxy console
        method = flow.request.method
        path   = flow.request.path[:80]
        status = entry["status"]
        print(f"[Wellhub] {method} {path} → {status}")

        # Save after every request so data isn't lost if you quit abruptly
        OUTPUT.parent.mkdir(exist_ok=True)
        OUTPUT.write_text(json.dumps(flows_captured, indent=2))


addons = [WellhubCapture()]
