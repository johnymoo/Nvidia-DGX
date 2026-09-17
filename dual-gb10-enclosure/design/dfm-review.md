# ESP32 模块外壳 Draft DFM 记录

状态：`PARTIAL — Three.js review only`

| 检查 | 阶段 | 结果 | 证据/下一步 |
|---|---|---|---|
| H01 成形空间 | PRE_CAD | PARTIAL | Draft 以现有 180 mm 打印空间为假设；正式包络待 Gate D |
| H03 悬垂/桥接 | PRE_CAD | OPEN | 后盖通风和线缆出口需进入 CAD 后按目标切片器复核 |
| H04 壁厚/筋 | PRE_CAD | PROVISIONAL | draft 显示 3 mm 外壳起点；正式 CAD 以线宽参数化 |
| H05 配合间隙 | PRE_CAD | OPEN | 前框、托盘、后盖和机箱适配接口需 fit coupon |
| H07 圆角/过渡 | PRE_CAD | OPEN | Type-C/电源出口根部需防应力集中 |
| H08 翘曲 | PRE_CAD | OPEN | 托盘大平面需方向、筋和 brim 设计 |
| H10 热 | PRE_CAD | LOW_RISK_OPEN | ESP32/接口板低热，但电源保护件区域需留通风 |
| H13 线缆服务 | PRE_CAD | PARTIAL | Draft 建立连接器和线缆实体包络；实物 OD/弯曲半径待测 |
| H17 机箱安装 | PRE_CAD | PARTIAL | 先复用 R2.3 T 键/弹片；最终承载和拔出方向需整机验证 |
| H18 参数追踪 | PRE_CAD | PASS_FOR_DRAFT | 所有 draft 尺寸集中在 `visuals/esp32-module-draft.html` 的 DESIGN 对象 |
| H19 接口合同 | PRE_CAD | OPEN | Gate D 前需建立本模块与机箱适配器的 assembly-interface-contract |

Draft 不满足 `HARD_CAD_EXPORT` 或 `HARD_RELEASE`，不得把该页面或其网格当作可打印交付物。
