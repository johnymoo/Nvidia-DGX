# FDM/FFF 机械外壳与装配件可制造性检查清单

适用于桌面及工程级 FDM/FFF。下列数值是保守设计起点或审核触发线，不是普适标准。`[实测]` 表示必须用目标打印机、材料、方向和切片配置打印 coupon；`[分歧]` 表示公开资料不存在统一值。`w` 为实际切片挤出线宽。

## 硬门槛（按阶段执行）

- `HARD_PRE_CAD`：H01-H13 以及涉及安装接口时的 H17。Gate D 前必须完成设计计算、参数和验证计划；若只能靠 coupon/gauge 得到输入，只允许先生成该试样 CAD。
- `HARD_CAD_EXPORT`：H14。任何正式零件导出进入数据包前必须通过。
- `HARD_RELEASE`：H15-H16，以及 H05/H06/H09-H13/H17 中声明的实体测量、循环、热流、承载或安装测试。`PROTOTYPE` 可明确保留，`RELEASED` 不可保留。

同一 H 项可同时具有前置设计准则和发布实测准则。例如 H05 在 Gate D 前要求尺寸链、状态和 coupon 计划，在发布前要求 coupon 结果。不要因“需要先打印 coupon”制造禁止生成 coupon CAD 的死锁。

| ID | 门槛与检查方法 | 默认保守阈值/公式 | 适用条件及项目参数 |
|---|---|---|---|
| H01 | 对候选方向计算零件包围盒并与有效成形空间比较；超限必须拆件 | 绝对条件：`part_bbox <= build_volume`；规划余量起点：各轴 `max(5 mm, 2%)` | 参数化成形尺寸、禁用区、边缘余量。拆件不得切断主要载荷路径、密封面或关键外观面。[源1] |
| H02 | 标注打印方向、主载荷、外观面和支撑接触面 | 承载件默认不得使主要拉伸/剥离载荷垂直层面；否则须有方向试样和首件载荷试验 | 参数化 XY/Z 许用强度和打印方向。FFF 明显各向异性。[源1][源5] |
| H03 | 检查悬垂、桥接、封闭空腔及支撑可拆除性 | 无资格数据时：悬垂 45 度、桥接 10 mm；超过即加支撑、改倒角/泪滴孔或拆件 | `[实测][分歧]` 必须注明角度基准，并参数化喷嘴、层高、冷却、材料。Prusa 的 45-60 度范围明确依赖设备和设置。[源1] |
| H04 | 按实际 `w` 计数周长线；在切片预览中检查薄壁、筋、孔柱和小孔 | 装饰壁 `>=1w`；功能壳体 `>=3w`；筋 `>=2w`；承载孔柱径向包肉起点 `>=3w`；`d<max(2w,1 mm)` 的孔不假定可直接成形 | 参数化 `w`、周长数、孔后加工方式。0.4 mm 喷嘴对应约 0.45 mm 线宽只是示例。[源1] |
| H05 | 建立尺寸链并标出 CTF 尺寸；打印孔/轴/槽 fit gauge | 非关键尺寸能力起点：`+/-max(0.30 mm, 0.005L)`；活动配合径向间隙 0.25 mm；紧滑配合 0.15 mm | `[实测][分歧]` 过盈配合不得套默认值。参数化 XY/Z 偏差、孔补偿、象脚补偿、材料和温湿度。[源1][源4] |
| H06 | 对卡扣计算根部应变并做循环 coupon | 恒截面悬臂小挠度初算：`epsilon_max ~= 1.5t*delta/L^2`；起点 `epsilon_design <= 0.5 * 屈服应变`；根部圆角 `r>=0.5t`，优选约 `t` | `[实测][分歧]` 不得以断裂伸长率直接作为许用应变。原型起点：至少 3 件、2 倍目标循环、无裂纹且保持力不低于初值 80%。[源5] |
| H07 | 检查所有载荷路径的尖角、孔边、筋端、孔柱根部和厚薄突变 | 结构内角默认 `r>=0.5 * 相邻薄壁厚度`；无法满足时须分析并试验 | 圆角值依几何、材料和方向参数化；卡扣根部及把手连接处必须重点检查。 |
| H08 | 识别大首层、大平面和长直壁；验证翘曲后的装配和平面度 | 审核触发线：平面对角线 >100 mm 或连续首层面积 >10000 mm2 | `[实测]` 触发后必须采用筋、浅拱、分段、热腔、围裙/鼠耳或拆件，并参数化平面度和腔温。[源1][源2] |
| H09 | 由热耗散计算需求风量，并将机箱阻抗曲线与风扇曲线求交 | `Q=P/(rho*Cp*deltaT)`；常温近似 `Q_CFM ~= 1.8P_W/deltaT_C`；工作点风量起点 `>=1.25Qreq`；格栅自由面积比 60% 仅作初筛 | `[实测][分歧]` 自由面积不能代替压降测试。参数化海拔、滤网堵塞、噪声、进排风短路和风扇曲线。[源7] |
| H10 | 用封闭机箱最坏热点温度对照具体牌号/颜色的 TDS | 连续使用额定温度起点 `>=Tlocal,max+15 C` | 不得以喷嘴温度、熔点或单一 HDT 替代连续使用温度。阻燃必须核对具体材料、厚度和整机适用标准。[源2][源3][源12] |
| H11 | 热熔铜螺母必须指定料号、孔型、插入方向、温度和深度；做扭出/拉拔 coupon | 孔径、锥度、孔深和包肉服从插入件厂商图纸，不设通用值；螺钉不得顶底 | `[实测]` 参数化 insert PN、安装温度、允许扭矩和拉拔力。高预紧连接使用金属承压面或压缩限位件。[源6] |
| H12 | 对把手、挂点和承载结构画完整载荷路径并做 proof load | 设计载荷起点：`Fd=mg*Kdyn*Ksf`，手提件可先取 `Kdyn=2、Ksf=2`；首件试验起点为额定载荷 2 倍、保持 60 s | `[实测][分歧]` 系数不是标准。关键路径不得依赖稀疏填充或层间剥离；FEA 不能替代实体试验。 |
| H13 | 数字装配和实物试装检查线缆弯曲、应变释放、插拔路径、锁扣及工具空间 | 优先采用线缆厂商值；缺失时路由起点：静态中心线半径 `>=6D`，重复运动 `>=10D` | `[实测][分歧]` 6D/10D 仅为保守起点。参数化连接器插拔包络、最小维修开口和端口沉入量。 |
| H14 | 独立检查器和目标切片器验证网格；逐层检查首层、薄壁、桥、支撑、顶底层、接缝和载荷区 | 开边、非流形边、错误法向、退化面、越界和意外缺层必须为 0；自动修复结果必须人工复核 | 目标切片器支持时优先使用 3MF 保存项目；STL 必须另附单位和导出偏差。3MF 要求流形边、一致方向和外向法线。[源8][源9][源11] |
| H15 | 打印同方向、同材料、同切片配置的 fit/bridge/snap/insert coupon | coupon 至少覆盖名义值及相邻补偿档，例如 `0、+/-0.1、+/-0.2、+/-0.3 mm` | `[实测]` 修改材料、方向、喷嘴、线宽、层高、冷却或主体几何后，旧证据失效。 |
| H16 | 完成首件尺寸、装配、紧固、循环、载荷、热稳态和风量测试后才发布 | 所有 CTF 和项目验收值通过；切片错误为 0 | 交付包至少含原生 CAD、STEP、分件 STL、BOM、方向图、参数表、coupon/首件报告、版本和校验和；目标切片器支持时附项目 3MF。G-code 仅作指定设备附件。[源4][源10] |
| H17 | 壁挂、吊装或机架安装时，记录基材/墙体、锚固件 MPN 和额定值，验算拉拔、剪切、倾覆力矩、孔边距、钥匙孔/螺钉头防脱和安装误差 | 设计载荷沿用 H12；无适用标准时，安装系统首件起点为 2 倍额定载荷保持 60 s，并做向上脱钩和最不利偏载测试 | `[实测][分歧]` 2 倍/60 s 只是保守起点。墙体/基材、锚栓允许载荷、孔距、防脱结构、安装方向和试验夹具必须项目化；不得只验证打印件而忽略墙体侧。 |

