# kart-can — カート CAN 定義（単一ソース）

カート車載 CAN バスのメッセージ定義を **1 つの人間可読ファイル (`can.yaml`) で管理**し、
そこから DBC / C コードを **生成**するリポジトリ。DBC を手書きしないための構成: `can.yaml` だけを編集し、他は生成物。

```
can.yaml ──(tools/gen.py + cantools)──▶ generated/kart.dbc ──▶ generated/kart_can.h / kart_can.c
   ▲ 人間が編集する唯一のソース              │ 汎用ツール用              firmware用Cコード
                                            └──────────────▶ python-can / cantools で直接ロード
```

システム全体の構成 (どのノードが何を持つか、設計方針、規則上の制約) は
[kart-soft-docs](https://github.com/KART-Software/kart-soft-docs) を参照。
ネットワーク仕様と未決事項は [docs/can-spec.md](docs/can-spec.md)。

## 構成

```
kart-can/
├── can.yaml               ← ✏️ 人間が編集する唯一のソース（ノード別TX/RX・信号レイアウト）
├── run.sh                 ← can.yaml から全生成物を再生成（venv自動セットアップ込み）
├── tools/
│   ├── gen.py             ← can.yaml → generated/kart.dbc 生成 + ラウンドトリップ自己テスト
│   └── example_usage.py   ← python-can/cantools での decode/encode 例
├── generated/             ← 🤖 生成物（編集禁止・run.sh で再生成）
│   ├── kart.dbc           ← 汎用CANツール用（candump/Vector/PCAN/python-can）
│   └── kart_can.h / .c    ← firmware用C（`KART_CAN_*_FRAME_ID`, `struct`, `_pack/_unpack`, `_decode`）
├── library.json           ← PlatformIO ライブラリ定義 (generated/ を srcDir/includeDir)
└── docs/
    └── can-spec.md        ← ネットワーク仕様・移行状態・未決事項
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
  rx: [受信ノード名]      # 受信側（DBC受信者）
  comment: "説明"        # 任意
  signals:
    - {name: sig, byte: 0, size: 16, endian: big, type: uint, scale: 0.1, unit: degC}
    #  byte=先頭からのバイト位置 / size=ビット長(8の倍数) / endian=big|little
    #  type=uint|int|float / 物理値 = raw*scale + offset / choices={0: "A", 1: "B"}
```

### YAML の注意（ハマりどころ）
- 指数表記は小数点必須: `1.0e-7`（`1e-7` は文字列扱いになる。gen.py で吸収済みだが明示推奨）
- enum で `OFF`/`ON`/`YES`/`NO` は**クォート必須**（YAML 1.1 が真偽値化する）。gen.py がbool混入を検知してエラーにする。

## 各ノードでの利用

| ノード | 取り込み方 | 状態 |
|---|---|---|
| drive-controller (Teensy 4.1) | submodule `dc-firmware/lib/kart-can` (PlatformIO ライブラリ) | 使用中 |
| data-logger-zephyr (kmm M コア) | submodule `kart-can`、`apps/can-gw` が `kart_can.h` を include | 使用中 |
| kart-machine-manager (kmm A コア, Python) | `generated/kart.dbc` を cantools でロード | **未使用** (手書きデコードのまま。要移行) |

```c
#include <kart_can.h>
struct kart_can_dc_gyro_xy_t m = { .gyro_x = ..., .gyro_y = ... };
uint8_t buf[8];
kart_can_dc_gyro_xy_pack(buf, &m, sizeof(buf));   // → CAN送信
// 受信側: kart_can_dc_gyro_xy_unpack(&m, data, len);
```

レイアウトを変えたら、各リポジトリの submodule を進めること。

## ノードと ID マップ

ノード名は `can.yaml` の `nodes` キー。kmm (kart-machine-manager ユニット = DEBIX Infinity) は
CAN コントローラを M コアが持つため、CAN 上のノードとしては `data_logger` が kmm を代表する。

| 送信ノード | 実体 | ID | 内容 |
|---|---|---|---|
| `motec_ecu` (外部) | MoTeC M800 | 0x5F0–0x5F4 | エンジンデータ (0x5F1 の battery_voltage は drive_controller も受信) |
| `drive_controller` | Teensy 4.1 (車両後方) | 0x600–0x603 | IMU (IAM-20680HP) + ギア |
| `drive_controller` | 〃 | 0x604–0x605 | APPS/TPS/クラッチ/後ろブレーキ圧の物理値、APPS/TPS 各 2 系統の生値 |
| `drive_controller` | 〃 | 0x606–0x609 | 後ろ左右ストローク、車輪速 4 輪 (km/h と生パルスカウント)、エンジン回転数 |
| `drive_controller` | 〃 | 0x60A | 適用中の制御状態・リレー状態・Shutdown ループ状態 |
| `data_logger` | kmm M コア (車両前方) | 0x700–0x701 | ADS8688 ADC 8ch (前方センサー。ch 割り当ては未定) |
| `data_logger` | 〃 | 0x740 | Control: コックピットスイッチ (ETC モード / ローンチ / オートシフト / セル) → drive_controller、33 ms |
| `data_logger` | 〃 | 0x741 | Shift: シフトパドル上下 → drive_controller、10 ms |

受信: `drive_controller` は 0x740、0x741 と 0x5F1、`kart_machine_manager` (A コア) は M コアのゲートウェイ経由で全フレーム。

### 制御信号の設計方針

- 制御用 ID は 0x740 から順に割り当てる。
- 即時性を求めない制御信号 (0x740) は 33 ms 周期、シフトパドル (0x741) だけ 10 ms 周期で送る。受信側は途絶でフェイルセーフに落とす (docs/can-spec.md)。
- `can.yaml` には生成物 (DBC / C ヘッダ) に現れる情報だけを書く。送信タイミングの詳細やフェイルセーフ、移行状態は docs/can-spec.md に書く。
- APPS と TPS は drive-controller にアナログ直結し、CAN には物理値と生値をログ用に流すだけ。ETC の制御入力を CAN に依存させない。
- Shutdown Circuit (BOTS / BSPD / マスタースイッチ) は規則上ハードワイヤ必須で、CAN には**載せない**。状態の監視のみ 0x60A で送る。

## 移行状態 (2026-10 時点)

- コックピットスイッチは現在 drive-controller の GPIO に直結されている。drive-controller は自分のスイッチ状態を 0x740 (DLC 3) で送信しており、CAN からの制御入力 (`CONTROL_INPUT_VIA_CAN`) は凍結中。
- 目標構成では kmm M コア (data-logger-zephyr) がスイッチ 6 系統を取得して 0x740 (ETC モード、ローンチ、オートシフト、セル) と 0x741 (シフト上下) で送り、drive-controller が受信側になる。切替時に drive-controller の 0x740 送信は止め、状態は 0x60A で送る。
- 詳細と未決事項は [docs/can-spec.md](docs/can-spec.md)。
