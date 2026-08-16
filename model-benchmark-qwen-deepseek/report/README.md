# 冻结评测报告

[`index.html`](./index.html) 是 2026-08-16 完成的三模型评测报告公开版，
用于题目、评分器和模型配置未变化时直接参考。

## 报告身份

- Report SHA-256：`5f3b540b42a13b1ea83b2152d16d6da9c6f9c309b9b2cc444ce50248d3c3d143`
- 题目总数：27
- DeepSeek 适用题目：21
- DeepSeek final content：20
- DeepSeek missing final：1（`risk_memo`，reasoning 已保留）
- DeepSeek 图片识别：N/A，不计入宏平均

## 输入身份

| 输入 | SHA-256 |
|---|---|
| `data/qwen36-quality.json` | `2e839d786705b43bc7f7fccdfc78924d44f9fed90543ecfc17740df7147fce61` |
| `data/qwen38-quality.json` | `9cb77dd85ab1b65f6407d15cd7932e804ac1bab06f8aa8d642999fbf3952104a` |
| `data/deepseek-quality.json` | `4b044f6860184dbb797a6db5d42acc4194d9132673213ded16fb8aa3e1aace1d` |
| `data/performance-comparison.json` | `3531abdd96ae774edab0043d123a38fa60f218f29e7754638471a435e3b5bbca` |
| `data/deepseek-performance.json` | `563002573d6fe9c51132c392fc11ae1f461eed77171387f494f5aee358a1bd44` |
| `data/quality-comparison.json` | `d7c2809392019eaa55f09ad017b2a247813409f9627dc49bac2566b56f71804e` |
| `scripts/generate_html_report.py` | `c7bee92d3d6713ce35f08b428824443ca4188ade522281433063028f5c05dd98` |

## 复用条件

以下条件全部成立时，可直接引用冻结报告，无需重新运行模型：

- 题目、prompt、隐藏编程测试和写作 rubric 未变化；
- 评分器与比较器逻辑未变化；
- 需要引用的是报告记录的三套模型配置和量化，而不是新的部署 revision；
- 接受 DeepSeek 与 Qwen 使用不同硬件，性能数字只代表部署实测。

任一条件变化时，应重新生成质量 JSON、比较结果和 HTML，并使用新的报告
哈希，不要覆盖本文件后继续沿用旧身份。
