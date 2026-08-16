# 冻结评测报告

[`index.html`](./index.html) 是 2026-08-16 完成并补充 RTX 4090 部署的评测报告公开版，
用于题目、评分器和模型配置未变化时直接参考。

## 报告身份

- Report SHA-256：`9eb0bf9a80f8f58dea23a9e68e7d8fe83867fe21f018983119be5c9d6805c488`
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
| `../qwen38-rtx4090-vllm/receipts/quality-instruct-20260816.json` | `0213316ae25cbd0d6e3b41bf78d118fe4e429ae43b311bd9a8d58b86ba5c863b` |
| `../qwen38-rtx4090-vllm/receipts/quality-thinking-low-20260816.json` | `7f483d366ffbb3093d33d1498db025dea92b44f7b9f49debd2562c02aeff6d7b` |
| `../qwen38-rtx4090-vllm/receipts/benchmark-20260816.json` | `81c698bbe896ce06de224a68934397b48df195b311a08d0185eb5f6a069e2c8d` |
| `../qwen38-rtx4090-vllm/receipts/deployment-20260816.json` | `dc958911c6a678175a979e6723af0907dda4558d3e99fafbc57f7d52b7a953e5` |
| `scripts/generate_html_report.py` | `c943c043946b0937d26835e00bedd3a4d7c5bcfae5b92ce06eef897384bf12df` |

## 复用条件

以下条件全部成立时，可直接引用冻结报告，无需重新运行模型：

- 题目、prompt、隐藏编程测试和写作 rubric 未变化；
- 评分器与比较器逻辑未变化；
- 需要引用的是报告记录的四套部署配置和量化，而不是新的部署 revision；
- 接受 DeepSeek 与 Qwen 使用不同硬件，性能数字只代表部署实测。

任一条件变化时，应重新生成质量 JSON、比较结果和 HTML，并使用新的报告
哈希，不要覆盖本文件后继续沿用旧身份。
