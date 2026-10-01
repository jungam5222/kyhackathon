"""역 순간이동 (지침서 15장).

배정이 끝난 뒤, 배정된 그룹의 도착 시간을 줄이는 TELE 하나만 고른다 (턴당 1회, 최대 5명, 병종 1개).
원천은 턴 시작에 출발 역에 있던 유닛뿐이다.
"""
import params as P
from assign import TAG_TELE
from slots import P0d


def select(ctx, asg, flag_moves):
    eco, mp, th = ctx.eco, ctx.mp, ctx.threat
    if not eco.tele_ok[0] or asg is None:
        return None
    st = sorted(eco.stations[0])
    best = None
    # 깃발 TELE (이득 ≥ P-TELE_FLAG_SAVE, 도착 역이 깃발에게 안전)
    for f, a, e in flag_moves:
        if f.new or f.c not in st or f.goal is None or f.tag is not None:
            continue
        g = f.goal
        walk = mp.dist[a][g]
        for d in st:
            if d == a:
                continue
            save = walk - (1 + mp.dist[d][g])
            if save < P.TELE_FLAG_SAVE:
                continue
            if th.E1[d] > asg.endc[d]:
                continue
            k = (save, -d)
            if best is None or k > best[0]:
                best = (k, 'F', a, d, 1, f)
    if best is not None:
        _, kind, s, d, n, f = best
        for i, (ff, a, e) in enumerate(flag_moves):
            if ff is f:
                flag_moves[i] = (ff, a, d)
                ff.end = d
                ff.tag = 'TELE'
        return ('F', s, d, n)
    # 전투병 TELE
    for s in st:
        grps = [g for g in asg.by_cell.get(s, ()) if g.n > 0 and not g.prod
                and g.slot is not None and g.status != 'lock' and g.tag is None]
        if not grps:
            continue
        for d in st:
            if d == s:
                continue
            items = []
            for g in grps:
                walk = asg.cost(s, g.slot)
                tl = 1 + asg.cost(d, g.slot)
                save = walk - tl
                if save >= P.TELE_MIN_SAVE:
                    items.append((save, g.seq, g))
            if not items:
                continue
            items.sort(key=lambda t: (-t[0], t[1]))
            n = 0
            total = 0
            p0 = False
            for save, _, g in items:
                if n >= P.TELE_MAX:
                    break
                k = min(g.n, P.TELE_MAX - n)
                n += k
                total += save * k
                if g.slot.tier <= P0d:
                    p0 = True
            if n <= 0:
                continue
            if asg.endc[d] + n < th.E1[d] and not p0:
                continue
            k = (total, -s, -d)
            if best is None or k > best[0]:
                best = (k, 'W', s, d, n, items)
    if best is None:
        return None
    _, kind, s, d, n, items = best
    left = n
    for save, _, g in items:
        if left <= 0:
            break
        k = min(g.n, left)
        if k < g.n:
            ng = g.clone(k)
            ng.slot, ng.status, ng.tier = g.slot, g.status, g.tier
            ng.step = g.step
            g.n -= k
            asg.groups.append(ng)
            g = ng
        if g.step is not None:
            asg.endc[g.step] -= g.n
        g.step = d
        g.tag = TAG_TELE
        g.path = None
        asg.endc[d] += g.n
        left -= k
    return ('W', s, d, n - left)
