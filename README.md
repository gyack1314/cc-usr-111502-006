# 文旅湖向量索引的快照过滤查询与召回核对

metrics.py 固定向量维度与距离规则，segments.py 保存不可变向量正文段，snapshots.py 定义活跃行版本与过滤。现有查询路径是精确全文扫描，尚未提供近邻访问结构。

运行环境为 Python 3.11，仅使用标准库。文件职责与数据约定见 contracts.md。

```sh
python3 -m vectorlake
python3 -m unittest discover -s tests -v
python3 -m compileall -q vectorlake tests
```

data/sample.json 保存项目演练资料。测试使用临时目录，不改变项目内正文。
