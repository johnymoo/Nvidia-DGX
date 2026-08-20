# Dual GB10 R2.2 Enclosure

面向两台 xFusion FusionXpark GB10 的参数化 3D 打印立式散热盒。R2.2-RC1 采用前置 140 mm PWM 进风、后部中央 60 mm PWM 辅助排风、圆角 U 型罩、前向滑入底板、免工具前后面板、左右可换显示仓和两颗 M4 固定的商业提手。

## 已确认结构

- 两台 `150 x 150 x 50.5 mm` GB10 沿短边并排立放；
- U 型罩主体 `152 x 158 x 166 mm`，所有单件适配 `180 mm` 立方打印空间；
- 底板每侧使用连续锥形舌边和三组带真实 Y 向导入面的上下双向捕获轨；
- 前后面板各使用两个上定位舌和两个 `20 mm` 根部固定弹臂卡扣，卡入底板 `1.8 mm` 厚固定反扣唇；
- 前面板包含与 140 mm 风扇配合的一体式周向导风罩、设备前止挡和底板止挡；
- 显示仓使用两个楔形 T 键、`7 mm` 锁程和一个 `22 mm` 纵向弹片，释放位移 `1.4 mm`；
- 底板线槽、侧壁保护导轨和显示仓穿墙口形成连续线束路径；
- 提手加强筋与两侧墙重叠，整机结构螺丝仅两颗 M4；
- 主体使用 PETG 硬导向，不使用泡棉或必需 TPU。

## 生成与验证

```bash
uv sync
uv run python -m unittest cad/test_generate_r2.py -v
uv run python cad/generate_r2.py
```

交付物写入 `output/dual-gb10-r2-2-rc1/`，ZIP 写入 `output/dual-gb10-r2-2-rc1-delivery.zip`。生成器输出 STEP、已定向 STL、装配 STEP、PDF/DXF/SVG 图纸、16 个生产几何派生配合规、CAD 派生网页 STL、预览图、BOM、验证报告和 SHA-256。

## 查看 3D 模型

```bash
python3 -m http.server 8767
```

打开 `http://127.0.0.1:8767/site/r2.html` 查看完成图，或打开 `http://127.0.0.1:8767/site/r2-assembly.html` 查看分步装配、透明风道和爆炸图。

## 放行边界

R2.2 已通过 CAD 实体、网格、包络、静态碰撞、根部固定卡扣挠曲/释放、防回扣、完整显示仓路径、底板全程滑入和设备限位检查，但仍是 release candidate。打印主体前必须先完成配合规、逐件切片复核、两台 GB10 实测、风扇孔位、显示 PCB、后部线缆弯曲半径、USB-C 供电能力和 `12 kg / 60 s` 提手静载 Gate。不要在切片软件中缩放 STL。
