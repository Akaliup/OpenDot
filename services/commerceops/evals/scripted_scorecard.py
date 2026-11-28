"""Run the existing scripted integration cases and publish their actual outcomes."""

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

directory = Path(__file__).resolve().parent
with tempfile.TemporaryDirectory() as tmp:
    report = Path(tmp) / "junit.xml"
    run = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/test_scripted_agent_chain.py",
                          f"--junitxml={report}"], cwd=directory.parent)
    cases = []
    for case in ET.parse(report).iter("testcase"):
        outcome = next((x.tag for x in case if x.tag in {"failure", "error", "skipped"}), "passed")
        cases.append({"case_id": case.get("name"), "status": outcome})
    card = {"generated_at": datetime.now(timezone.utc).isoformat(), "cases": cases}
    (directory / "scripted_scorecard.json").write_text(json.dumps(card, indent=2)+"\n", encoding="utf8")
    sys.exit(run.returncode)
