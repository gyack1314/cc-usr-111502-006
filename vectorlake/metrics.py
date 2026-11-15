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
        return math.fsum((a-b)*(a-b) for a, b in zip(left, right))
    if metric == 'negative_dot':
        return -math.fsum(a*b for a, b in zip(left, right))
    raise ValueError('未知距离规则')
