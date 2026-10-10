# カート CAN 通信仕様

`can.yaml` が定義の正。本書はネットワーク全体の構成・各メッセージの意味・移行状態・未決事項をまとめた読み物。
信号レイアウト (byte/size/endian/scale) は `can.yaml` と生成物 `generated/kart.dbc` を参照すること。

> 更新: 2026-10-05。旧版 (2026-07-06、ESP32 版 data-logger と 0x200/0x300/0x400 指令を前提とした実装調査) は git 履歴参照。

---

## 1. ネットワーク構成

```
 車両前方                                                      車両後方
 ┌──────────────────────────────────────────┐
 │ kart-machine-manager (kmm, DEBIX Infinity) │
 │  ┌─────────────┐   rpmsg    ┌───────────┐ │
 │  │ A コア Linux │◀──────────│ M コア    │ │   ┌──────────────────┐   ┌──────────────┐
 │  │ 表示/ログ/   │ (全受信)   │ data_logger│ │   │ drive_controller │   │  motec_ecu   │
 │  │ クラウド     │           │ ADC/GPIO/ │ │   │  Teensy 4.1      │   │  MoTeC M800  │
 │  └─────────────┘           │ CAN ctrl  │ │   │  APPS/TPS 直結   │   └──────┬───────┘
 │   GPS (UART 直結)           └─────┬─────┘ │   └────────┬─────────┘          │
 └──────────────────────────────────┼───────┘            │                    │
                                     │                    │                    │
 ════════════════════════════════════╧════════════════════╧════════════════════╧════ CAN 1 Mbps
        TX 0x700-0x701 (ADC)              TX 0x600-0x60A (IMU/後方センサー/状態)   TX 0x5F0-0x5F4
        TX 0x740 Control, 0x741 Shift ─▶ RX 0x740/0x741, RX 0x5F1 (Vbat) ◀──────────┘
```

- 物理層: **1 Mbps、Classic CAN 2.0、標準 11bit ID**。CAN FD・29bit ID は未使用。
- CAN はデータ取得だけでなく、**リアルタイムの制御信号 (コックピットスイッチ) の伝送にも使う**。
- APPS と TPS は drive_controller にアナログ直結。ETC の制御入力は CAN に依存しない (CAN には物理値と生値をログ用に流す)。
- Shutdown Circuit (BOTS / BSPD / マスタースイッチ / 燃料・点火・ETC の電源遮断) は規則上ハードワイヤ必須で CAN には載せない (kart-soft-docs「規則上の制約」参照)。

## 2. ノード

| ノード名 (`can.yaml`) | 実体 | CAN コントローラ | 役割 |
|---|---|---|---|
| `data_logger` | kmm M コア (i.MX8MM Cortex-M4 / 8MP M7, data-logger-zephyr `apps/can-gw`) | MCP2518FD (キャリアボード) / MCP2515 (現 HAT) | ADS8688 ADC 8ch (前方センサー) とコックピットスイッチ (GPIO) を送信。CAN 受信全量を rpmsg で Linux へ転送 |
| `kart_machine_manager` | kmm A コア (Linux, kart-machine-manager アプリ) | なし (rpmsg 経由の CAN netdev) | インパネ表示・ログ・クラウド送信。実バスへ送信しない |
| `drive_controller` | Teensy 4.1 (車両後方) | FlexCAN_T4 CAN3 | ETC / クラッチ / シフト / セルモーターリレー / ブレーキランプ制御。APPS/TPS 直結。IMU・後方センサー・車輪速・自身の状態を送信。0x740 と 0x5F1 を受信 |
| `motec_ecu` (外部) | MoTeC M800 | — | エンジンデータ送信 |

## 3. メッセージ一覧

