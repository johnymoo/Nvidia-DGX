# Dual GB10 R2.1 Enclosure

面向两台 xFusion FusionXpark GB10 的参数化 3D 打印立式散热盒。R2.1-RC2 采用前置 140 mm PWM 进风、后部中央 60 mm PWM 辅助排风、圆角 U 型罩、前向滑入底板、免工具前后面板、左右可换显示仓和两颗 M4 固定的商业提手。

## 已确认结构

- 两台 `150 x 150 x 50.5 mm` GB10 沿短边并排立放；
- U 型罩主体 `152 x 158 x 166 mm`，所有单件适配 `180 mm` 立方打印空间；
- 底板每侧使用连续舌边和三组上下双向 45 度捕获轨；
- 前后面板各使用两个上定位钩和两个带止回肩的下卡扣；
- 显示仓使用两个楔形 T 键、`7 mm` 锁程和一个按压释放卡扣；
- 提手加强筋与两侧墙重叠，整机结构螺丝仅两颗 M4；
- 主体使用 PETG 硬导向，不使用泡棉或必需 TPU。

## 生成与验证

```bash
uv sync
uv run python -m unittest cad/test_generate_r2.py -v
uv run python cad/generate_r2.py
```

交付物写入 `output/dual-gb10-r2-1-rc2/`，ZIP 写入 `output/dual-gb10-r2-1-rc2-delivery.zip`。生成器输出 STEP、已定向 STL、装配 STEP、PDF/DXF/SVG 图纸、14 个生产几何派生配合规、预览图、BOM、验证报告和 SHA-256。

## 查看 3D 模型

```bash
python3 -m http.server 8767
```

打开 `http://127.0.0.1:8767/site/r2.html` 查看完成图，或打开 `http://127.0.0.1:8767/site/r2-assembly.html` 查看分步装配、透明风道和爆炸图。

## 放行边界

R2.1 已通过 CAD 实体、网格、包络、静态碰撞、运动阻挡和打印方向检查，但仍是 release candidate。打印主体前必须先完成配合规、两台 GB10 实测、风扇孔位、显示 PCB、后部线缆弯曲半径、USB-C 供电能力和 `12 kg / 60 s` 提手静载 Gate。不要在切片软件中缩放 STL。
