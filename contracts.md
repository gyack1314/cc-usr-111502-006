# 向量湖访问

向量维度固定，元素为有限 binary64，输入规范由 metrics.py 决定；bool 不属于数值。距离为平方欧氏距离或负内积，越小越近，无隐式归一化。溢出的距离应明确报告，不用 NaN 排序。相同距离按逻辑 id 的 UTF-8 顺序稳定排列，精确模式返回过滤后前 K 条，不扩展 ties。

向量段可包含旧行，指定 snapshot 的 live 映射才决定可见 revision，删除是映射不再包含该 id。metadata 是同一正文版本的整型、文本、布尔或 null 字段，过滤采用有类型相等和 AND，不将字符串数字隐式转换。索引需绑定向量段摘要、维度及距离规则；合并后仍保留旧快照所用段。

现有 exact 是小资料可用的扫描路径；近似模式需要独立访问结构，结果标记模式、搜索参数、可见候选和距离计算数，不承诺每次恰有 K 个结果。召回参照过滤后精确 TopK，固定且独立的查询集公开生成种子与规模，可报告测得召回而不预设一个固定结论。新增索引结构须在磁盘恢复后可查询，索引与活跃行版本不一致时拒绝或回退正确的扫描路径。

# 索引与召回核对实现约定

index.py 的 IVF 索引按内容寻址落盘于 段根目录/indexes/，绑定段摘要列表（构建顺序）、维度、距离规则与种子；load 校验摘要、格式与维度。分格为确定性 k-means（kmeans++，种子固定），质心指派始终按平方欧氏，与查询距离规则无关；索引只为构建时的距离规则服务，查询指定其他规则即拒绝，跨维度段在扫描与恢复处即被拦截。

近似查询按质心距离升序逐格探测：快照可见性先于距离计算，元数据过滤在距离计算之后；stats 分别报告 rows_examined、visible_candidates、distance_computations、matched_candidates、centroid_distances。expand=False 只探测 nprobe 格（stop_reason=fixed_nprobe）；expand=True 在过滤后候选满 K 前持续扩格（count_reached）；require_certified=True 继续扩到 l2 三角界（质心距离减格半径，向零留浮点余量，溢出即放弃）可认证或耗尽为止（certified / exhausted）。exhausted 或 certified 为真时结果与 exact 一致，否则是近似结果，不承诺恰有 K 条。快照段集合与索引不一致时默认拒绝；on_incompatible='fallback' 回退 exact 扫描并标记 mode=exact_fallback。

merge 只接受同维度、同距离规则的索引，段取并集并保留先来顺序，行按 (id, revision) 去重，同版本内容冲突直接报错。合并写入新索引文件，旧索引与旧段保留，旧快照仍由旧索引服务。

recall.py 的 make_queries 用独立种子均匀生成查询，不取自索引样本或质心，种子与规模写入报告；evaluate 以过滤后 exact TopK 为参照，报告逐条与平均召回、顺序一致率、认证比例及双方实际访问量（approx 的 rows_examined 与 distance_computations，对 exact 的 rows_scanned）。brute_force 是独立实现的扫描路径，check_exact 在小快照上核对 exact 结果。
