# kz-can — カート CAN 定義（単一ソース）

カート車載 CAN バスのメッセージ定義を **1 つの人間可読ファイル (`can.yaml`) で管理**し、
そこから DBC / C コード / Python 用定義を **生成**するリポジトリ。

DBC を手書きしないための構成: `can.yaml` だけを編集し、他は生成物。

```
can.yaml ──(tools/gen.py + cantools)──▶ generated/kart.dbc ──▶ generated/kart_can.h / kart_can.c
   ▲ 人間が編集する唯一のソース              │ 汎用ツール用              firmware用Cコード
                                            └──────────────▶ python-can で直接ロード
```

## 構成

```
kz-can/
├── can.yaml               ← ✏️ 人間が編集する唯一のソース（ノード別TX/RX・信号レイアウト）
├── run.sh                 ← can.yaml から全生成物を再生成（venv自動セットアップ込み）
├── tools/
│   ├── gen.py             ← can.yaml → generated/kart.dbc 生成 + ラウンドトリップ自己テスト
│   └── example_usage.py   ← python-can/cantools での decode/encode 例
├── generated/             ← 🤖 生成物（編集禁止・run.sh で再生成）
│   ├── kart.dbc           ← 汎用CANツール用（candump/Vector/PCAN/python-can）
│   ├── kart_can.h / .c    ← firmware用C（`KART_CAN_*_FRAME_ID`, `struct`, `_pack/_unpack`, `_decode`）
└── docs/
    └── can-spec.md        ← 読み物仕様（背景・出典 `file:line`・**要確認事項**）
```

## 使い方

```bash
./run.sh                             # can.yaml から generated/{kart.dbc,kart_can.h,kart_can.c} を再生成
.venv/bin/python tools/example_usage.py        # デコード例
.venv/bin/cantools dump generated/kart.dbc <id> <data>   # 単発デコード
.venv/bin/cantools monitor generated/kart.dbc            # 実バス監視（socketcan）
```

初回は `run.sh` が `uv venv` で `.venv` を作り `cantools`/`pyyaml` を入れる。

## 定義を追加・変更するには

`can.yaml` の該当ノード配下に message/signal を足して `./run.sh` を流すだけ。記法:

```yaml
- name: MyMessage       # メッセージ名（DBC BO_）
  id: 0x123             # アービトレーションID（標準11bit）
  dlc: 8                # バイト長
  cycle_ms: 20          # 送信周期（任意, DBC GenMsgCycleTime）
  rx: [受信ノード名]      # 受信側（ドキュメント用, DBC受信者）
  signals:
    - {name: sig, byte: 0, size: 16, endian: big, type: uint, scale: 0.1, unit: degC}
    #  byte=先頭からのバイト位置 / size=ビット長(8の倍数) / endian=big|little
    #  type=uint|int|float / 物理値 = raw*scale + offset / choices={0: "A", 1: "B"}
```

### YAML の注意（ハマりどころ）
- 指数表記は小数点必須: `1.0e-7`（`1e-7` は文字列扱いになる。gen.py で吸収済みだが明示推奨）
- enum で `OFF`/`ON`/`YES`/`NO` は**クォート必須**（YAML 1.1 が真偽値化する）。gen.py がbool混入を検知してエラーにする。

## firmware での利用（手書き #define の置換）

`generated/kart_can.h` に各メッセージの ID・構造体・pack/unpack・スケール変換が入る:

```c
#include <kart_can.h>
struct kart_can_dc_gyro_xy_t m = { .gyro_x = ..., .gyro_y = ... };
uint8_t buf[8];
kart_can_dc_gyro_xy_pack(buf, &m, sizeof(buf));   // → CAN送信
// 受信側: kart_can_dc_gyro_xy_unpack(&m, data, len);
```

Teensy(dc-firmware)/ESP32(data-logger) の `constants.hpp` の手書き `CAN_ID_*` は
`KART_CAN_*_FRAME_ID` に置き換え可能。ビルドに `generated/kart_can.h`/`.c` を取り込む。

## 対象ノード / IDマップ

`can.yaml` に定義済み（詳細レイアウトは `docs/can-spec.md`）:

| 送信ノード | ID | 概要 |
|---|---|---|
| motec_ecu（外部） | 0x5F0–0x5F4 | エンジンデータ → kart-machine-manager |
| drive_controller | 0x600–0x603 | IMU姿勢 + ギア |
| drive_controller | 0x740〜 | 制御信号（制御ID帯の先頭。0x740 = mode/launch/auto-shift）→ ログ/テレメトリ |
| data_logger | 0x700–0x70E | BMI160+ADS8688+GNSS の120Bバッファ（15分割） |

> **要確認事項**（0x600系の受信者不在, 加速度の単位, BMI160ジャイロY/Zバグ 等）は
> `docs/can-spec.md` の「不整合・注意点」を参照。定義を正とする前に確認すること。
