# R2.1 Claude Opus 5 独立评审与处置

评审器：`claude_kimi --model claude-opus-5`。评审范围为可装配性、PETG 打印性、承力路径、保持结构、配合规和验证缺口。

原始结论为 `NOT PASS - HOLD RC2`，包含 1 个 blocker、3 个 major 和 5 个 minor。整改后的聚焦复核结论为 `RC_VERDICT: PASS`，无 blocker；RC2 始终保持 `production_released=false`，实物 Gate 未通过前不得打印整套或搬运设备。

| Finding | 评审意见 | 处置 | 状态 |
| --- | --- | --- | --- |
| B1 | 显示 T 键锁定仅有 0.083 mm3 干涉，接近线接触 | 恢复 7.2 mm 横向 T 头，使用 XY 45 度扩宽斜坡保持零支撑；锁定位外移 2 mm 干涉提高到约 4.69 mm3；新增 USB-C 插合状态 5 次 30 N 外拉 Gate | Fixed in CAD + physical gate |
| M1 | 提手长期蠕变、动态载荷和插入件规格不足 | 加强筋和顶皮是一体打印并非装配干涉；载荷由中央 boss 经横筋和整片顶皮传至侧墙。最终硬件锁定后执行 12 kg 静载（<=2 mm）、10 次提放和 6 kg/24 h 蠕变（残余 <=0.5 mm） | CAD clarification + physical gate |
| M2 | 短配合规不能覆盖全尺寸翘曲与 154 mm 滑行 | 三档规后执行全尺寸干装：滑入力 <=40 N、三站 Z 间隙 <=0.8 mm、后挡间隙 <=0.5 mm | Physical gate added |
| M3 | 140 mm 进风与 60 mm 排风不对称，热设计未证实 | `30+/-2 C` 双机满载 2 h，GPU <=85 C、PETG <=60 C 且无降频；失败则改 80 mm 或双 60 mm | Physical gate + fallback |
| m1/m2 | 卡扣插入扫掠、释放可达性未实证 | 50 次前后卡扣循环同时记录峰值插入力和单手释放；显示规记录 4.5 mm 按压释放 | Physical gate |
| m3 | 公差验证只有名义几何 | 三档规后执行全尺寸干装与双机推入，不以名义零碰撞代替 | Physical gate |
| m4 | 8-10 mm brim 接近 180 mm 热床边界 | 新增切片机 purge/prime/skirt 保留区检查；不满足时将 brim 调到通过实测翘曲所需的最小值或换更大热床 | Physical gate |
| m5 | 插入件与底板 Y 保持说明不足 | BOM/开放 Gate 记录实际插入件和扭矩；前面板下卡扣同时阻止底板向前退出，后挡与后框限制后移 | Documentation + physical gate |

## 复核标准

1. 自动 CAD 测试必须保持全绿，显示 T 键 0-7 mm 路径零碰撞，锁定位外拔干涉大于 1 mm3。
2. RC2 可以作为配合规和实物 Gate 的候选包，但不得标记生产放行。
3. 任何全尺寸干装、30 N 显示仓外拉、提手载荷或热浸失败都必须回到 CAD 修改并重新评审。