## 建议项

| ID | 建议 |
|---|---|
| R01 | 拆件接缝增加定位销、舌槽或台阶，避开密封面和最大弯矩区；其间隙服从 fit gauge。 |
| R02 | 装配入口使用 0.5-1.0 mm 起始倒角；朝热床的外圆角若形成陡悬垂，改倒角或调整方向。[源1] |
| R03 | 大平面采用浅拱、边框和短筋分区；筋端渐变，根部圆滑，避免筋、孔柱和壁在一点形成刚度突变。 |
| R04 | 格栅采用圆角条和均匀流道，避免紧贴叶尖、滤网无维护空间及进排风短路；最终按压降、热点和噪声验收。[源7] |
| R05 | 高频维护位置优先螺钉加嵌件，低循环位置才使用卡扣；限制装配扭矩和螺钉长度。[源6] |
| R06 | 用 3MF 保存对象、修改器和切片参数快照；跨切片器或配置版本打开后必须重新审核。[源10] |

## 依赖打印机、材料和切片参数的可配置项

| 参数组 | 必须项目参数 | 初始值/资格方式 |
|---|---|---|
| P01 设备 | `build_xyz, exclusion_zones, nozzle_d, line_width, layer_h, chamber_temp` | `w` 取实际切片配置；成形余量按 H01 起步。 |
| P02 几何 | `wall/rib_perimeters, overhang_deg, bridge_mm, support_gap` | 功能壁 3w、筋 2w、悬垂 45 度、桥 10 mm；由综合 coupon 更新。 |
| P03 尺寸 | `tol_xy/z, hole_comp, elephant_foot_comp, fit_clearance` | 采用 H05 起点；由同方向 fit gauge 替换。 |
| P04 机械 | `allowable_xy/z, snap_strain, cycles, insert_torque/pullout, rated_load` | 只能使用目标打印态数据；静态 TDS 不得外推疲劳寿命。 |
| P05 热流 | `Tambient, Tlocal, Pheat, deltaTallow, altitude, Qreq, deltaPsystem, free_area` | 温度裕量 15 C、风量裕量 25%、自由面积 60% 仅作初筛；最终以热稳态和工作点实测替换。 |
| P06 验证 | `coupon_matrix, sample_n, CTF_list, proof_load, acceptance, package_manifest` | 安全或量产项目须另行制定统计样本量和法规验收计划。 |

