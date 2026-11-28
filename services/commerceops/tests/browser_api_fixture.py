"""JSON-lines transport for isolated browser tests of the actual FastAPI routes."""
import json
import os
import secrets
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from commerceops.api.app import create_app
from commerceops.identity import issue_identity


def main():
    os.environ["COMMERCEOPS_SIGNING_SECRET"] = secrets.token_hex(32)
    with tempfile.TemporaryDirectory() as directory:
        url = "sqlite:///" + (Path(directory) / "browser.db").as_posix()
        with TestClient(create_app(url)) as client:
            for line in sys.stdin:
                req = json.loads(line)
                token = issue_identity(user_id="browser", username="tester", workspace_id="browser-test",
                                       can_approve=req["admin"], ttl_seconds=60)
                response = client.request(req["method"], req["path"], content=req.get("body"),
                                          headers={"content-type":"application/json","x-commerceops-identity":token})
                print(json.dumps({"status":response.status_code,"json":response.json()}), flush=True)


if __name__ == "__main__":
    main()
