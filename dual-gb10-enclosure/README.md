# Dual GB10 A+ Enclosure

面向两台 xFusion FusionXpark GB10 的可参数化 3D 打印立式散热盒。当前 R1 原型采用前置 140 mm PWM 进风、后部中央 60 mm PWM 辅助排风和上下被动排风窗，同时保留后部接口接线空间。

## 已确认方案

- 两台 `150 x 150 x 50.5 mm` GB10 沿短边并排立放；
- 前置 `140 x 140 x 25 mm` 四线 PWM 风扇；
- 后部中央 `60 x 60 x 15 mm` 四线 PWM 风扇；
- 可拆顶盖、承重横梁和可折叠提手；
- 显示器盒可装在左侧或右侧，默认左侧；
- 最大打印件 `158 x 158 x 162 mm`，适配 `180 mm` 立方打印空间；
- PETG 主体和圆角硬质导向筋，不使用泡棉或必需 TPU 接触件；仅在实测出现异响时选装少量硅胶点。

详细打印、装配和硬件说明见 [`cad/README.md`](./cad/README.md)。当前控制器拓扑草案见 [`planning/02-working/controller-architecture.md`](./planning/02-working/controller-architecture.md)。

## 文件清单

| 路径 | 内容 |
| --- | --- |
| `cad/generate_a_plus.py` | A+ 参数化 CAD、STL/STEP 导出和几何验证 |
| `cad/test_generate_a_plus.py` | 尺寸、实体有效性和碰撞测试 |
| `visuals/` | Three.js A+ 交互式结构与风道查看器 |
| `site/` | 风道方案对比页与 R2 外壳结构评审页 |
| `planning/` | 约束、方案取舍和控制器架构记录 |
| `output/` | 本地生成的打印件、装配件、预览图和发布包，不纳入 Git |

## 生成 CAD

需要 Python 3.9+ 和 [uv](https://docs.astral.sh/uv/)：

```bash
uv sync
uv run python cad/generate_a_plus.py
uv run python -m unittest cad/test_generate_a_plus.py
```

输出写入 `output/cad-a-plus/`。先打印三个 fit gauge，实测 GB10、140 mm 风扇、60 mm 风扇和最终显示器 PCB 后，再调整 `Params` 并生成正式打印件。不要在切片软件中缩放 STL。

## 查看 3D 方案

```bash
cd dual-gb10-enclosure
npm --prefix visuals install
python3 -m http.server 8766
```

打开 `http://127.0.0.1:8766/site/index.html` 查看风道方案，打开 `http://127.0.0.1:8766/site/r2.html` 查看 R2 外观比例，或打开 `http://127.0.0.1:8766/site/r2-assembly.html` 查看当前 0–8 步装配、透明风道、完整爆炸和接口验证清单。

旧版 Three.js 场景位于 `http://127.0.0.1:8766/visuals/`。所有场景均支持旋转和缩放；装配评审页另支持分步播放、左右显示仓、透明风道与完整爆炸模式。

## 已知限制

- 当前 STL/STEP 是工程原型，不是量产定稿；关键安装孔和实体公差仍需卡尺复核。
- 显示器开孔是视觉包络，待温控器件选型后更新。
- 不应拆分或搭接 GB10 的 `48 V / 5 A` EPR 电源输入；控制器供电能力需在 GB10 USB-C 主机口上实测。
- 生成图只用于外观和空间沟通，制造尺寸以参数化 CAD 和验证报告为准。