## 电子设备外壳材料风险矩阵

风险为相对筛选，不代表具体牌号；基础聚合物名称也不代表 UL 94 等级。[源2][源3][源12]

| 材料 | 热/蠕变 | 冲击/卡扣 | 翘曲/工艺 | 电子外壳结论 |
|---|---|---|---|---|
| PLA | 高；约 60 C 已可能软化 | 脆，循环风险高 | 低翘曲 | 仅室温原型和低载荷内件，不用于热源附近或车内。[源3] |
| PETG | 中；长期夹紧会蠕变 | 韧性较好 | 低-中；拉丝、吸湿 | 常规室内壳体候选；卡扣、嵌件和热点须实测。 |
| ABS | 中低 | 较好 | 高翘曲；需热腔并管理排放 | 室内耐热功能壳体候选；大平面风险高。 |
| ASA | 中低 | 较好 | 高翘曲；需热腔 | 户外壳体候选，UV 优于 ABS；阻燃仍看具体牌号。 |
| PC | 低但牌号差异大 | 高韧性、缺口敏感 | 高；需高温设备和干燥 | 高温或承载壳体候选；必须验证尺寸稳定性。 |
| PA | 牌号相关；吸湿后刚度和尺寸变化明显 | 韧性/疲劳通常较好 | 高；严格干燥和热腔 | 卡扣和耐磨件候选；须做调湿后的尺寸与寿命测试。 |

## 来源

1. Prusa, Modeling with 3D printing in mind: https://help.prusa3d.com/article/modeling-with-3d-printing-in-mind_164135
2. Prusa, Filament Material Guide: https://help.prusa3d.com/filament-material-guide
3. Prusa, PLA: https://help.prusa3d.com/article/pla_2062
4. Protolabs, Understanding 3D Printing Tolerances: https://www.protolabs.com/resources/design-tips/3d-printing-tolerances/
5. Formlabs, Snap-Fit Joints for Enclosures: https://formlabs.com/blog/designing-3d-printed-snap-fit-enclosures/
6. SPIROL, Heat / Ultrasonic Inserts: https://www.spirol.com/product/threaded-inserts-for-plastics/heat-ultrasonic-inserts/
7. Same Sky, Airflow Fundamentals for DC Fan Selection: https://www.sameskydevices.com/blog/understanding-airflow-fundamentals-for-proper-dc-fan-selection
8. Protolabs, STL Design: https://www.protolabs.com/resources/design-tips/how-to-design-stl-files-for-3d-printing-in-your-cad-program/
9. 3MF Consortium, Core Specification 1.3.0: https://3mf.io/wp-content/uploads/sites/55/2025/02/3MF_Core_Specification_v1.3.0.pdf
10. Prusa, Saving projects as 3MF: https://help.prusa3d.com/article/saving-projects-as-3mf_1773
11. Prusa, Corrupted 3D models: https://help.prusa3d.com/article/corrupted-3d-models-for-printing_2205
12. UL Standards & Engagement, UL 94: https://www.shopulstandards.com/ProductDetail.aspx?productId=UL94

## 机器执行/Agent 审核模板

| ID | 等级 | 输入 | 检查 | 证据 | 结果 |
|---|---|---|---|---|---|
| `H01` | `HARD_PRE_CAD` | `build_xyz; bbox; orientation; margin` | `bbox_axis <= build_axis-2*margin` | `包围盒报告; 方向图` | `PASS/FAIL/NA/BLOCKED` |
| `<ID>` | `HARD_PRE_CAD/HARD_CAD_EXPORT/HARD_RELEASE/RECOMMENDED/CONFIG` | `<参数=值+单位>` | `<表达式或审核规则>` | `<测量表、照片、报告、3MF 哈希或日志 URL>` | `<PASS/FAIL/NA/BLOCKED>; note=<原因>; reviewer=<Agent>; timestamp=<ISO-8601>` |

`HARD_PRE_CAD` 或 `HARD_CAD_EXPORT` 出现 `FAIL/BLOCKED` 时不得关闭对应 CAD 门禁；`HARD_RELEASE` 出现 `FAIL/BLOCKED` 时不得标记 `RELEASED`。`NA` 必须附适用性理由。
