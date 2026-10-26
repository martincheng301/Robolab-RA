"""Local JSON command interface for the official NOKOV SDK and UDP protocol."""
from __future__ import annotations

import argparse
import contextlib
import importlib.metadata
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
RESULT_PREFIX = "__NOKOV_RESULT__"


def emit(value):
    print(json.dumps(value, ensure_ascii=False, allow_nan=False))


def load_config(path):
    config = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    socket.inet_pton(socket.AF_INET, config["server_ip"])
    if not 1 <= int(config["remote_port"]) <= 65535:
        raise ValueError("remote_port must be between 1 and 65535")
    return config


def import_sdk():
    # The vendor module prints during import; preserve clean JSON on stdout.
    with contextlib.redirect_stdout(sys.stderr):
        from nokov import nokovsdk
    return nokovsdk


def doctor(config):
    sdk = import_sdk()
    client = sdk.PySDKClient()
    version = list(client.PyNokovVersion())
    del client
    try:
        directory_exists = Path(config["capture_directory"]).is_dir()
        directory_error = None
    except OSError as error:
        directory_exists = None
        directory_error = str(error)
    return {
        "ok": True,
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "package_version": importlib.metadata.version("nokovpy"),
        "native_sdk_version_bytes": version,
        "dll_loaded": True,
        "server_ip": config["server_ip"],
        "remote_port": config["remote_port"],
        "capture_directory_exists": directory_exists,
        "capture_directory_check_error": directory_error,
        "live_connection_verified": False,
        "note": "Local installation check only. Use probe to check XINGYING connectivity.",
    }


def snapshot_frame(frame):
    return {
        "frame_number": frame.iFrame,
        "timestamp_raw": frame.iTimeStamp,
        "marker_set_count": frame.nMarkerSets,
        "unidentified_marker_count": frame.nOtherMarkers,
        "skeleton_count": frame.nSkeletons,
        "rigid_bodies": [
            {
                "id": b.ID,
                "position_mm": [b.x, b.y, b.z],
                "rotation_xyzw": [b.qx, b.qy, b.qz, b.qw],
                "tracking_valid": bool(b.params & 1),
            }
            for b in frame.RigidBodies[:frame.nRigidBodies]
        ],
    }


def sdk_probe_worker(config, seconds):
    sdk = import_sdk()
    client = sdk.PySDKClient()
    client.PySetVerbosityLevel(0)
    result = client.Initialize(config["server_ip"].encode("ascii"))
    if result != 0:
        return {
            "ok": False, "connected": False, "sdk_return_code": result,
            "server_ip": config["server_ip"],
            "note": "Check XINGYING is running and SDK is enabled on the selected network address.",
        }
    description = sdk.ServerDescription()
    description_result = client.PyGetServerDescription(description)
    output = {
        "ok": True, "connected": True, "server_ip": config["server_ip"],
        "server_description_return_code": description_result,
        "host_present": bool(description.HostPresent),
        "app": bytes(description.szHostApp).decode("utf-8", errors="replace"),
        "app_version_bytes": list(description.HostAppVersion),
        "frame_received": False,
    }
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        frame = client.PyGetLastFrameOfMocapData()
        if frame:
            try:
                output["frame"] = snapshot_frame(frame.contents)
                output["frame_received"] = True
            finally:
                client.PyNokovFreeFrame(frame)
            break
        time.sleep(0.05)
    if not output["frame_received"]:
        output["note"] = "Connected but no frame received. Start live playback or play a recorded take."
    del client
    return output


def probe(config_path, seconds):
    # Bound vendor DLL calls, including initialization and shutdown, in a child process.
    try:
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--config", str(config_path),
             "_probe-worker", "--seconds", str(seconds)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=seconds + 12,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "connected": False, "error": "sdk_connection_timeout"}
    for line in reversed(completed.stdout.splitlines()):
        if line.startswith(RESULT_PREFIX):
            return json.loads(line[len(RESULT_PREFIX):])
    return {
        "ok": False, "connected": False, "error": "sdk_worker_failed",
        "exit_code": completed.returncode,
        "details": completed.stderr[-2000:],
    }


def capture_packet(action, name, directory):
    if not name.strip() or name != name.strip() or name.endswith(".") or any(
        c in name for c in '<>:"/\\|?*'
    ) or any(ord(c) < 32 for c in name):
        raise ValueError("Take name must be a valid Windows filename without an extension")
    root = ET.Element("CaptureStart" if action == "start" else "CaptureStop")
    values = {"Name": name}
    if action == "start":
        values.update({"SessionName": "", "Notes": "", "Delay": "Reserved",
                       "Description": "", "DatabasePath": str(directory).replace("\\", "/"),
                       "TimeCode": "00:00:00:00", "PacketID": "0"})
    else:
        values.update({"Notes": "", "Assets": "", "TimeCode": "00:00:00:00",
                       "HostName": "", "ProcessID": ""})
    for tag, value in values.items():
        ET.SubElement(root, tag, {"VALUE": value})
    packet = b'<?xml version="1.0" encoding="UTF-8"?>' + ET.tostring(root, encoding="utf-8")
    if len(packet) > 65507:
        raise ValueError("Capture command exceeds the UDP packet size limit")
    return packet


def capture(config, action, name, send):
    packet = capture_packet(action, name, config["capture_directory"])
    result = {"ok": True, "action": action, "name": name,
              "destination": [config["server_ip"], config["remote_port"]],
              "sent": False, "execution_confirmed": False,
              "xml": packet.decode("utf-8")}
    if send:
        if action == "start" and not Path(config["capture_directory"]).is_dir():
            raise ValueError("Configured capture directory does not exist on this computer")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            result["bytes_sent"] = sock.sendto(
                packet, (config["server_ip"], config["remote_port"]))
        result["sent"] = True
        result["note"] = "UDP dispatched without acknowledgement; verify recording state in XINGYING."
    else:
        result["note"] = "Preview only. Add --send to transmit this capture command."
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config.json")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Check installed SDK and DLL; no network calls")
    p = commands.add_parser("probe", help="Check server connection and read a frame")
    p.add_argument("--seconds", type=float, default=3)
    worker = commands.add_parser("_probe-worker", help=argparse.SUPPRESS)
    worker.add_argument("--seconds", type=float, default=3)
    for name in ("start", "stop"):
        p = commands.add_parser(name, help=f"Preview or send a capture {name} command")
        p.add_argument("--name", required=True)
        p.add_argument("--send", action="store_true")
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        if args.command in ("probe", "_probe-worker") and not 0 < args.seconds <= 30:
            raise ValueError("seconds must be between 0 and 30")
        if args.command == "doctor":
            result = doctor(config)
        elif args.command == "probe":
            result = probe(args.config.resolve(), args.seconds)
        elif args.command == "_probe-worker":
            result = sdk_probe_worker(config, args.seconds)
            print(RESULT_PREFIX + json.dumps(result, ensure_ascii=False), flush=True)
            return 0 if result.get("ok") else 1
        else:
            result = capture(config, args.command, args.name, args.send)
        emit(result)
        return 0 if result.get("ok") else 1
    except Exception as error:
        result = {"ok": False, "error": str(error), "error_type": type(error).__name__}
        if args.command == "_probe-worker":
            print(RESULT_PREFIX + json.dumps(result, ensure_ascii=False), flush=True)
        else:
            emit(result)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
