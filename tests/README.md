# 测试

本目录测试**不依赖第三方库**，仅用 Python 标准库即可运行，便于在无 Docker/无 pip 的环境核对核心口径。

```bash
cd tests
python3 -m unittest test_identity_core test_identity_integration -v
```

- `test_identity_core.py`：纯函数口径（并查集、去重、污染、幂等重试、冻结语义），直接按文件路径加载 `backend/src/services/identity_core.py`。
- `test_identity_integration.py`：真实服务层 `identity.py` / `analysis.py` / 控制器在内存 SQLite 上的端到端测试。`_vendor/` 提供仅用于测试的极简 SQLAlchemy / scipy / FastAPI / pydantic / redis 垫片，**不参与生产**；容器内仍使用 `requirements.lock` 的真实依赖。

覆盖的关键不变量：

1. 同组别名去重，原始标识数与去重人数同时保留。
2. 同一身份跨 A/B 两组 → 污染单列、不计入任一组、阻断发布，不任选组、不悄悄剔除。
3. 关联任务 queued/running/done/failed，中断可恢复；同一关联重试不重复改变人数与版本。
4. 裁决冻结身份关系版本与映射；归并后旧裁决结果不变，新裁决用新版本。
5. 归并后旧别名补采的事件仍归同一人；采集时身份级跨组/重复事件被阻断。
6. 归并链可追查：canonical 身份、全部别名、归并历史、原始关联依据。

垫片中的统计实现已用标准正态/卡方已知值核对（sf(1.96)、ppf(.975)、chi2 sf(3.841,1)），与 scipy 口径一致。
