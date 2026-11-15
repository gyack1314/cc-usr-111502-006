"""向量查询的距离契约。"""
import math

def validate(vector, dimension):
    if not isinstance(vector, list) or len(vector) != dimension:
        raise ValueError('向量维度不符')
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in vector):
        raise ValueError('向量含非有限数或非法类型')
    return tuple(float(value) for value in vector)

def distance(left, right, metric):
    if len(left) != len(right):
        raise ValueError('距离两端维度不符')
    if metric == 'l2_squared':
        # 各项非负，溢出只会得到 +inf，可确定地排在有限距离之后，不产生 NaN。
        return math.fsum((a-b)*(a-b) for a, b in zip(left, right))
    if metric == 'negative_dot':
        terms = [a*b for a, b in zip(left, right)]
        try:
            return -math.fsum(terms)
        except ValueError:
            # 异号无穷相加无法比较，明确报告而不是返回 NaN 参与排序。
            raise ValueError('距离溢出：内积含异号无穷') from None
    raise ValueError('未知距离规则')
