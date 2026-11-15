# 文旅湖向量索引的快照过滤查询与召回核对

metrics.py 固定向量维度与距离规则，segments.py 保存不可变向量正文段，snapshots.py 定义活跃行版本、过滤、并列排序与可认证精确扫描，index.py 提供 IVF 近似索引（构建、落盘恢复、合并、带候选扩展的快照过滤近似查询），recall.py 用独立查询集交叉核对精确结果并衡量近似召回与实际访问量。

运行环境为 Python 3.11，仅使用标准库。文件职责与数据约定见 contracts.md。

```sh
python3 -m vectorlake
python3 -m unittest discover -s tests -v
python3 -m compileall -q vectorlake tests
```

data/sample.json 保存项目演练资料。测试使用临时目录，不改变项目内正文。
