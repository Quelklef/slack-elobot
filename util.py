def mean(xs):
    """Mean of an iterable"""
    sum = 0
    count = 0
    for x in xs:
        sum += x
        count += 1
    return sum / count

def show(n):
    if n >= 0:
        return "+" + str(n)
    return str(n)
