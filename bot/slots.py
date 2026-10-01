"""수요 슬롯 (지침서 11장).

슬롯 하나 = "이 칸(또는 건물 b 반경 r)에 몇 명이 몇 턴 안에 필요하다"는 수요.
"""
import params as P
from mapinfo import INF

TIER_NAMES = ('P0a', 'P0b', 'P0c', 'P0d', 'P1a', 'P1b', 'P1c', 'P2', 'P3', 'P4', 'P5', 'P6')
(P0a, P0b, P0c, P0d, P1a, P1b, P1c, P2, P3, P4, P5, P6) = range(12)
TEMP_KINDS = ('hunt', 'guard', 'escort', 'gather', 'press', 'trade', 'squad', 'oesc', 'reent')
STRUCT_KINDS = ('screen', 'screenu', 'screen2', 'support')


class Slot:
    __slots__ = ('key', 'cell', 'r', 'need', 'tier', 'deadline', 'atomic', 'value',
                 'failed', 'base_need', 'meta')

    def __init__(self, key, cell, need, tier, deadline=None, atomic=False, value=0.0, r=0,
                 meta=None):
        self.key = key
        self.cell = cell
        self.r = r
        self.need = need
        self.base_need = need
        self.tier = tier
        self.deadline = INF if deadline is None else deadline
        self.atomic = atomic
        self.value = value
        self.failed = False
        self.meta = meta

    @property
    def area(self):
        return self.r > 0

    def __repr__(self):
        return f"Slot({self.key},{TIER_NAMES[self.tier]},n{self.need},d{self.deadline})"


class SlotMemory:
    """슬롯 히스테리시스 기억."""

    def __init__(self):
        self.guard_on = {}        # (bid, 깃발 키) -> bool
        self.intercept = {}       # 경계 칸 -> need 2 상태
        self.press = {}           # 경계 칸 -> 압력 목표
        self.press_turn = -99


# ---------------------------------------------------------------------- 경주 수비 (11.2)
def guard_slots(ctx, out):
    mp, td, th, mem = ctx.mp, ctx.td, ctx.threat, ctx.mem
    sm = ctx.smem
    eco = ctx.eco
    targets = [b for b in mp.blds if td.owner[b.i] == 0]
    targets += [b for b in mp.blds if td.owner[b.i] == -1 and b.i in mem.retake]
    last_stand = eco.n_bld[0] <= P.LAST_STAND_BUILDINGS
    eflags = [(('f', f.id), f.c, False) for f in mem.eflags]
    eflags += [(('s', s), s, True) for s in th.flag_virtual_sites()]
    alive_keys = set()
    for b in targets:
        ds = set()
        for fk, fc, virt in eflags:
            if virt:
                d = mp.dist[fc][b.c]
                if d > P.SITE_FLAG_RADIUS:
                    continue
            else:
                d = th.deff(fc, b.c)
            key = (b.i, fk)
            alive_keys.add(key)
            on = sm.guard_on.get(key, False)
            if d <= P.GUARD_HORIZON:
                on = True
            elif d >= P.GUARD_RELEASE:
                on = False
            sm.guard_on[key] = on
            if on:
                ds.add(d)
        if not ds:
            continue
        val = ctx.bld_value(b)
        for d in sorted(ds):
            if d == 0:
                need = th.E1[b.c] + 1
                out.append(Slot(('guard', b.i, 0), b.c, need, P0a if last_stand else P0b,
                                deadline=1, atomic=not last_stand, value=val, meta=b))
                continue
            r = d - 1
            k = th.Ed(b.c, d) + 1
            if not last_stand and th.Au(b.c, r) < k:
                continue            # 양보 (11.2-5)
            if last_stand:
                tier = P0a
            else:
                tier = P0b if r == 0 else P1a
            out.append(Slot(('guard', b.i, r), b.c, k, tier, deadline=1,
                            atomic=(tier == P0b), value=val, r=r, meta=b))
    for key in [k for k in sm.guard_on if k not in alive_keys]:
        del sm.guard_on[key]


