#!/usr/bin/env python3
"""kart.dbc を python-can / cantools で使う最小例。
   実行:  .venv/bin/python tools/example_usage.py
"""
from pathlib import Path

import cantools

DBC = Path(__file__).resolve().parent.parent / "generated" / "kart.dbc"
db = cantools.database.load_file(str(DBC))

# --- デコード例: MoTeC Engine1 (0x5F0) ---
# rpm=6000, throttle=42.0%, water=95.0, oil=110.0 のフレームを作ってデコード
msg = db.get_message_by_name("MoTeC_Engine1")
data = msg.encode({"rpm": 6000, "throttle": 42.0, "water_temp": 95.0, "oil_temp": 110.0})
print("0x%03X %s -> %s" % (msg.frame_id, data.hex(" "), db.decode_message(msg.frame_id, data)))

# --- デコード例: drive-controller GyroXY (0x600, float32 LE) ---
msg = db.get_message_by_name("DC_GyroXY")
data = msg.encode({"gyro_x": 12.5, "gyro_y": -3.0})
print("0x%03X %s -> %s" % (msg.frame_id, data.hex(" "), db.decode_message(msg.frame_id, data)))

# --- 実バスから読む場合（socketcan can0）---
# import can
# bus = can.Bus(channel="can0", interface="socketcan")
# for frame in bus:
#     try:
#         print(db.decode_message(frame.arbitration_id, frame.data))
#     except KeyError:
#         pass  # DBC 未定義ID
