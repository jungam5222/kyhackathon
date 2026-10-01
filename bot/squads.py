"""분대 작전 (지침서 17장): FORM → MOVE → WAIT → ENTER → HOLD → DONE / ABORT."""
import params as P
from mapinfo import INF
from slots import Slot, P3

FORM, MOVE, WAIT, ENTER, HOLD = 'FORM', 'MOVE', 'WAIT', 'ENTER', 'HOLD'


class Squad:
    __slots__ = ('id', 'bi', 'fid', 'k', 'wait', 'state', 'since', 'waited', 'unsafe',
                 'move_limit')

    def __init__(self, sid, bi, fid, k, wait, turn):
        self.id = sid
        self.bi = bi
        self.fid = fid
        self.k = k
        self.wait = wait
        self.state = MOVE
        self.since = turn
        self.waited = 0
        self.unsafe = 0
        self.move_limit = 0

    def __repr__(self):
        return f"Sq{self.id}(b{self.bi},{self.state},k{self.k})"


class SquadManager:
    def __init__(self, mp):
        self.mp = mp
        self.squads = []
        self.next_id = 1
        self.done = 0
        self.aborted = 0

    # ------------------------------------------------------------------ 대상과 가치 (17.1)
    def _targets(self, ctx):
        mp, td, eco, mem = self.mp, ctx.td, ctx.eco, ctx.mem
        H = min(P.VALUE_HORIZON, P.LAST_TURN - ctx.turn)
        out = []
        e_eng = [b for b in mp.by_kind.get('ENG', []) if td.owner[b.i] == 1]
        fin = ctx.finale
        for b in mp.blds:
            o = td.owner[b.i]
            v = 0.0
            if fin and o == 1:
                order = {'ENG': 6, 'HALL': 5, 'HOSPITAL': 4, 'STATION': 3}
                v = 100.0 + order.get(b.kind, 0) + mem.score_of(b.i)
            elif b.kind == 'ENG' and o == 1 and len(e_eng) == 1:
                v = H * (eco.income[1] / P.DIV_ENG +
                         (eco.income[0] / P.DIV_ENG if eco.eng[0] == 0 else 0))
            elif b.i in mem.retake and o == 1 and b.kind in ('ENG', 'HALL'):
                v = H * eco.income[0] / P.DIV_ENG if b.kind == 'ENG' \
                    else H * P.HALL_BONUS / eco.cost[0]
            elif b.kind == 'HALL' and o == 1:
                v = H * (P.HALL_BONUS / eco.cost[1] + P.HALL_BONUS / eco.cost[0])
            elif b.kind == 'DEPOT' and o != 0 and not mem.depot_claimed[0][b.i] \
                    and not ctx.terr.T[b.c]:
                v = P.DEPOT_BONUS / eco.cost[0]
            elif b.kind == 'HOSPITAL' and o == 1 and ctx.terr.F and \
                    min(mp.dist[b.c][c] for c in ctx.terr.F) <= P.SQUAD_FWD_HOSP_R:
                v = P.SQUAD_V_FWD_HOSP
            elif b.kind == 'STATION' and o == 1 and len(eco.stations[1]) == 2:
                v = P.SQUAD_V_STATION
            if v > 0:
                out.append((v, b))
        return out

    def _wait_cell(self, ctx, b, k):
        mp, th = self.mp, ctx.threat
        best = None
        for r in (1, 2):
            for c in mp.ball(b.c, r):
                if mp.dist[b.c][c] != r or c in mp.bld_at:
                    continue
                if th.E1[c] > k:
                    continue
                d0 = min(mp.dist[s][c] for s in ctx.eco.sites[0])
                cost = d0 + P.SQUAD_LAMBDA * th.E1[c]
                key = (cost, c)
                if best is None or key < best[0]:
                    best = (key, c)
            if best is not None:
                break
        return best[1] if best is not None else None

    # ------------------------------------------------------------------ 매 턴
    def update(self, ctx, flagm):
        """반환: (깃발 id → 목표 칸, 슬롯 목록, 고정 목록[(칸, 인원, 슬롯)])."""
        mp, td, th = self.mp, ctx.td, ctx.threat
        alive = {f.id: f for f in flagm.flags}
        keep = []
        for sq in self.squads:
            f = alive.get(sq.fid)
            o = td.owner[sq.bi]
            if f is None:
                self.aborted += 1
                continue
            if o == 0:
                self.done += 1
                f.squad = None
                continue
            if sq.state in (MOVE, WAIT):
                if th.E1[sq.wait] > max(sq.k, td.W[0][sq.wait]):
                    sq.unsafe += 1
                else:
                    sq.unsafe = 0
                if f.c == sq.wait:
                    sq.state = WAIT
                if sq.state == WAIT:
                    sq.waited += 1      # 깃발이 대기 칸에서 밀려나도 센다
                late = sq.state == MOVE and ctx.turn > sq.move_limit
                if sq.waited > P.SQUAD_WAIT_MAX or sq.unsafe >= P.SQUAD_UNSAFE_TURNS or late:
                    f.squad = None
                    self.aborted += 1
                    continue
            elif sq.state == ENTER:
                b = mp.blds[sq.bi]
                sq.state = HOLD if f.c == b.c else WAIT
            if ctx.turn >= P.ENDGAME_TURN:
                b = mp.blds[sq.bi]
                need_t = mp.dist[f.c][b.c] + (1 if o == -1 else 2)
                if ctx.turn + need_t - 1 > P.LAST_TURN:
                    f.squad = None
                    self.aborted += 1
                    continue
            keep.append(sq)
        self.squads = keep
        self._start(ctx, flagm)
        goals = {}
        slots = []
        locks = []
        for sq in self.squads:
            b = mp.blds[sq.bi]
            f = alive.get(sq.fid)
            if sq.state == WAIT and f is not None and f.c == sq.wait:
                need = th.E1[b.c] + 1
                have = td.W[0][sq.wait]
                if have >= need and (td.W[1][b.c] == 0 or have >= td.W[1][b.c] + 1):
                    sq.state = ENTER
            if sq.state in (MOVE, WAIT):
                goals[sq.fid] = sq.wait
                s = Slot(('squad', sq.id, 'wait'), sq.wait, sq.k, P3, value=float(sq.k))
                slots.append(s)
                if sq.state == WAIT:
                    locks.append((sq.wait, sq.k, s))
            elif sq.state == ENTER:
                goals[sq.fid] = b.c
                need = th.E1[b.c] + 1
                s = Slot(('squad', sq.id, 'enter'), b.c, need, P3, deadline=1, atomic=True,
                         value=float(need))
                slots.append(s)
                locks.append((sq.wait, td.W[0][sq.wait], s))
            elif sq.state == HOLD:
                goals[sq.fid] = b.c
                need = th.E1[b.c]
                if need > 0:
                    slots.append(Slot(('squad', sq.id, 'hold'), b.c, need, P3, value=float(need)))
        return goals, slots, locks

    def _start(self, ctx, flagm):
        mp, th, td = self.mp, ctx.threat, ctx.td
        limit = P.SQUAD_MAX_FIN if ctx.finale else P.SQUAD_MAX
        if len(self.squads) >= limit:
            return
        busy = {sq.bi for sq in self.squads}
        used_k = sum(sq.k for sq in self.squads)
        surplus = ctx.w_total - len(ctx.terr.F) - P.SQUAD_RESERVE - used_k
        if ctx.finale:
            surplus = ctx.w_total - used_k - P.SQUAD_RESERVE
        cands = []
        for v, b in self._targets(ctx):
            if b.i in busy:
                continue
            k = max(th.E1[b.c], th.Ed(b.c, 2)) + 1
            if v < P.SQUAD_MIN_VALUE or v < k or k > surplus:
                continue
            d0 = min(mp.dist[s][b.c] for s in ctx.eco.sites[0])
            if d0 >= INF:
                continue
            cands.append((-v / (k * max(1, d0)), b.i, b, k))
        cands.sort(key=lambda t: (t[0], t[1]))
        for _, _, b, k in cands:
            if len(self.squads) >= limit or k > surplus:
                break
            wait = self._wait_cell(ctx, b, k)
            if wait is None:
                continue
            free = [f for f in flagm.flags if f.squad is None and
                    f.task in (None, 'F4', 'F5', 'F7', 'F8')]
            if not free:
                break
            f = min(free, key=lambda f: (mp.dist[f.c][wait], f.id))
            if mp.dist[f.c][wait] >= INF:
                continue
            sq = Squad(self.next_id, b.i, f.id, k, wait, ctx.turn)
            sq.move_limit = ctx.turn + mp.dist[f.c][wait] + P.SQUAD_MOVE_SLACK
            self.next_id += 1
            f.squad = sq.id
            f.task = 'F6'
            f.bi = None
            self.squads.append(sq)
            surplus -= k
