"""Inspect a C3D export and preserve every frame in a raw-coordinate CSV."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys
import warnings

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "analysis-deps"))
import c3d
import numpy as np


def runs(mask, frame_numbers, rate):
    changes = np.diff(np.r_[False, mask, False].astype(int))
    return [
        {"first_frame": int(frame_numbers[start]),
         "last_frame": int(frame_numbers[end - 1]),
         "frame_count": int(end - start), "sample_duration_s": (end - start) / rate}
        for start, end in zip(np.where(changes == 1)[0], np.where(changes == -1)[0])
    ]


def inspect(source: Path, output: Path):
    source_bytes = source.read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    with warnings.catch_warnings(record=True) as captured, source.open("rb") as handle:
        warnings.simplefilter("always")
        reader = c3d.Reader(handle)
        metadata = {
            "point_count": int(reader.point_used), "sample_rate_hz": float(reader.point_rate),
            "point_labels": [str(label).strip() for label in reader.point_labels],
            "units": reader.get("POINT:UNITS").string_value.strip(),
            "first_frame": int(reader.first_frame), "last_frame": int(reader.last_frame),
            "analog_channel_count": int(reader.analog_used), "point_scale": float(reader.point_scale),
            "data_block": int(reader.header.data_block),
            "point_frames_parameter": int(reader.get("POINT:FRAMES").uint16_value),
        }
        rows = list(reader.read_frames(check_nan=False))
    if not rows:
        raise ValueError("No frames were decoded")
    if metadata["units"].lower() != "mm":
        raise ValueError("This conversion expects documented mm units; inspect other units explicitly")
    rate = metadata["sample_rate_hz"]
    if rate <= 0:
        raise ValueError("Invalid sampling rate")
    frame_numbers = np.array([row[0] for row in rows], dtype=np.int64)
    points = np.stack([row[1] for row in rows])
    if len(rows) != metadata["point_frames_parameter"]:
        raise ValueError("Decoded frame count differs from POINT:FRAMES")
    if not np.all(np.diff(frame_numbers) == 1):
        raise ValueError("Decoded frame numbers are not consecutive")

    # Independent check against the standard Intel floating-point storage layout.
    # Do not attempt to interpret proprietary CAP/TRB/VC files.
    raw_fourth = None
    independent_check = {"performed": False}
    if metadata["point_scale"] < 0 and metadata["analog_channel_count"] == 0 and reader.proc_type == "INTEL":
        offset = (metadata["data_block"] - 1) * 512
        raw = np.frombuffer(source_bytes, dtype="<f4", offset=offset,
                            count=len(rows) * metadata["point_count"] * 4)
        raw = raw.reshape(len(rows), metadata["point_count"], 4)
        assert np.array_equal(raw[:, :, :3], points[:, :, :3], equal_nan=True)
        raw_fourth = raw[:, :, 3]
        independent_check = {"performed": True, "xyz_match": True,
                             "method": "Standard Intel float32 XYZ + fourth-word layout"}

    relative_times = (frame_numbers - frame_numbers[0]) / rate
    if output.exists():
        existing = json.loads((output / "inspection.json").read_text(encoding="utf-8"))
        if existing.get("source_sha256") != source_hash:
            raise ValueError("Output belongs to a different source revision; choose a new directory")
    output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, output / (source.stem + "_source.c3d"))
    csv_path = output / (source.stem + "_coordinates.csv")
    summaries = []
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["frame", "time_from_export_start_s", "marker", "x_mm", "y_mm", "z_mm",
                         "c3d_residual_scaled", "c3d_camera_mask", "fourth_word_raw_float",
                         "candidate_valid", "quality_status"])
        for marker_index in range(metadata["point_count"]):
            label = metadata["point_labels"][marker_index]
            data = points[:, marker_index]
            xyz = data[:, :3]
            finite = np.all(np.isfinite(xyz), axis=1)
            standard_invalid = (~finite) | (data[:, 3] < 0)
            # This exporter writes the 16-bit -1 bit pattern as positive float 65535.
            # Preserve the raw word and flag it explicitly rather than relying on the reader's sign test.
            exporter_uint16_invalid = np.zeros(len(rows), dtype=bool) if raw_fourth is None else (
                raw_fourth[:, marker_index] == 65535)
            all_zero = np.all(xyz == 0, axis=1)
            # A real point can lie at the origin. Flag, never silently delete, origin rows.
            origin_placeholder_candidate = all_zero & (data[:, 3] == 255) & (data[:, 4] == 127)
            candidate_valid = ~standard_invalid & ~exporter_uint16_invalid & ~all_zero
            for index, frame in enumerate(frame_numbers):
                if standard_invalid[index]:
                    status = "invalid_by_standard_flag_or_nonfinite"
                elif exporter_uint16_invalid[index]:
                    status = "invalid_by_exporter_unsigned_16bit_sentinel"
                elif origin_placeholder_candidate[index]:
                    status = "suspected_unidentified_origin_placeholder"
                elif all_zero[index]:
                    status = "origin_position_requires_review"
                else:
                    status = "candidate_valid_not_independently_verified"
                writer.writerow([int(frame), f"{relative_times[index]:.9f}", label,
                                 *[format(float(v), ".9g") for v in xyz[index]],
                                 float(data[index, 3]), int(data[index, 4]),
                                 "" if raw_fourth is None else float(raw_fourth[index, marker_index]),
                                 int(candidate_valid[index]), status])
            valid_xyz = xyz[candidate_valid]
            adjacent = candidate_valid[:-1] & candidate_valid[1:]
            steps = np.linalg.norm(np.diff(xyz, axis=0), axis=1)[adjacent]
            valid_indices = np.flatnonzero(candidate_valid)
            summary = {
                "marker": label, "standard_invalid_count": int(standard_invalid.sum()),
                "exporter_unsigned_invalid_count": int(exporter_uint16_invalid.sum()),
                "all_zero_count": int(all_zero.sum()),
                "suspected_placeholder_count": int(origin_placeholder_candidate.sum()),
                "zero_runs": runs(all_zero, frame_numbers, rate),
                "candidate_valid_frame_count": int(candidate_valid.sum()),
                "candidate_valid_fraction": float(candidate_valid.mean()),
                "candidate_valid_sample_duration_s": float(candidate_valid.sum()) / rate,
                "interior_gap_count_after_first_candidate": 0 if not len(valid_indices) else int(
                    (~candidate_valid[valid_indices[0]:valid_indices[-1] + 1]).sum()),
                "note": "Candidate validity excludes suspicious origin rows; it is not ground-truth visibility.",
            }
            if len(valid_xyz):
                summary.update({
                    "first_candidate_frame": int(frame_numbers[valid_indices[0]]),
                    "last_candidate_frame": int(frame_numbers[valid_indices[-1]]),
                    "first_candidate_time_s": float(relative_times[valid_indices[0]]),
                    "xyz_min_mm": valid_xyz.min(axis=0).tolist(),
                    "xyz_max_mm": valid_xyz.max(axis=0).tolist(),
                    "xyz_extent_mm": np.ptp(valid_xyz, axis=0).tolist(),
                    "first_candidate_xyz_mm": valid_xyz[0].tolist(),
                    "last_candidate_xyz_mm": valid_xyz[-1].tolist(),
                    "first_last_candidate_distance_mm": float(np.linalg.norm(valid_xyz[-1] - valid_xyz[0])),
                })
            if len(steps):
                summary["adjacent_candidate_step_mm_percentiles_50_95_100"] = np.percentile(steps, [50, 95, 100]).tolist()
            if raw_fourth is not None:
                values, counts = np.unique(raw_fourth[:, marker_index], return_counts=True)
                summary["fourth_word_raw_float_histogram"] = [
                    {"value": float(value), "frames": int(count)} for value, count in zip(values, counts)]
            summaries.append(summary)

    # Reopen the CSV and verify every raw XYZ survived the conversion.
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        exported = list(csv.DictReader(handle))
    assert len(exported) == len(rows) * metadata["point_count"]
    for marker_index in range(metadata["point_count"]):
        selected = exported[marker_index * len(rows):(marker_index + 1) * len(rows)]
        recovered = np.array([[float(row[axis]) for axis in ("x_mm", "y_mm", "z_mm")]
                              for row in selected], dtype=np.float32)
        assert np.array_equal(recovered, points[:, marker_index, :3], equal_nan=True)
        assert [int(row["frame"]) for row in selected] == frame_numbers.tolist()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    assert hashlib.sha256((output / (source.stem + "_source.c3d")).read_bytes()).hexdigest() == source_hash
    report = {
        "source_path": str(source.resolve()), "source_sha256": source_hash,
        "reader": "c3d", "reader_version": importlib.metadata.version("c3d"),
        "metadata": metadata, "decoded_frame_count": len(rows),
        "sample_duration_s_n_over_rate": len(rows) / rate,
        "first_to_last_sample_span_s": float(relative_times[-1]),
        "time_basis": "Derived relative time: (frame - first_export_frame) / nominal rate. Not a hardware timestamp.",
        "reader_warnings": [str(item.message) for item in captured],
        "independent_storage_check": independent_check, "csv_roundtrip_verified": True,
        "source_and_copy_hash_verified": True, "markers": summaries,
        "interpolation_applied": False, "filtering_applied": False, "frames_removed": 0,
        "full_sequence_accepted": False,
        "limitations": [
            "Exporter writes raw fourth-word float 65535 on zero-coordinate frames; this is separately flagged because the reader's signed check does not reject positive 65535.",
            "Leading origin placeholders require replay of the unlabelled source to distinguish missing labels from missing observations.",
            "Zero residual on the remaining frames does not establish zero measurement error or measured camera visibility.",
            "This recording does not verify metric calibration accuracy, cross-device synchronization, hand pose or OakInk compatibility.",
        ],
    }
    (output / "inspection.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    (output / "README.md").write_text(
        "# 单点导出检查\n\n"
        f"源文件：`{source.name}`。采样率 {rate:g} Hz，共 {len(rows)} 帧，单位 mm。\n\n"
        "CSV 保留所有帧及原始 XYZ，包括零值，未补点、滤波或删除帧。"
        "candidate_valid 是待复核的筛选标记，不代表独立验证的测量有效性。\n\n"
        "P001 的第 1–1119 帧均为 (0,0,0)，且原始第四字段为 65535；"
        "这是疑似未识别/占位段，不能算作真实静止于原点，也不能仅按非负 residual 判为有效。"
        "第 1120–3141 帧有非零连续坐标。需在 XINGYING 检查前段是否仍有白色未命名点；"
        "若有，应从前段重新识别并跟踪，再导出新版本。若原始点已缺失，应标无效或重录，不能跨 9 秒插值。\n\n"
        "time_from_export_start_s 由帧号和采样率计算，不是硬件时间戳，不能证明与手套同步。"
        "C3D 的 residual 和 camera mask 不作为该文件的精度或相机可见数量证明。\n\n"
        "检查结果：`inspection.json`。坐标数据：`" + csv_path.name + "`。\n\n"
        "格式依据：[C3D 点数据定义](https://www.c3d.org/HTML/Documents/pointused1.htm)；"
        "[读取库](https://pypi.org/project/c3d/)。\n",
        encoding="utf-8",
    )
    print(json.dumps({"output_directory": str(output.resolve()), "csv": str(csv_path.resolve()),
                      "rate_hz": rate, "frames": len(rows), "markers": summaries,
                      "csv_roundtrip_verified": True}, ensure_ascii=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    inspect(args.source, args.output)
