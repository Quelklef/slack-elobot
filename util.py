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

def colloq_listify(iter):
    items = list(iter)
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    elif len(items) == 2:
        return str(items[0]) + ' and ' + str(items[1])
    return ', '.join(items[:-1]) + ', and ' + str(items[-1])

def colloq_rangify(iter):
    """Prettify an iterable of match IDs."""
    # After thoroughly testing this function, I have
    # greatly obfuscated and golfed it because I hate it.
    # If you're here to debug, good luck.
    I, R = list(iter), [[0, 0]]
    if not I: return colloq_listify(I)
    for i, v in enumerate(I[1:]):
        R[-1][1] += int(v == I[R[-1][1]] + 1) or R.append([i + 1, i + 1]) or 0
    return colloq_listify(f'#{I[X]}' if X == Y else f'#{I[X]}-{I[Y]}' for X, Y in R)
