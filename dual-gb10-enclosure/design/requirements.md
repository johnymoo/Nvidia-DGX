# ESP32-LCD 机箱显示模块外壳（Draft）

状态：`THREEJS_DRAFT`

本记录区分用户请求、图片证据和仓库内已有资料。图片只用于确认装配拓扑和线缆方向，不把透视尺寸当成制造尺寸。

## 用户请求（权威）

- 先为“1.47 寸控制显示模块 + Rev B 风扇接口板”实际装配体建模。
- 先交付 three.js draft，用户确认结构后才进入最终 3D 打印 CAD。
- 在模型中显式考虑 Type-C 端、电源线/12 V DC 插头端、风扇线束和转接板背面元件空间。
- 最终目标是可在桌面 FDM 打印机上打印的外壳，并可安装到既有双 GB10 立式机箱。

## 图片证据（用户提供）

- `design/evidence/esp32-module-assembly-01.png`
- `design/evidence/esp32-module-assembly-02.png`

图片确认：显示板与转接板平行叠层；两排排母位于中间；DC5521 插头从转接板一端插入；风扇插头和线束在转接板背面/下方形成集中包络；Type-C 位于显示板端部。图片未提供比例尺、插头型号尺寸或线缆最小弯曲半径。

## 现有资料（参考/约束）

- ESP32-LCD Rev B 制造版：PCB `45 × 30 × 1.6 mm`，4 个 M2 安装孔；显示排母塑高约 `8.5 mm`；底面 DC 插座高度约 `11 mm`。来源：`ESP32-LCD/hardware/fan-interface-revB/release-20260909-dfm5/README.md` 和 `pin-bom-mechanical-audit.json`。
- Waveshare 显示板：外形 `44.50 × 24.55 mm`，有效显示区 `32.93 × 17.75 mm`，排距 `17.00 mm`，M2 孔中心约 `39.00 × 17.78 mm`，含排针装配高度约 `10.60 mm`。来源：`ESP32-LCD/hardware/fan-interface-revB/display-pinout.md` 和官方机械图。
- 双 GB10 机箱 R2.3 A.1 已有左右可换显示仓接口：两个上 T 键、`7 mm` 下滑锁紧、一个约 `22 mm` 弹片卡扣。来源：`planning/02-working/r2.3-a1-panel-retention-esp32.md` 和 `cad/generate_r2.py`。

## 当前结构假设

- 显示面朝外，屏幕横向显示；ESP32 显示板和 Rev B 转接板保持平行叠层。
- 外壳由前框、电子托盘、可拆后盖组成；电子托盘不把排母或连接器作为承力件。
- 优先复用机箱现有显示仓适配接口并支持左右镜像；默认屏幕位于机箱左侧。
- Type-C 插头、电源线、风扇线束使用独立的插拔包络和应力释放体积；线缆不作为“细中心线”处理。
- 风扇线束允许沿 DC5521 电源线一侧汇合并共同弯曲出线；draft 以独立支路 + 同侧公共线束包络表示。
- 12 V 插座、FAN1/FAN2 接头是否外露仍为开放决定；draft 同时显示“内部接头”和“外露接头”两种 keep-out 选项。

## 尺寸状态

| 项目 | 名义值 | 状态 | 说明 |
|---|---:|---|---|
| 显示 PCB 外形 | 44.50 × 24.55 mm | `verified` | 官方机械图 |
| 显示有效区 | 32.93 × 17.75 mm | `verified` | 官方机械图 |
| Rev B PCB | 45 × 30 × 1.6 mm | `verified` | 当前制造版文件 |
| 排母塑高 | 8.5 mm | `verified` | 选定器件资料 |
| DC 插座高度 | 11 mm | `derived` | Rev B 机械审计/照片，需实物复核 |
| Type-C 插头外廓 | 暂按 12 × 8 × 5 mm | `provisional` | draft keep-out，不作为 CAD 尺寸 |
| 12 V 插头外廓 | 暂按 18 × 12 × 32 mm | `provisional` | 照片比例估计，需实物复核 |
| 线缆静态弯曲半径 | 暂按 `6×D` | `provisional` | 仅作 FDM draft 起点 |
| 转接板背面元件包络 | 11 mm 以上 | `derived` | 以 DC 座、C1、插件和焊点包络为基础 |
| 外壳墙厚 | 3.0 mm | `provisional` | 0.4 mm 喷嘴、PETG 起点 |

## Draft 验收

- 场景使用毫米，显示板、转接板、连接器、线缆包络和外壳分组均有稳定 `partId`。
- 至少包含 assembled、transparent、exploded、service、front/rear/left/right/top/bottom 视图。
- 可切换 Type-C、电源和风扇接头可见性，并显示关键尺寸和未实测警告。
- three.js 只作为结构评审模型；不宣称可直接打印，也不冻结最终孔位/卡扣/公差。
- 结构确认后，另行建立 Gate D freeze 和参数化 Build123d/OpenCascade CAD。