# ---------------------------------------------------------------------- 사냥 (11.4)
def _flag_next_cell(ctx, f):
    mp, td = ctx.mp, ctx.td
    best = None
    for b in mp.blds:
        if td.owner[b.i] == 1:
            continue
        dn = mp.dist[f.c][b.c]
        dp = mp.dist[f.prev][b.c]
        if f.prev != f.c and dn < dp:
            if best is None or dn < best[0]:
                best = (dn, b)
    if best is None:
        for b in mp.blds:
            if td.owner[b.i] == 1:
                continue
            dn = mp.dist[f.c][b.c]
            if best is None or dn < best[0]:
                best = (dn, b)
    if best is None or best[0] == 0:
        return None
    opts = mp.toward(f.c, best[1].c)
    if not opts:
        return None
    if f.last_dir:
        for v in opts:
            if mp.dir_of(f.c, v) == f.last_dir:
                return v
    return opts[0]


def hunt_slots(ctx, out):
    mp, td, th, mem = ctx.mp, ctx.td, ctx.threat, ctx.mem
    E1, A1 = th.E1, th.A1
    our_b = {b.c for b in mp.blds if td.owner[b.i] == 0 or b.i in mem.retake}
    for f in mem.eflags:
        M = [f.c] + mp.nbrs[f.c]
        on_ours = f.c in our_b
        contested = f.c in mp.bld_at and td.F[0][f.c] > 0
        p = {}
        if on_ours or contested:
            p[f.c] = P.HUNT_P_BLD
            rest = [m for m in M if m != f.c]
            for m in rest:
                p[m] = (1 - P.HUNT_P_BLD) / max(1, len(rest))
        else:
            nxt = _flag_next_cell(ctx, f)
            if f.stat >= 1:
                p[f.c] = P.HUNT_P_STAY
                pn = P.HUNT_P_NEXT_STAYING if nxt is not None else 0.0
                rest = [m for m in M if m != f.c and m != nxt]
                if nxt is not None:
                    p[nxt] = pn
                for m in rest:
                    p[m] = (1 - P.HUNT_P_STAY - pn) / max(1, len(rest))
            else:
                p[f.c] = P.HUNT_P_STAY_MOVING
                if nxt is not None:
                    p[nxt] = P.HUNT_P_NEXT
                rest = [m for m in M if m != f.c and m != nxt]
                left = 1 - P.HUNT_P_STAY_MOVING - (P.HUNT_P_NEXT if nxt is not None else 0)
                for m in rest:
                    p[m] = left / max(1, len(rest))
        V = P.HUNT_V_BASE
        if f.lurker:
            V += P.HUNT_V_LURK
        if on_ours or any(v in our_b for v in mp.nbrs[f.c]):
            V += P.HUNT_V_ONBLD
        escorted = any(td.W[1][v] > 0 for v in mp.closed[f.c])
        if escorted and any(mp.dist[f.c][c] <= 3 for c in our_b):
            V += P.HUNT_V_ESCORT
        cands = []
        for m in M:
            need = E1[m] + 1
            if A1[m] < need:
                continue
            sc = p.get(m, 0.0) * V / need
            cands.append((-sc, m, need, p.get(m, 0.0)))
        cands.sort()
        k = 0
        for nsc, m, need, pm in cands:
            if k >= P.HUNT_MAX_CELLS:
                break
            if k == 1 and pm < P.HUNT_COVER_MIN_P:
                break
            out.append(Slot(('hunt', f.id, m), m, need, P0d, deadline=1, atomic=True,
                            value=-nsc, meta=f))
            k += 1


