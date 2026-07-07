#!/usr/bin/env python3
"""can.yaml -> kart.dbc を生成する薄いラッパー（cantools が重い処理を担当）。

やっていること:
  1. can.yaml を読む（人間が編集する唯一のソース）
  2. cantools の Database / Message / Signal オブジェクトを組み立てる
     - byte オフセット + endian から DBC のビット番号へ変換
     - data_logger は 120B バッファを byte//8 で 15 フレームへ自動分割
  3. kart.dbc を出力
  4. ラウンドトリップ自己テスト（エンコード→バイト列→デコード）でレイアウト検証

C ヘッダ生成:  cantools generate_c_source generated/kart.dbc   （run.sh 参照）
python-can:    db = cantools.database.load_file("generated/kart.dbc"); db.decode_message(id, data)
"""
from __future__ import annotations
import struct
import sys
from pathlib import Path

import yaml
from cantools.database.can import Database, Message, Node, Signal
from cantools.database.conversion import BaseConversion

ROOT = Path(__file__).resolve().parent.parent  # tools/ の 1 つ上 = リポジトリルート
YAML_PATH = ROOT / "can.yaml"
GENERATED_DIR = ROOT / "generated"
DBC_PATH = GENERATED_DIR / "kart.dbc"


def byte_order(endian: str) -> str:
    return "big_endian" if endian == "big" else "little_endian"


def start_bit(byte: int, size: int, endian: str) -> int:
    """バイト境界に揃った信号の DBC 開始ビットを返す。
    little(Intel)  : LSB のビット位置 = byte*8
    big(Motorola)  : MSB のビット位置 = byte*8 + 7 （sawtooth 番号付け）
    """
    if size % 8 != 0:
        raise ValueError(f"size must be a multiple of 8 (byte-aligned only): {size}")
    return byte * 8 if endian == "little" else byte * 8 + 7


def build_signal(sig: dict, default_endian: str, byte_in_frame: int | None = None) -> Signal:
    endian = sig.get("endian", default_endian)
    size = sig["size"]
    byte = byte_in_frame if byte_in_frame is not None else sig["byte"]
    typ = sig.get("type", "uint")
    is_float = typ == "float"
    is_signed = typ == "int"
    # PyYAML(1.1) は "1e-7" を文字列にするため数値へ強制変換
    scale = 1 if is_float else float(sig.get("scale", 1))
    offset = float(sig.get("offset", 0))
    if scale == int(scale):
        scale = int(scale)
    if offset == int(offset):
        offset = int(offset)
    choices = sig.get("choices")
    if choices is not None:
        for v in choices.values():
            if isinstance(v, bool):  # YAML 1.1 が ON/OFF/YES/NO を真偽値化した兆候
                raise ValueError(
                    f"signal {sig['name']}: choices 値が真偽値になっています。"
                    f'YAMLで "OFF"/"ON" のようにクォートしてください。'
                )
        choices = {int(k): str(v) for k, v in choices.items()}
    conversion = BaseConversion.factory(
        scale=scale, offset=offset, choices=choices, is_float=is_float
    )
    return Signal(
        name=sig["name"],
        start=start_bit(byte, size, endian),
        length=size,
        byte_order=byte_order(endian),
        is_signed=is_signed,
        conversion=conversion,
        unit=sig.get("unit"),
        comment=sig.get("comment"),
        receivers=sig.get("_receivers", []),
    )


def build_message(msg: dict, sender: str, default_endian: str) -> Message:
    rx = msg.get("rx", [])
    signals = []
    for s in msg["signals"]:
        s = dict(s, _receivers=rx)
        signals.append(build_signal(s, default_endian))
    return Message(
        frame_id=msg["id"],
        name=msg["name"],
        length=msg["dlc"],
        signals=signals,
        senders=[sender],
        cycle_time=msg.get("cycle_ms"),
        comment=msg.get("comment"),
    )


def build_reassembled(node_name: str, r: dict) -> list[Message]:
    """data_logger: 絶対バイトオフセットの信号列を base_id+i の各フレームへ分割。"""
    base, fb, dlc = r["base_id"], r["frame_bytes"], r["dlc"]
    cyc, rx = r.get("cycle_ms"), r.get("rx", [])
    frames: dict[int, list] = {}
    for sig in r["signals"]:
        b, size = sig["byte"], sig["size"]
        fi, inb = divmod(b, fb)
        if inb + size // 8 > fb:
            raise ValueError(
                f"signal {sig['name']} @byte {b} (size {size}) crosses a "
                f"{fb}-byte frame boundary — DBC では表現できません"
            )
        frames.setdefault(fi, []).append((sig, inb))

    messages = []
    for fi in sorted(frames):
        fid = base + fi
        signals = []
        for sig, inb in frames[fi]:
            s = dict(sig, _receivers=rx)
            signals.append(build_signal(s, default_endian="little", byte_in_frame=inb))
        messages.append(
            Message(
                frame_id=fid,
                name=f"DL_{fid:03X}",
                length=dlc,
                signals=signals,
                senders=[node_name],
                cycle_time=cyc,
                comment=f"data-logger 生バッファ byte {fi * fb}-{fi * fb + fb - 1}（再構成の一部）",
            )
        )
    return messages