| ID | 名称 | 送信 → 受信 | DLC | 周期 | 内容 |
|---|---|---|---|---|---|
| 0x5F0 | MoTeC_Engine1 | motec → kmm | 8 | MoTeC 設定 | rpm / スロットル / 水温 / 油温 |
| 0x5F1 | MoTeC_Engine2 | motec → kmm, dc | 8 | 〃 | 油圧 / ギア電圧 / バッテリ電圧 (dc は Vbat として使用) / λ |
| 0x5F2 | MoTeC_Engine3 | motec → kmm | 8 | 〃 | 吸気圧 / 燃圧 / 前後ブレーキ圧 |
| 0x5F3 | MoTeC_Status | motec → kmm | 8 | 〃 | ファン / IST シフト状態 / 入出力 RPM |
| 0x5F4 | MoTeC_Temps2 | motec → kmm | 6 | 〃 | 油温 2/3 / クーラント温 |
| 0x600 | DC_GyroXY | dc → kmm | 8 | 16 ms | ジャイロ X/Y (f32 LE, dps) |
| 0x601 | DC_GyroZGear | dc → kmm | 5 | 16 ms | ジャイロ Z + ギア |
| 0x602 | DC_AccelXY | dc → kmm | 8 | 16 ms | 加速度 X/Y (f32 LE, 単位要確認) |
| 0x603 | DC_AccelZ | dc → kmm | 4 | 16 ms | 加速度 Z |
| 0x604 | DC_Pedals | dc → kmm | 8 | 20 ms | 採用 APPS / TPS / クラッチ (0.01 %)、後ろブレーキ圧 (0.1 psi) |
| 0x605 | DC_EtcRaw | dc → kmm | 8 | 20 ms | APPS 1/2、TPS 1/2 の生値 (ADS8688 カウント, V) |
| 0x606 | DC_StrokeRear | dc → kmm | 4 | 20 ms | 後ろ左右ストローク (0.01 V) |
| 0x607 | DC_WheelSpeed | dc → kmm | 8 | 20 ms | 車輪速 4 輪 (0.01 km/h) |
| 0x608 | DC_WheelPulse | dc → kmm | 8 | 20 ms | 車輪速パルスの生カウント 4 輪 (累積 uint16) |
| 0x609 | DC_Engine | dc → kmm | 4 | 20 ms | エンジン回転数 / クラッチ後回転数 |
| 0x60A | DC_Status | dc → kmm | 5 | 33 ms | 適用中の ETC モード / launch / auto-shift、セルリレー、Shutdown ループ状態 |
| 0x700–0x701 | DL_700 / DL_701 | data_logger → kmm | 8 | 33 ms | ADS8688 ch0–3 / ch4–7 (u16 BE 生カウント, V = raw × 7.8125e-5) |
| 0x740 | Control | data_logger → dc, kmm | 4 | 33 ms | コックピットスイッチ: ETC モード / launch / auto-shift / セル |
| 0x741 | Shift | data_logger → dc, kmm | 2 | 10 ms | シフトパドル上下の押下状態 |

## 4. 制御信号の意味とフェイルセーフ

### 4.1 Control (0x740) と Shift (0x741)

- Control の byte0–2 (`etc_mode` / `launch_active` / `auto_shift`) は旧 DLC 3 フレームと互換。drive-controller の受信コード (`can_data.cpp`, `CONTROL_INPUT_VIA_CAN`) はこの 3 バイトを解釈する。byte3 は `starter` (押下中 1)。
- Control は即時性を求めないので 33 ms 周期で状態を送る (イベント送信はしない)。
- Shift はパドル操作の遅延を抑えるため Control から分離し、**10 ms 周期で押下状態を送ったうえで、状態が変わった瞬間 (押した / 離した) にも即時に 1 フレーム追加で送る**。遅延は送信側の検出時間だけになり、周期の待ち (最大 10 ms) がなくなる。周期送信は、追加フレームを取りこぼしたときの回復と途絶判定のために続ける。
  - この「変化時の即時送信」は DBC には表れない (`can.yaml` の `cycle_ms` から出る `GenMsgCycleTime` = 10 ms だけが載る)。DBC からツールで送信を模擬する場合は、変化時の送信を別に実装すること。
- 送信側 (M コア) はパドル入力を 10 ms より十分速く走査しデバウンスする (チャタリング除去は送信側の責務。受信側はしない)。変化時に即時送信するので、10 ms より短い押下も押した / 離したの 2 フレームで届く。
- 受信側 (drive_controller) は `shift_up` / `shift_down` の 0→1 の立ち上がりを 1 回のシフト要求とみなす。周期フレームか追加フレームかは区別しない。保持中の 1 は無視するので、押した瞬間の追加フレームの直後に周期フレームが来ても二重にシフトしない。
- フェイルセーフ (drive_controller): Control **200 ms 途絶**で `etc_mode → NORMAL` (ただし `MOTOR_OFF` はラッチ、CAN 断で勝手に復帰させない)、`launch → inactive`、`auto_shift → manual`、`starter → 0`。Shift は **100 ms 途絶**で両パドル 0 扱い。
- `etc_mode = 0` (未指定) や未知値はモード変更なし (現在値維持)。
- `starter` 押下中は drive_controller がセルモーターリレーを駆動する。
- バス負荷の目安: Shift 10 ms で約 1% (変化時の追加フレームはパドル操作の回数分だけで無視できる)、Control 33 ms で約 0.3%。drive_controller の 0x604–0x60A と IMU、0x700 系を足しても 10% 以下。
- CAN コントローラは通常モード (ACK 無しで自動再送) で使う。単発送信モード (旧 ESP32 版の TWAI `ss=1`) は制御フレームには使わない。

