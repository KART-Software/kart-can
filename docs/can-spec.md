# カート CAN 通信仕様

`data-logger` / `drive-controller` / `kart-machine-manager` の 3 リポジトリのソースコードから抽出・統合した、カート車載 CAN ネットワークの仕様書。
すべて実装（as-implemented）ベース。ドキュメント記載値ではなくコードの実値を採用し、矛盾点は「[注意点](#7-不整合注意点action-items)」に列挙した。

> 生成日: 2026-07-06 / 出典: 各リポジトリのソース（引用は `file:line`）

---

## 1. 概要（ネットワーク構成）

```
                    ┌─────────────────────────────┐
                    │       CAN バス (1 Mbps)       │
                    │   Classic CAN 2.0 / 11bit ID  │
                    └─────────────────────────────┘
   0x200/0x300/0x400 │        │0x5F0-0x5F4   │0x600-0x603   │0x700-0x70E
   （制御指令）        ▼        ▼              ▲              ▲
  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
  │ IST/コックピット │→│drive-controller│  │  MoTeC ECU    │  │ data-logger  │
  │ (上位ECU・外部)  │  │  (Teensy4.1)  │  │  (外部・エンジン)│  │ (ESP32-S3)   │
  └──────────────┘  │ 駆動系ECU      │  └──────────────┘  │ センサ送信専用 │
                    │ TX:0x600-603   │        │              └──────────────┘
                    │ RX:0x200/300/400│       │0x5F0-0x5F4          │0x700-0x70E
                    └──────────────┘        ▼                     ▼
                                      ┌──────────────────────────────────┐
                                      │       kart-machine-manager         │
                                      │       (Raspberry Pi / インパネ)      │
                                      │  RX 監視 + CAN→UDP ゲートウェイ       │
                                      │  実バスへは送信しない（DEBUG時のみ模擬）│
                                      └──────────────────────────────────┘
```

- **物理層は 3 ノードとも 1 Mbps・Classic CAN 2.0・標準 11bit ID で一致**（唯一 Arduino モックのみ 500 kbps → [注意点](#7-不整合注意点action-items)）。
- CAN FD・拡張 29bit ID は**どのノードでも未使用**。
- リポジトリに `.dbc` 等の共通 CAN データベースは**存在しない**（`kart-machine-manager` にある `dl1.dbc` は未使用の参照資料）。ID・レイアウトはすべてソース内の定数／構造体で管理。

---

## 2. バス設定

| 項目 | data-logger | drive-controller | kart-machine-manager | 備考 |
|---|---|---|---|---|
| MCU / コントローラ | ESP32-S3 内蔵 **TWAI** | Teensy 4.1 (i.MX RT1062) **FlexCAN_T4 / CAN3** | Raspberry Pi + `python-can` | |
| プロトコル | Classic CAN 2.0 | Classic CAN 2.0 | Classic CAN 2.0 | FD 不使用 |
| ビットレート | **1 Mbps** | **1 Mbps** | (未指定・OSで設定) | 実バス = 1 Mbps |
| ID 形式 | 標準 11bit | 標準 11bit | 標準 11bit (`is_extended_id=False`) | |
| インタフェース | TWAI NORMAL | FlexCAN CAN3 | socketcan `can0`（本番）/ virtual `debug`（DEBUG） | |
| 物理ピン | TX=GPIO35 / RX=GPIO36 | CAN3 = pin 30/31 | (SBC のCANインタフェース) | |
| フィルタ | 全受け入れ(実質送信専用) | ハード無し・ソフトでID判定 | listener でID判定 | |
| 送信バッファ | tx_queue 15 | TX_SIZE_16 / RX_SIZE_256 (FIFO) | — | |
| 送信方式 | **単発・再送なし** (`ss=1`, timeout 0) | 通常送信 | 本番は送信なし | data-logger は取りこぼし得る |

引用: data-logger `src/can/can.hpp:18`, `src/can/can.cpp:5-31`, `src/config.hpp:32-33` / drive-controller `src/constants.hpp:165`, `src/can/can_bus.hpp:19`, `can_bus.cpp:6` / kart-machine-manager `app/src/can/can_master.py:15-25`。

> **サンプルポイント** は各ドライバのデフォルト（ESP-IDF `TWAI_TIMING_CONFIG_1MBITS()` ≒80% / FlexCAN 内部既定）で、コード内に明示設定なし。

---

## 3. ノードと役割

| ノード | 役割 | 送信 (TX) | 受信 (RX) |
|---|---|---|---|
| **drive-controller** (Teensy 4.1) | 駆動系 ECU。電子スロットル(ETC)・オートシフタ・ローンチ制御 | `0x600`–`0x603`（IMU姿勢+ギア, 16ms周期） | `0x200`/`0x300`/`0x400`（モード/ローンチ/オートシフト指令） |
| **data-logger** (ESP32-S3) | センサ送信専用（BMI160 IMU + ADS8688 ADC + u-blox GNSS）。**受信経路なし** | `0x700`–`0x70E`（120Bバッファを15分割, ~30Hz） | なし |
| **kart-machine-manager** (Raspberry Pi) | インパネ表示 + **CAN→UDP ゲートウェイ**（受信フレームをクラウド転送）。**実バスへは送信しない** | なし（DEBUG時のみ ECU を模擬送信） | `0x5F0`–`0x5F4`（表示用にデコード）, `0x700`–`0x70E`（生のままUDP転送） |
| **MoTeC ECU** (外部・本リポジトリ外) | エンジン ECU | `0x5F0`–`0x5F4`（エンジンデータ） | — |
| **IST/コックピット** (外部・上位ECU) | ドライバ操作の指令元 | `0x200`/`0x300`/`0x400` | — |

- `drive-controller` の launch control は通常ビルドでは**無効**（`-DLAUNCH_CONTROL_ENABLED` 未定義）。`0x300` は受信・解釈されるが FSM は動かない (`main.cpp:202-212`)。

---

## 4. メッセージ ID マップ（ネットワーク全体）

| ID | 名称 | 送信元 → 受信先 | DLC | 形式 | 周期 |
|---|---|---|---|---|---|
| `0x200` | MODE_SELECT（ETCモード指令） | IST/上位ECU → drive-controller | ≥1 (byte0) | 11bit | ハートビート (≤200ms) |
| `0x300` | LAUNCH_CTRL（ローンチON/OFF） | IST/上位ECU → drive-controller | ≥1 (byte0) | 11bit | ハートビート (≤200ms) |
| `0x400` | AUTO_SHIFT（オートシフトON/OFF） | IST/上位ECU → drive-controller | ≥1 (byte0) | 11bit | ハートビート (≤200ms) |
| `0x5F0` | エンジン1（RPM/スロットル/水温/油温） | MoTeC ECU → kart-machine-manager | 8 | 11bit | 実機不明（模擬 33ms） |
| `0x5F1` | エンジン2（油圧/ギア電圧/バッテリ/λ） | MoTeC ECU → kart-machine-manager | 8 | 11bit | 同上 |
| `0x5F2` | エンジン3（吸気圧/燃圧/ブレーキ圧） | MoTeC ECU → kart-machine-manager | 8 | 11bit | 同上 |
| `0x5F3` | ステータス（ファン/ISTシフト/入出力RPM） | MoTeC ECU → kart-machine-manager | 8 | 11bit | 同上 |
| `0x5F4` | 追加温度（油温2/油温3/クーラント温） | MoTeC ECU → kart-machine-manager | **6** | 11bit | 同上（表示デコードなし・UDP転送のみ） |
| `0x600` | GYRO_XY（ジャイロX,Y） | drive-controller → *(消費者不明)* | 8 | 11bit | 16ms (~62.5Hz) |
| `0x601` | GYRO_Z_GEAR（ジャイロZ+ギア） | drive-controller → *(消費者不明)* | **5** | 11bit | 16ms |
| `0x602` | ACCEL_XY（加速度X,Y） | drive-controller → *(消費者不明)* | 8 | 11bit | 16ms |
| `0x603` | ACCEL_Z（加速度Z） | drive-controller → *(消費者不明)* | **4** | 11bit | 16ms |
| `0x700`–`0x70E` | data-logger センサバースト（15フレーム） | data-logger → kart-machine-manager | 8 | 11bit | ~30Hz バースト（フレーム間 ~1ms） |

> `0x600`–`0x603` は本 3 リポジトリ内に受信側がいない。詳細は[注意点](#7-不整合注意点action-items) を参照。

---

## 5. メッセージ詳細（信号レイアウト）

### 5.1 制御指令: `0x200` / `0x300` / `0x400`（→ drive-controller）

いずれも **byte0 のみ使用**（`len>=1` が条件）。上位 ECU からの周期ハートビートとして扱われ、**200ms 途絶でフェイルセーフ**が働く。
引用: `drive-controller/dc-firmware/src/can/can_data.cpp:34-75`, `src/constants.hpp:171-180`。

| ID | byte0 の意味 | フェイルセーフ (200ms途絶時) |
|---|---|---|
| `0x200` MODE_SELECT | ETC モード enum `CanEtcMode`: `1`=CALIB, `2`=NORMAL, `3`=RESTRICTED, `4`=MOTOR_OFF。`0`(未指定)/不明値は無視（現モード維持） | NORMAL へ復帰。ただし **MOTOR_OFF はラッチ**（CAN喪失でも解除しない） |
| `0x300` LAUNCH_CTRL | `0x01`=launch active、その他=false | `launchActive=false` |
| `0x400` AUTO_SHIFT | `0x01`=オート(ON)、その他=マニュアル(OFF) | `autoShiftActive=false`（マニュアル） |

- `CanEtcMode` は proto の `dc.EtcMode`（UNSPECIFIED=0, CALIB=1, NORMAL=2, RESTRICT=3, MOTOR_OFF=4, `spec/proto/drive_controller.proto:12-18`）と数値一致（C++ は `RESTRICTED`、proto は `RESTRICT` と綴り差）。
- RX 側は DLC を byte0 以外検証しないため、送信側 DLC は ≥1 なら自由。

### 5.2 MoTeC エンジンデータ: `0x5F0`–`0x5F4`（MoTeC → kart-machine-manager）

**ビッグエンディアン、各信号 uint16（2バイト）**。送信側は `int(値×係数) & 0xFFFF` を BE で格納、受信側は係数で除算して物理値化。
引用（エンコード=模擬送信 / デコード=表示）: `kart-machine-manager/app/src/can/mock_can_sender.py:42-84` / `app/src/can/can_listeners.py:34-66`。

**`0x5F0`（DLC 8）**
| byte | 信号 | 型 | 係数 | 単位 |
|---|---|---|---|---|
| 0–1 | rpm | u16 BE | ×1 | rpm |
| 2–3 | throttlePosition | u16 BE | ÷10 | % |
| 4–5 | waterTemp | u16 BE | ÷10 | °C |
| 6–7 | oilTemp | u16 BE | ÷10 | °C |

**`0x5F1`（DLC 8）**
| byte | 信号 | 係数 | 単位 |
|---|---|---|---|
| 0–1 | oilPress | ÷10 | (圧力) |
| 2–3 | gearVoltage | ÷1000 | V |
| 4–5 | batteryVoltage | ÷100 | V |
| 6–7 | lambda | ÷1000（模擬のみ・表示側は未デコード） | λ |

**`0x5F2`（DLC 8）**
| byte | 信号 | 係数 | 単位 |
|---|---|---|---|
| 0–1 | manifoldPressure | ÷10（模擬のみ・表示側未デコード） | kPa |
| 2–3 | fuelPress | ÷10 | (圧力) |
| 4–5 | brakePress front | ÷10 | (圧力) |
| 6–7 | brakePress rear | ÷10 | (圧力) |

**`0x5F3`（DLC 8）**
| byte | 信号 | 内容 |
|---|---|---|
| 0–1 | fanEnabled | ON時 `\x00\x01` / OFF時 `\x00\x00`（表示側は `data[1]` を bool 化） |
| 2–3 | IST シフト状態 enum | `(istUp,istDown)`: 0=(F,F), 1=(F,T), 2=(T,F), 3=(T,T)（表示側未デコード） |
| 4–5 | inputRpm | u16 BE ×1（表示側未デコード） |
| 6–7 | outputRpm | u16 BE ×1（表示側未デコード） |

**`0x5F4`（DLC 6）** — 表示デコードなし・UDP 転送のみ
| byte | 信号 | 係数 | 単位 |
|---|---|---|---|
| 0–1 | oilTemperature2 | ÷10 | °C |
| 2–3 | oilTemperature3 | ÷10 | °C |
| 4–5 | coolantTemperature | ÷10 | °C |

> 表示側の温度デコードは整数切り捨て `//10`、スロットル等は浮動小数 `/10`（実装差, `can_listeners.py:41,44`）。

### 5.3 drive-controller 姿勢テレメトリ: `0x600`–`0x603`

**すべて float32・リトルエンディアン**（Cortex-M7 上の `memcpy`、スケーリングなしで物理値を直接格納）。
引用: `drive-controller/dc-firmware/src/can/can_data.cpp:5-32`, `src/constants.hpp:167-170`。

| ID | DLC | byte 0–3 | byte 4– |
|---|---|---|---|
| `0x600` GYRO_XY | 8 | gyro_x (f32 LE, dps) | gyro_y (f32 LE, dps) @4 |
| `0x601` GYRO_Z_GEAR | 5 | gyro_z (f32 LE, dps) | gear (uint8) @4 |
| `0x602` ACCEL_XY | 8 | accel_x (f32 LE) | accel_y (f32 LE) @4 |
| `0x603` ACCEL_Z | 4 | accel_z (f32 LE) | — |

- **ジャイロ単位 = dps**（IAM20680 ±2000dps, `1/16.4 dps/LSB`, `iam20680hp.cpp:53,78`）。
- **加速度単位は要確認**: ヘッダコメント (`can_data.hpp:9`) は m/s² だが、実データはドライバ由来で **mg（ミリG, `1000/2048 mg/LSB`）**。変換コードは存在しない → [注意点](#7-不整合注意点action-items)。
- **gear** (`0x601` byte4): `-1`=不明→`0xFF` 送信、`0`=ニュートラル、`1`–`6`=ギア段。
- DLC 未満のバイトは 0 埋め（バッファを `{}` でクリア）。

### 5.4 data-logger センサバースト: `0x700`–`0x70E`

**セマンティックな per-ID 意味はない**。120 バイトの平坦バッファを 8 バイト毎に分割し `0x700 + i`（i=0..14）で連番送信するだけ。受信側は **ID 順に 15 フレームを連結してから** 120 バイト構造を解釈する必要がある（シーケンス番号・タイムスタンプ・CRC なし）。
引用: `data-logger/src/can/can_master.cpp:14-26`, `src/can/can_master.hpp:9-16`。

**⚠ バッファ内でエンディアン混在**: BMI160/ADS8688 は**ビッグエンディアン**、GPS ブロックは u-blox 由来の**リトルエンディアン**。

#### 120 バイトバッファ構造

**bytes 0–11: BMI160 IMU**（int16, ビッグエンディアン, 生カウント）
| byte | 信号 | 備考 |
|---|---|---|
| 0–1 | accel.x | ±2g, ≒16384 LSB/g |
| 2–3 | accel.y | |
| 4–5 | accel.z | |
| 6–7 | gyro.x | ±250dps, ≒131.2 LSB/(°/s) |
| 8–9 | gyro.y **であるべき（実際は gyro.x を重複送信＝バグ）** | 🐛 `bmi160.cpp:70-73` |
| 10–11 | gyro.z **であるべき（実際は gyro.x を重複送信＝バグ）** | 🐛 gyro.y/z は送信されない |

**bytes 12–27: ADS8688 ADC**（uint16, ビッグエンディアン, 生カウント）
| byte | 信号 |
|---|---|
| 12–13 … 26–27 | ADC ch0 … ch7（2バイト×8ch） |

- レンジ RANGE_4 = 0–1.25×VREF（VREF=4.096V）→ **0–5.12V**。電圧換算 `V = raw × 7.8125e-5`（=5.12/65536 V/LSB, `ads8688.cpp:67`）。ファームは生カウント送信。

**bytes 28–119: u-blox UBX-NAV-PVT（92 バイト, リトルエンディアン）**
UBX ヘッダ6バイトを除いたペイロードをそのまま格納（NEO-M8U, 20Hz）。バッファ byte = `28 + UBXペイロードオフセット`。主要フィールド:

| UBX off | buffer byte | フィールド | 型 | スケール/単位 |
|---|---|---|---|---|
| 0 | 28–31 | iTOW | U4 | ms |
| 4 | 32–37 | year/month/day/hour/min | — | UTC |
| 10 | 38 | sec | U1 | s |
| 11 | 39 | valid | X1 | bitfield |
| 20 | 48 | fixType | U1 | 0=no fix,2=2D,3=3D,4=GNSS+DR,5=time |
| 21 | 49 | flags | X1 | b0 gnssFixOK 他 |
| 23 | 51 | numSV | U1 | 使用衛星数 |
| 24 | 52–55 | lon | I4 | 1e-7 deg |
| 28 | 56–59 | lat | I4 | 1e-7 deg |
| 32 | 60–63 | height | I4 | mm（楕円体高） |
| 36 | 64–67 | hMSL | I4 | mm（海抜） |
| 40 | 68–71 | hAcc | U4 | mm |
| 44 | 72–75 | vAcc | U4 | mm |
| 48 | 76–79 | velN | I4 | mm/s（北） |
| 52 | 80–83 | velE | I4 | mm/s（東） |
| 56 | 84–87 | velD | I4 | mm/s（下） |
| 60 | 88–91 | gSpeed | I4 | mm/s（対地速度） |
| 64 | 92–95 | headMot | I4 | 1e-5 deg |
| 68 | 96–99 | sAcc | U4 | mm/s |
| 72 | 100–103 | headAcc | U4 | 1e-5 deg |
| 76 | 104–105 | pDOP | U2 | 0.01 |
| 78 | 106 | flags3 (invalidLlh 他) | X1 | `getInvalidLlh()` 参照 |
| 84 | 112–115 | headVeh | I4 | 1e-5 deg |
| 88 | 116–117 | magDec | I2 | 0.01 deg |
| 90 | 118–119 | magAcc | U2 | 0.01 deg |

> GPS 各フィールドのオフセットは標準 u-blox M8 UBX-NAV-PVT 仕様に基づく（SparkFun ライブラリのサブモジュールが未初期化のため構造体を直接読めず、`GPS_DATA_LENGTH=92` と `printPvtData()` の参照フィールドで裏取り済み）。

---

## 6. モック（kart-machine-manager によるバス模擬）

`kart-machine-manager` は実バスへ送信しないが、開発用に **MoTeC ECU（`0x5F0`–`0x5F4`）を模擬送信**する 3 種のモックを持つ。**data-logger 系（`0x700`–`0x70E`）や drive-controller 系（`0x600`–`0x603`）は模擬しない**（＝DEBUG 時 UDP ペイロードでは 0 のまま）。

| モック | 実装 | インタフェース | ビットレート | 生成 ID | 周期 |
|---|---|---|---|---|---|
| in-process | `mock_can_sender.py` | virtual `debug` | (メモリ内) | `0x5F0`–`0x5F4` | 33ms |
| can-mock-py | `can-mock-py/` | slcan（CANable 等 `/dev/ttyACM0`） | **1 Mbps** 既定 | `0x5F0`–`0x5F4` | 33ms |
| can-mock (Arduino) | `can-mock/` | UNO + MCP2515 | **500 kbps** ⚠ | `0x5F0`,`0x5F1`,`0x5F2` のみ（`0x5F2`は DLC4） | 30ms |

---

## 7. 不整合・注意点（Action Items）

コード横断で見つかった、仕様確定・修正の判断が要る箇所。

1. **`0x600`–`0x603`（drive-controller の IMU/ギア）の受信側が本 3 リポジトリに存在しない。** `kart-machine-manager` が listen するのは `0x5F0`–`0x5F4` と `0x700`–`0x70E` のみで、`0x600` 系は含まれない (`can_listeners.py:74-98`)。実際に誰が消費するのか（別 ECU／将来用）要確認。
2. **ID 範囲の重複懸念。** drive-controller は `0x600`–`0x603`（標準11bit）を送信する一方、`kart-machine-manager` の参照 DBC `dl1.dbc` は `0x600`–`0x60F`（**29bit 拡張**）を定義。フレーム形式が違うため物理衝突はしないが、番号帯が重なる。`dl1.dbc` はコード未使用の参照資料 → 本仕様の正とはしない。
3. **ビットレート不一致。** 実ノード（data-logger / drive-controller）と can-mock-py は 1 Mbps だが、**Arduino モックのみ 500 kbps**。本番 socketcan は OS 側設定でコードに明記なし。実バス = **1 Mbps** で統一すべき（Arduino モックは実バス接続時に要変更）。
4. **加速度単位の食い違い（drive-controller `0x602`/`0x603`）。** ヘッダコメントは m/s² だが実データは **mg**。受信側デコーダと単位を突き合わせて確定要。
5. **BMI160 ジャイロ Y/Z が送信されていない（data-logger バグ）。** `0x700` 系 buffer byte 8–11 が gyro.x の重複。`bmi160.cpp:70-73` を `gyro.y`/`gyro.z` に修正要。
6. **data-logger フレームはトランスポート分割のみ**でセマンティクスなし・シーケンス/タイムスタンプ/CRC なし・単発送信で再送なし。取りこぼし時の欠落・部分更新に注意。受信側は 15 フレーム全て揃えてから解釈が必要。
7. **`0x5F0`–`0x5F4` の一部フィールドが表示側で未デコード**（lambda, manifoldPressure, IST シフト状態, input/output RPM）。UDP へは転送されるが GUI には出ない。
8. **`0x5F4` と `0x700`–`0x70E` は生のまま UDP 転送のみ**で CAN 上の意味付けデコードがない。data-logger の 120 バイト構造は `kart-machine-manager` 側では解釈されていない。
9. **実機 MoTeC の送信周期は本リポジトリ内に定義なし**（模擬は 33ms）。実 ECU 設定と要突き合わせ。
10. **AGENTS.md 記載が古い**: `CanMaster.__init__` が `sudo` で socketcan を立ち上げるとあるが、実コードは `can0` を開くだけ（ブリングアップは外部）。

---

## 付録: 主要な定義箇所（引用）

| 定義 | ファイル |
|---|---|
| CAN ID / ビットレート / タイムアウト定数 | `drive-controller/dc-firmware/src/constants.hpp:161-180` |
| drive-controller TX パック / RX パース | `drive-controller/dc-firmware/src/can/can_data.cpp` |
| ETC モード enum (CAN) | `drive-controller/dc-firmware/src/can/can_data.hpp:20-25` |
| data-logger バースト送信 / バッファ分割 | `data-logger/src/can/can_master.cpp` , `can_master.hpp` |
| data-logger TWAI 設定 | `data-logger/src/can/can.hpp` , `can.cpp` |
| MoTeC デコード（表示） | `kart-machine-manager/app/src/can/can_listeners.py:34-66` |
| MoTeC エンコード（模擬） | `kart-machine-manager/app/src/can/mock_can_sender.py:42-84` |
| ID→長さマップ / UDP ペイロード | `kart-machine-manager/app/src/can/can_listeners.py:74-134` |