def build_database(spec: dict) -> Database:
    node_specs = spec["nodes"]
    # 送信ノード + rx に現れる受信ノードをすべて BU_ として宣言
    node_names = set(node_specs)
    for n in node_specs.values():
        for m in n.get("messages", []):
            node_names.update(m.get("rx", []))
        if "reassembled" in n:
            node_names.update(n["reassembled"].get("rx", []))
    nodes = []
    for name in sorted(node_names):
        spec_n = node_specs.get(name, {})
        desc = spec_n.get("description")
        if spec_n.get("external"):
            desc = f"[外部ノード] {desc or ''}".strip()
        nodes.append(Node(name=name, comment=desc))

    messages = []
    for name, node in node_specs.items():
        default_endian = node.get("defaults", {}).get("endian", "little")
        for m in node.get("messages", []):
            messages.append(build_message(m, name, default_endian))
        if "reassembled" in node:
            messages.extend(build_reassembled(name, node["reassembled"]))

    messages.sort(key=lambda m: m.frame_id)
    return Database(messages=messages, nodes=nodes)


# --------------------------------------------------------------------------
# ラウンドトリップ自己テスト（エンディアン・float・スケーリングの検証）
# --------------------------------------------------------------------------
def run_selftests(db: Database) -> bool:
    ok = True

    def check(cond, label):
        nonlocal ok
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
        ok = ok and cond

    def approx(a, b, tol=1e-3):
        return abs(a - b) <= tol * max(1, abs(b))

    # 1) big-endian uint16 + scaling （Motorola 開始ビットの検証）
    m = db.get_message_by_name("MoTeC_Engine1")
    data = m.encode({"rpm": 4660, "throttle": 45.0, "water_temp": 98.0, "oil_temp": 110.0})
    check(data[0] == 0x12 and data[1] == 0x34, "Engine1 rpm=4660 -> big-endian bytes 0x12 0x34")
    dec = m.decode(data)
    check(dec["rpm"] == 4660 and approx(dec["throttle"], 45.0), "Engine1 decode rpm/throttle")

    # 2) little-endian float32 （Intel + IEEE754）
    m = db.get_message_by_name("DC_GyroXY")
    data = m.encode({"gyro_x": 1.5, "gyro_y": -2.25})
    check(data[0:4] == struct.pack("<f", 1.5), "GyroXY gyro_x=1.5 -> little-endian float bytes")
    dec = m.decode(data)
    check(approx(dec["gyro_x"], 1.5) and approx(dec["gyro_y"], -2.25), "GyroXY decode floats")

    # 3) float + uint8 混在フレーム、gear=0xFF
    m = db.get_message_by_name("DC_GyroZGear")
    data = m.encode({"gyro_z": 10.0, "gear": 255})
    check(len(data) == 5 and data[4] == 0xFF, "GyroZGear dlc=5, gear byte=0xFF")

    # 4) big-endian signed int16 （data-logger BMI160）
    m = db.get_message_by_name("DL_700")
    data = m.encode({"dl_accel_x": -1000, "dl_accel_y": 2000, "dl_accel_z": -3000, "dl_gyro_x": 500})
    check(data[0:2] == struct.pack(">h", -1000), "DL_700 accel_x=-1000 -> big-endian signed int16")
    dec = m.decode(data)
    check(dec["dl_accel_x"] == -1000 and dec["dl_gyro_x"] == 500, "DL_700 decode signed ints")

    # 5) little-endian signed int32 + 1e-7 スケール （data-logger GPS lat/height）
    m = db.get_message_by_name("DL_707")
    lat = 35.6812345
    data = m.encode({"gps_lat": lat, "gps_height": -12345})
    check(data[0:4] == struct.pack("<i", round(lat / 1e-7)), "DL_707 gps_lat -> little-endian int32 x1e-7")
    dec = m.decode(data)
    check(approx(dec["gps_lat"], lat, 1e-6) and dec["gps_height"] == -12345, "DL_707 decode lat/height")

    # 6) 統合制御フレーム KartControl: enum + マルチバイト (byte0/1/2)
    m = db.get_message_by_name("KartControl")
    data = m.encode({"etc_mode": "MOTOR_OFF", "launch_active": "ACTIVE", "auto_shift": "AUTO"})
    check(data[0] == 4 and data[1] == 1 and data[2] == 1, "KartControl -> bytes [0x04,0x01,0x01]")
    dec = m.decode(data)
    check(
        str(dec["etc_mode"]) == "MOTOR_OFF" and str(dec["auto_shift"]) == "AUTO",
        "KartControl decode enum names",
    )

    return ok


def main() -> int:
    spec = yaml.safe_load(YAML_PATH.read_text())
    db = build_database(spec)

    GENERATED_DIR.mkdir(exist_ok=True)
    DBC_PATH.write_text(db.as_dbc_string())
    n_sig = sum(len(m.signals) for m in db.messages)
    print(f"生成: {DBC_PATH.name}  ({len(db.nodes)} nodes, {len(db.messages)} messages, {n_sig} signals)")
    for m in db.messages:
        tx = ",".join(m.senders) if m.senders else "-"
        print(f"  0x{m.frame_id:03X}  {m.name:<16} dlc={m.length}  tx={tx}  ({len(m.signals)} sig)")

    print("\nラウンドトリップ自己テスト:")
    ok = run_selftests(db)
    print("\n=> " + ("ALL PASS ✅" if ok else "FAILED ❌"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