### 4.2 APPS / TPS (アナログ直結)

- APPS 2 系統と TPS 2 系統は drive_controller の ADS8688 に直結 (`constants.hpp` の `APPS_1_CH` / `APPS_2_CH` / `TPS_1_CH` / `TPS_2_CH`)。規則上は FSAE Rules 2027 T.4.2.8 / IC.4.4.7 の「アナログ信号で直接コントローラへ」に該当し、デジタル送信時に必要な故障モードの説明 (T.4.2.11 / IC.4.4.9) は不要。
- プラウジビリティ判定 (2 系統の 10% 乖離 100 ms、範囲外) は drive_controller 内で行う。
- CAN には採用値 (0x604) と生値 (0x605) をログ・検証用に流す。これらを ETC 制御に使う受信者はいない。

### 4.3 Vbat

drive_controller は MoTeC 0x5F1 の `battery_voltage` (0.01 V) を受信して ETC 制御の電源電圧として使う。

## 5. 移行状態 (2026-10 時点の実装)

| 項目 | 現状 | 目標 |
|---|---|---|
| コックピットスイッチ | drive-controller の GPIO に直結 (`MODE_SELECT_SW_PIN_*`, `AUTO_SHIFT_SW_PIN`, パドル `AUTO_SHIFT_UP/DOWN_IN_PIN`)。drive-controller が自分の状態を 0x740 (DLC 3) で送信 (`can_controller.cpp`) | kmm M コアの GPIO → 0x740 (DLC 4) と 0x741 を送信。drive-controller は `CONTROL_INPUT_VIA_CAN` を有効化して受信側へ。drive-controller の 0x740 送信は止め、状態は 0x60A へ |
| APPS / TPS | drive-controller の ADS8688 に直結 | 同左 (0x604 / 0x605 の送信を追加) |
| 前方 ADC (0x700/0x701) | M4 (`apps/can-gw`) が 30 Hz で送信済み | 同左。ch 割り当ては未定のまま信号名は固定しない |
| IMU (0x600–0x603) | drive-controller が IAM-20680HP で送信 | 同左 (加速度の単位確定) |
| 後方センサー・車輪速 (0x606–0x609) | 未送信 (drive-controller 内部で使用のみ) | 送信 |
| DC_Status (0x60A) | 未送信 (状態は 0x740 で送っている) | 0x740 が M コア送信に移った後、状態はこちらへ |
| Vbat | 未受信 (ログの vbat は 0) | 0x5F1 `battery_voltage` を受信 |
| kmm A コアの受信 | Python で 0x5F0–0x5F4 を手書きデコード、0x700 系は生のまま転送。kart.dbc 未使用 | kart.dbc を cantools でロード |

切替の際の注意: Control の定義は DLC 4 に拡張したが、現行 drive-controller (submodule 1a01108) は DLC 3 で送信している。新ヘッダで `msg.len >= KART_CAN_CONTROL_LENGTH` を判定する受信側は 3 バイトフレームを無視する。同じ ID を 2 ノードが送るとバス上で衝突するため、M コア側の送信開始と drive-controller の送信停止・受信側切替は同時に行うこと。

## 6. 未決・要確認

1. **加速度の単位 (0x602/0x603)**。旧実装はヘッダ m/s²・実データ mg。IAM-20680HP 実装で確定。
2. **MoTeC の送信周期**。本リポジトリ内に定義なし (kmm のモックは 33 ms)。実 ECU 設定と突き合わせ。drive_controller が Vbat に使うので、0x5F1 の周期と途絶時の扱いを決める。
3. **Shift の送信周期 (10 ms)**。パドルの最短押下時間と M コアの走査周期・デバウンス時間の関係を実機で確認し、必要なら周期を詰める。
4. **0x700/0x701 のチャンネル割り当て**。前方センサー 3 種 (左右ストローク、舵角、前ブレーキ圧) の配線が決まるまで ch 番号のまま。
5. **kmm A コアの kart.dbc 移行**。手書きデコード (`can_listeners.py`) を cantools に置き換える。