# ---------------------------------------------------------------------- 라인 칸 (11.5)
def screen_slots(ctx, out):
    mp, td, th, terr = ctx.mp, ctx.td, ctx.threat, ctx.terr
    sm = ctx.smem
    FR = th.FR
    seen2 = set()
    for c in terr.F:
        val = -th.d_enemy[c] * 1000 - th.d_site_us[c]
        if c in terr.occupied:
            for s in mp.nbrs[c]:
                if terr.T[s] and s not in terr.Fset and s not in seen2:
                    seen2.add(s)
                    out.append(Slot(('screen2', s), s, 1, P2, value=val))
            if c not in mp.bld_at or td.owner[mp.bld_at[c].i] != 0:
                out.append(Slot(('reent', c), c, th.E1[c] + 1, P3, deadline=1, atomic=True,
                                value=val))
            continue
        fr = FR[c]
        on = sm.intercept.get(c, False)
        if fr <= P.INTERCEPT_RADIUS:
            on = True
        elif fr > P.INTERCEPT_RELEASE:
            on = False
        sm.intercept[c] = on
        need = P.INTERCEPT_NEED if on else P.SCREEN
        if fr <= P.SCREEN_DEADLINE_R:
            # 마감 안에 닿는 병력이 없어도 칸이 비지 않도록 마감 없는 P2 몫을 함께 둔다
            out.append(Slot(('screenu', c), c, need, P1c, deadline=max(1, fr - 1), value=val))
        out.append(Slot(('screen', c), c, need, P2, value=val))


# ---------------------------------------------------------------------- 압력 (11.7)
def press_slots(ctx, out):
    th, terr, td = ctx.threat, ctx.terr, ctx.td
    sm = ctx.smem
    if ctx.turn - sm.press_turn >= P.PRESS_PERIOD:
        sm.press_turn = ctx.turn
        for c in terr.F:
            v = min(th.E1[c], P.PRESS_MAX)
            old = sm.press.get(c, 0)
            if abs(v - old) >= P.PRESS_HYST or (v == 0) != (old == 0):
                sm.press[c] = v
    for c in terr.F:
        v = sm.press.get(c, 0)
        if v > 0 and c not in terr.occupied and td.W[1][c] == 0:
            out.append(Slot(('press', c), c, v, P4, value=float(v)))


# ---------------------------------------------------------------------- 교환 (11.8)
def trade_slots(ctx, out):
    mp, td, th, terr = ctx.mp, ctx.td, ctx.threat, ctx.terr
    if ctx.mode not in ('ATT', 'FIN'):
        return
    if ctx.modes.A < P.TRADE_LEAD or ctx.modes.dP < 0:
        return
    our_b = {b.c for b in mp.blds if td.owner[b.i] == 0}
    cand = []
    seen = set()
    for c in terr.F + terr.S:
        for v in mp.nbrs[c]:
            if v in seen or terr.T[v] or td.W[1][v] == 0:
                continue
            seen.add(v)
            if td.F[1][v] > 0:
                pri = 3
            elif any(u in our_b for u in mp.nbrs[v]):
                pri = 2
            elif v in th.e_site_near:
                pri = 1
            else:
                pri = 0
            cand.append((-pri, v))
    cand.sort()
    for npri, v in cand[:3]:
        out.append(Slot(('trade', v), v, th.E1[v] + 1, P5, value=float(-npri)))


# ---------------------------------------------------------------------- 지원 (11.9)
def support_slots(ctx, out):
    mp, th, terr = ctx.mp, ctx.threat, ctx.terr
    for s in terr.S:
        m = 0
        for v in mp.nbrs[s]:
            if v in terr.Fset and th.E1[v] > m:
                m = th.E1[v]
        if m > 0:
            out.append(Slot(('support', s), s, min(P.SUPPORT_MAX, m), P6, value=float(m)))


# ---------------------------------------------------------------------- 오프닝 호위 (16.5)
def opening_escort_slots(ctx, out):
    plan = ctx.opening
    if plan is None:
        return
    td = ctx.td
    for (bi, need, t_dead) in plan.escorts:
        if td.owner[bi] == 0:
            continue
        dl = t_dead - ctx.turn + 1
        if dl < 1:
            continue
        b = ctx.mp.blds[bi]
        out.append(Slot(('oesc', bi), b.c, need, P1b, deadline=dl, value=ctx.bld_value(b)))


def build_base_slots(ctx):
    out = []
    guard_slots(ctx, out)
    hunt_slots(ctx, out)
    opening_escort_slots(ctx, out)
    screen_slots(ctx, out)
    press_slots(ctx, out)
    trade_slots(ctx, out)
    support_slots(ctx, out)
    return out
