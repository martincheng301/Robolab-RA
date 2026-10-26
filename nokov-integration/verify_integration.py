"""Checks the installed SDK and real UDP transport against a local test receiver."""
import hashlib
import json
from pathlib import Path
import socket
import subprocess
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

from nokov_cli import ROOT, capture, capture_packet, doctor, load_config, probe


def main():
    config = load_config(ROOT / "config.json")
    report = {"installation": doctor(config)}
    archive = ROOT / "downloads" / "XING_Python_SDK_4105645.zip"
    report["archive_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert report["archive_sha256"] == "eb4d2f23538c47bf1ab7c983898d2573a89193e36ea82beaf281853175d8dceb"
    # Confirm non-ASCII paths and XML metacharacters survive the actual wire encoding.
    directory = "C:/采集数据/A&B"
    parsed = ET.fromstring(capture_packet("start", "预览&A", directory))
    assert parsed.tag == "CaptureStart"
    assert parsed.find("Name").attrib["VALUE"] == "预览&A"
    assert parsed.find("DatabasePath").attrib["VALUE"] == directory
    report["xml_unicode_and_escaping"] = True
    for invalid_name in ("../take", "bad:name", " ", "take.", "bad\nname"):
        try:
            capture_packet("start", invalid_name, directory)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Invalid take name accepted: {invalid_name!r}")
    report["invalid_filename_rejection"] = True
    preview = capture(config, "start", "verification_preview", False)
    assert not preview["sent"] and not preview["execution_confirmed"]
    report["preview_sends_nothing"] = True
    # Send STOP only to our ephemeral loopback receiver, never to XINGYING.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
        receiver.bind(("127.0.0.1", 0))
        receiver.settimeout(2)
        local = dict(config, server_ip="127.0.0.1", remote_port=receiver.getsockname()[1])
        sent = capture(local, "stop", "transport_verification", True)
        wire, _ = receiver.recvfrom(65535)
        assert ET.fromstring(wire).tag == "CaptureStop"
        assert sent["sent"] and not sent["execution_confirmed"]
        assert sent["bytes_sent"] == len(wire)
    report["udp_loopback_roundtrip"] = True
    report["xingying_recording_commands_sent"] = False
    report["live_probe"] = probe(ROOT / "config.json", 2)
    report["live_connection_verified"] = bool(report["live_probe"].get("connected"))
    netstat = subprocess.run(["netstat", "-ano", "-p", "udp"], capture_output=True,
                             text=True, errors="replace", timeout=10)
    report["remote_udp_listeners"] = [line.strip() for line in netstat.stdout.splitlines()
                                      if f':{config["remote_port"]} ' in line]
    report["remote_control_execution_verified"] = False
    report["verified_at_utc"] = datetime.now(timezone.utc).isoformat()
    (ROOT / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
