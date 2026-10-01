"""생산·자원 (지침서 14장)."""
import params as P


def _ceil_div(a, b):
    return -(-a // b)


class ProdPlan:
    __slots__ = ('nF', 'w_base', 'w_max', 'hold', 'save', 'reason')

    def __repr__(self):
        return f"Prod(F{self.nF} W{self.w_base}/{self.w_max}{' hold' if self.hold else ''})"


def plan(ctx, nF, C, depot_n, depot_cost, eng_sure, flags_alive):
    """전투병 구매 수를 정한다.

    w_base: 일반 슬롯이 쓸 수 있는 수, w_max: P0 슬롯까지 쓸 수 있는 수(공학관 보류 예외).
    """
    eco = ctx.eco
    R = eco.R[0]
    I = eco.income[0]
    cw = eco.cost[0]
    pp = ProdPlan()
    pp.nF = nF
    pp.hold = False
    pp.save = False
    pp.reason = ''
    R1 = R - nF * P.COST['F']
    # 점령 자금: R1 − sW + I ≥ C  (E-02, 14.1)
    max_by_funds = (R1 + I - C) // cw if R1 + I - C >= 0 else 0
    w_max = max(0, min(R1 // cw, max_by_funds))
    # 넘침 방지 최소량 (E-19)
    over = R1 + I - P.RES_CAP
    w_min = _ceil_div(over, cw) if over > 0 else 0
    # 보급소 상한: bal − C_depot ≤ 40 − 15n  (E-18)
    if depot_n > 0:
        lim = P.RES_CAP - P.DEPOT_BONUS * depot_n
        need_spend = R1 + I - depot_cost - lim
        if need_spend > 0:
            w_min = max(w_min, _ceil_div(need_spend, cw))
    w_min = min(w_min, w_max)
    if ctx.last:
        pp.w_base = pp.w_max = w_max
        pp.reason = 'last'
        return pp
    # 깃발이 0명이면 깃발 값을 모은다 (13.1)
    if flags_alive == 0 and nF == 0 and R < P.COST['F']:
        pp.save = True
        pp.w_base = pp.w_max = w_min
        pp.reason = 'save'
        return pp
    if P.ENG_HOLD and eco.eng[0] == 0 and eng_sure:
        pp.hold = True
        pp.w_base = w_min
        pp.w_max = w_max
        pp.reason = 'eng_hold'
        return pp
    pp.w_base = pp.w_max = w_max
    return pp


def leftover_w(ctx, nF, spentW, C, depot_n, depot_cost):
    """S13: 최종 확인 뒤 더 사야 할 전투병 수 (넘침·보급소 조건)."""
    eco = ctx.eco
    R1 = eco.R[0] - nF * P.COST['F'] - spentW * eco.cost[0]
    I = eco.income[0]
    cw = eco.cost[0]
    over = R1 + I - P.RES_CAP
    need = _ceil_div(over, cw) if over > 0 else 0
    if depot_n > 0:
        lim = P.RES_CAP - P.DEPOT_BONUS * depot_n
        ns = R1 + I - depot_cost - lim
        if ns > 0:
            need = max(need, _ceil_div(ns, cw))
    can = max(0, min(R1 // cw, (R1 + I - C) // cw if R1 + I - C >= 0 else 0))
    return max(0, min(need, can))
