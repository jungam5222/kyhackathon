"""깃발병 (지침서 13장): 정원·보충, 일 배정, 안전 이동, 회피, 점령 처리, 주차."""
from collections import deque

import params as P
from mapinfo import INF
from slots import Slot, P0c, P1b

RANK = {'F1': 1, 'F2': 2, 'F3': 3, 'F4': 4, 'F5': 5, 'F6': 6, 'F7': 7, 'F8': 8}


class OurFlag:
    __slots__ = ('id', 'c', 'task', 'bi', 'goal', 'came', 'stall', 'best_d', 'lane', 'li',
                 'born', 'last_dir', 'park_for', 'squad', 'opts', 'opt', 'end', 'tag',
                 'new', 'site')

    def __init__(self, fid, c, turn):
        self.id = fid
        self.c = c
        self.task = None
        self.bi = None
        self.goal = None
        self.came = None
        self.stall = 0
        self.best_d = INF
        self.lane = None
        self.li = 0
        self.born = turn
        self.last_dir = None
        self.park_for = None
        self.squad = None
        self.opts = []
        self.opt = 0
        self.end = c
        self.tag = None
        self.new = False
        self.site = None

    def __repr__(self):
        return f"F{self.id}@{self.c}:{self.task}"


class FlagManager:
    def __init__(self, mp, plan):
        self.mp = mp
        self.plan = plan
        self.flags = []
        self.next_id = 1
        self.lost_total = 0
        self.lost_now = 0
        self.spawned_total = 0
        self.blocked = {}            # (fid, bi) -> 끝나는 턴
        self.next_lane = 0
        self.hunted = False          # 19장: 요격으로 2명 이상 잃음
        self.n_open = plan.nflags if plan is not None else P.FLAG_OPEN
        self.reserved = set()        # 분대 목표 건물 (다른 깃발이 노리지 않는다)

    # ------------------------------------------------------------------ 장부 대조
    def reconcile(self, td, turn):
        exp = {}
        for f in self.flags:
            exp.setdefault(f.c, []).append(f)
        alive = []
        lost = 0
        for c in sorted(exp):
            fl = exp[c]
            actual = td.F[0][c]
            if actual >= len(fl):
                alive.extend(fl)
            else:
                fl.sort(key=lambda f: (RANK.get(f.task, 9), f.id))
                alive.extend(fl[:actual])
                lost += len(fl) - actual
        for c in self.mp.cells:
            extra = td.F[0][c] - len(exp.get(c, []))
            for _ in range(max(0, extra)):
                f = OurFlag(self.next_id, c, turn)
                self.next_id += 1
                alive.append(f)
        for f in alive:
            f.new = False
            f.came = f.came if f.c != f.end else f.came
        alive.sort(key=lambda f: f.id)
        self.flags = alive
        self.lost_now = lost
        self.lost_total += lost
        if self.lost_total >= 2:
            self.hunted = True
        for k in [k for k, t in self.blocked.items() if t < turn]:
            del self.blocked[k]

    # ------------------------------------------------------------------ 정원 (13.1)
    def quota(self, ctx):
        if ctx.finale:
            return min(P.FLAG_FIN_MAX, ctx.eco.n_bld[1] + P.FLAG_FIN_EXTRA)
        return P.FLAG_MID

    def spawn_count(self, ctx):
        turn = ctx.turn
        alive = len(self.flags)
        R = ctx.eco.R[0]
        sched_now = 0
        if turn <= P.OPEN_FLAG_SCHEDULE[-1][0]:
            target = 0
            for t, n in P.OPEN_FLAG_SCHEDULE:
                if t <= turn:
                    target += n
                if t == turn:
                    sched_now = n
            if turn == P.OPEN_FLAG_SCHEDULE[-1][0] and self.n_open > P.FLAG_OPEN:
                target += self.n_open - P.FLAG_OPEN
                sched_now += self.n_open - P.FLAG_OPEN
            n = min(max(0, target - alive), sched_now + 1)
        else:
            q = self.quota(ctx)
            step = P.FLAG_FIN_STEP if ctx.finale else 1
            n = min(max(0, q - alive), step)
            if turn > P.LAST_TURN - 5 and not ctx.finale:
                n = 0
        return max(0, min(n, R // P.COST['F']))

    # ------------------------------------------------------------------ 일 배정 (13.2)
    def _cap_turns(self, ctx, b):
        return 1 if ctx.td.owner[b.i] == -1 else 2

    def _time_ok(self, ctx, f, b):
        if ctx.turn < P.ENDGAME_TURN:
            return True
        arr = self.mp.dist[f.c][b.c]
        return ctx.turn + arr + self._cap_turns(ctx, b) - 1 <= P.LAST_TURN

    def _valid(self, ctx, f, eflag_cells):
        td, mp = ctx.td, self.mp
        t = f.task
        if t is None:
            return False
        if t == 'F8':
            return f.goal is not None and self._park_ok(ctx, f.goal)
        if f.bi is None:
            return False
        b = mp.blds[f.bi]
        o = td.owner[f.bi]
        if (f.id, f.bi) in self.blocked:
            return False
        if t == 'F1':
            return b.c in eflag_cells and (o == 0 or (o == -1 and f.bi in ctx.mem.retake)) \
                and mp.dist[f.c][b.c] <= 1
        if o == 0:
            return False
        if not self._time_ok(ctx, f, b):
            return False
        if t == 'F2':
            return o == -1
        if t == 'F3':
            return o != 1 or f.c == b.c
        if t == 'F4':
            return ctx.terr.T[b.c] or mp.dist[f.c][b.c] <= 2
        if t == 'F5':
            return b.c in ctx.terr.Fset or f.c == b.c
        if t == 'F7':
            return ctx.threat.Ed(b.c, 2) == 0 or f.c == b.c
        return True

    def _set(self, f, task, bi, taken, goal=None):
        if f.bi is not None and taken.get(f.bi) == f.id:
            del taken[f.bi]
        f.task = task
        f.bi = bi
        if bi is not None:
            taken[bi] = f.id
            f.goal = self.mp.blds[bi].c
        else:
            f.goal = goal
        f.stall = 0
        f.best_d = INF

    def _raid_ok(self, ctx, f, b):
        th = ctx.threat
        mp = self.mp
        if th.Ed(b.c, 2) != 0:
            return False
        for ef in ctx.mem.eflags:
            if mp.dist[ef.c][b.c] <= P.FREE_RAID_FLAG_R:
                return False
        return self._safe_path(ctx, f.c, b.c, zero_only=True, inside=False) is not None

    def _candidates(self, ctx, f, taken):
        mp, td, th, terr = self.mp, ctx.td, ctx.threat, ctx.terr
        out = []
        if f.lane is not None:
            while f.li < len(f.lane) and td.owner[f.lane[f.li]] == 0:
                f.li += 1
            if f.li < len(f.lane):
                bi = f.lane[f.li]
                b = mp.blds[bi]
                if bi not in taken and td.owner[bi] != 1 and (f.id, bi) not in self.blocked \
                        and self._time_ok(ctx, f, b):
                    out.append((RANK['F3'], -INF, bi))
        for b in mp.blds:
            if td.owner[b.i] == 0 or b.i in taken or (f.id, b.i) in self.blocked:
                continue
            if b.i in self.reserved:
                continue
            if not self._time_ok(ctx, f, b):
                continue
            arr = mp.dist[f.c][b.c]
            if arr >= INF:
                continue
            sc = ctx.flag_value(b) / (arr + self._cap_turns(ctx, b))
            if terr.T[b.c] and b.c not in terr.Fset:
                out.append((RANK['F4'], -sc, b.i))
            elif b.c in terr.Fset:
                if th.E1[b.c] <= th.A1[b.c]:
                    out.append((RANK['F5'], -sc, b.i))
            elif P.FREE_RAID and not self.hunted and self._raid_ok(ctx, f, b):
                out.append((RANK['F7'], -sc, b.i))
        out.sort()
        return out

    def assign_tasks(self, ctx):
        mp, td, mem = self.mp, ctx.td, ctx.mem
        eflag_cells = {}
        for ef in mem.eflags:
            eflag_cells[ef.c] = eflag_cells.get(ef.c, 0) + 1
        taken = {}
        flags = self.flags
        for f in flags:
            if f.squad is not None:
                f.task = 'F6'
                continue
            if f.task == 'F6':
                f.task = None
            if not self._valid(ctx, f, eflag_cells):
                f.task, f.bi = None, None
                if f.task != 'F8':
                    f.goal = None
            elif f.bi is not None:
                taken[f.bi] = f.id
        # 진행 정체 (13.2)
        for f in flags:
            if f.task in ('F3', 'F4', 'F5', 'F7', 'F2') and f.goal is not None:
                d = mp.dist[f.c][f.goal]
                if d < f.best_d:
                    f.best_d = d
                    f.stall = 0
                elif d > 0:
                    f.stall += 1
                    if f.stall >= P.FLAG_STALL:
                        self.blocked[(f.id, f.bi)] = ctx.turn + P.STALL_COOLDOWN
                        if taken.get(f.bi) == f.id:
                            del taken[f.bi]
                        f.task, f.bi, f.goal = None, None, None
        own_or_retake = [b for b in mp.blds
                         if td.owner[b.i] == 0 or (td.owner[b.i] == -1 and b.i in mem.retake)]
        # F1: 상대 깃발이 우리 건물 위
        for b in sorted(own_or_retake, key=lambda b: (-ctx.bld_value(b), b.i)):
            if b.c not in eflag_cells:
                continue
            cur = taken.get(b.i)
            if cur is not None and self.byid(cur).task == 'F1':
                continue
            cands = [f for f in flags if f.task not in ('F1', 'F6')
                     and mp.dist[f.c][b.c] <= 1]
            if not cands:
                continue
            f = min(cands, key=lambda f: (mp.dist[f.c][b.c], -RANK.get(f.task, 9), f.id))
            self._set(f, 'F1', b.i, taken)
        # F2: 재점령
        for b in sorted(own_or_retake, key=lambda b: (-ctx.bld_value(b), b.i)):
            if td.owner[b.i] != -1 or b.c in eflag_cells or b.i in taken:
                continue
            cands = [f for f in flags if f.task not in ('F1', 'F2', 'F6')
                     and (f.id, b.i) not in self.blocked]
            if not cands:
                continue
            f = min(cands, key=lambda f: (mp.dist[f.c][b.c], f.id))
            if mp.dist[f.c][b.c] >= INF:
                continue
            self._set(f, 'F2', b.i, taken)
        # 나머지: 히스테리시스를 두고 가장 좋은 일
        for f in flags:
            if f.task in ('F1', 'F2', 'F6'):
                continue
            cands = self._candidates(ctx, f, taken)
            if f.task in ('F3', 'F4', 'F5', 'F7') and f.bi is not None:
                cur_rank = RANK[f.task]
                b = mp.blds[f.bi]
                cur_sc = ctx.flag_value(b) / (mp.dist[f.c][b.c] + self._cap_turns(ctx, b))
                better = None
                for rk, nsc, bi in cands:
                    if rk < cur_rank or (rk == cur_rank and -nsc >= P.FLAG_SWITCH * cur_sc):
                        better = (rk, bi)
                        break
                    if rk > cur_rank:
                        break
                if better is None:
                    continue
                task = {v: k for k, v in RANK.items()}[better[0]]
                self._set(f, task, better[1], taken)
                continue
            if cands:
                rk, nsc, bi = cands[0]
                task = {v: k for k, v in RANK.items()}[rk]
                self._set(f, task, bi, taken)
            elif f.task != 'F8':
                self._set(f, 'F8', None, taken, goal=None)
        # 주차 칸 (13.6)
        used = {f.park_for for f in flags if f.task == 'F8' and f.park_for is not None
                and f.goal is not None and self._park_ok(ctx, f.goal)}
        for f in flags:
            if f.task != 'F8':
                f.park_for = None
                continue
            if f.goal is not None and self._park_ok(ctx, f.goal):
                continue
            f.goal = self._park_cell(ctx, f, used)

    def byid(self, fid):
        for f in self.flags:
            if f.id == fid:
                return f
        return None

    # ------------------------------------------------------------------ 주차 (13.6)
    def _park_ok(self, ctx, c):
        terr, th = ctx.terr, ctx.threat
        return (terr.T[c] and th.E1[c] == 0 and c not in terr.Fset and c not in self.mp.bld_at)

    def _park_cell(self, ctx, f, used):
        mp, td = self.mp, ctx.td
        eng = [b for b in mp.by_kind.get('ENG', []) if td.owner[b.i] == 0]
        targets = (eng if len(eng) == 1 else []) + \
            [b for b in mp.by_kind.get('HALL', []) if td.owner[b.i] == 0] + \
            [b for b in mp.by_kind.get('HOSPITAL', []) if td.owner[b.i] == 0]
        # 영역 안쪽 건물만 기준으로 삼는다 (전진 기지는 경주 수비가 맡는다)
        terr = ctx.terr
        targets = [b for b in targets if terr.T[b.c] and b.c not in terr.Fset]
        anchor = None
        for b in targets:
            if b.i not in used:
                anchor = b.c
                f.park_for = b.i
                used.add(b.i)
                break
        if anchor is None:
            anchor = mp.base_us
            f.park_for = None
        best = None
        for c in mp.cells:
            if not self._park_ok(ctx, c):
                continue
            k = (mp.dist[c][anchor], mp.dist[f.c][c], c)
            if best is None or k < best[0]:
                best = (k, c)
        return best[1] if best is not None else mp.base_us

    # ------------------------------------------------------------------ 이동 (13.3)
    def _safe_path(self, ctx, u, g, zero_only=True, inside=True):
        """E1 = 0 칸(영역 안이면 경계 칸 제외)만 밟는 최단 + DETOUR 이하 경로."""
        mp, th, terr = self.mp, ctx.threat, ctx.terr
        limit = mp.dist[u][g] + P.DETOUR_MAX
        prev = {u: None}
        q = deque([(u, 0)])
        while q:
            x, d = q.popleft()
            if x == g:
                path = []
                while x != u:
                    path.append(x)
                    x = prev[x]
                path.reverse()
                return path
            for v in mp.nbrs[x]:
                if v in prev:
                    continue
                if v != g:
                    if zero_only and th.E1[v] > 0:
                        continue
                    if inside and v in terr.Fset:
                        continue
                if d + 1 + mp.dist[v][g] > limit:
                    continue
                prev[v] = x
                q.append((v, d + 1))
        return None

    def next_step(self, ctx, f, g):
        mp, th, terr = self.mp, ctx.threat, ctx.terr
        u = f.c
        if u == g:
            return u
        if terr.T[u] and terr.T[g]:
            path = self._safe_path(ctx, u, g, zero_only=True, inside=True)
            if path:
                return path[0]
        opts = mp.toward(u, g)
        if not opts:
            return u
        ld = f.last_dir

        def key(v):
            interior = terr.T[v] and v not in terr.Fset
            return (0 if th.E1[v] == 0 else 1, th.E1[v], 0 if interior else 1,
                    0 if ld is not None and mp.dir_of(u, v) == ld else 1, v)
        opts.sort(key=key)
        return opts[0]

    def need_at(self, ctx, f, x, goal):
        th, td, mp = ctx.threat, ctx.td, self.mp
        E = th.E1[x]
        margin_cell = 1 if self.hunted else P.FLAG_MARGIN_CELL
        if E == 0:
            return margin_cell if self.hunted and x != goal else 0
        b = mp.bld_at.get(x)
        if b is not None:
            o = td.owner[b.i]
            if x == goal and (o != 0 or td.F[1][x] > 0):
                return E          # 점령·경합·처치 진입: 여유 0
            if o == 0:
                return E + P.FLAG_MARGIN_OWN
        return E + margin_cell

    def plan_moves(self, ctx, squad_goals):
        mp, td = self.mp, ctx.td
        for f in self.flags:
            f.opt = 0
            f.tag = None
            if f.squad is not None and f.id in squad_goals:
                f.goal = squad_goals[f.id]
            g = f.goal if f.goal is not None else f.c
            if ctx.last:
                x = self._last_turn_entry(ctx, f)
                if x is not None:
                    f.opts = [('move', x, 0)]
                    continue
            u = f.c
            need_u = self.need_at(ctx, f, u, g)
            if u == g:
                f.opts = [('stay', u, need_u, 0)]
                if need_u > 0:
                    f.opts.append(('evade',))
                continue
            x = self.next_step(ctx, f, g)
            if x == u:
                f.opts = [('stay', u, need_u, 0)]
                if need_u > 0:
                    f.opts.append(('evade',))
                continue
            need_x = self.need_at(ctx, f, x, g)
            f.opts = [('move', x, need_x), ('stay', u, need_u, need_x)]
            if need_u > 0:
                f.opts.append(('evade',))

    def _last_turn_entry(self, ctx, f):
        """160턴: 점수를 바꾸는 진입은 생존이 불확실해도 시도한다 (18.3)."""
        mp, td, mem = self.mp, ctx.td, ctx.mem
        best = None
        for v in mp.closed[f.c]:
            b = mp.bld_at.get(v)
            if b is None or td.owner[b.i] == 0:
                continue
            if td.F[1][v] > 0 and td.owner[b.i] == -1:
                continue
            gain = mem.score_of(b.i)
            k = (-gain, mp.dist[f.c][v], v)
            if best is None or k < best[0]:
                best = (k, v)
        return best[1] if best is not None else None

    def option_slots(self, ctx):
        out = []
        for f in self.flags:
            if f.opt >= len(f.opts):
                continue
            o = f.opts[f.opt]
            if o[0] == 'move' and o[2] > 0:
                out.append(Slot(('escort', f.id, o[1]), o[1], o[2], P0c, deadline=1,
                                atomic=True, value=float(o[2]), meta=f))
            elif o[0] == 'stay':
                if o[2] > 0:
                    out.append(Slot(('escort', f.id, o[1]), o[1], o[2], P0c, deadline=1,
                                    atomic=True, value=float(o[2]), meta=f))
                if o[3] > 0:
                    out.append(Slot(('gather', f.id), o[1], o[3], P1b, deadline=2,
                                    value=float(o[3]), meta=f))
        return out

    def verify(self, ctx, asg):
        """S10: 호위가 채워지지 않은 깃발은 다음 선택지로."""
        bad = 0
        for f in self.flags:
            if f.opt >= len(f.opts):
                continue
            o = f.opts[f.opt]
            if o[0] in ('move', 'stay') and o[2] > 0:
                s = asg.by_key.get(('escort', f.id, o[1]))
                ok = s is not None and not s.failed and asg.endc[o[1]] >= o[2]
                if not ok:
                    f.opt += 1
                    bad += 1
        return bad

    def finalize(self, ctx, asg):
        """최종 깃발 이동을 정하고 (출발, 도착, 꼬리표) 목록을 돌려준다."""
        mp, th = self.mp, ctx.threat
        res = []
        endc = asg.endc if asg is not None else None
        for f in self.flags:
            o = f.opts[f.opt] if f.opt < len(f.opts) else ('evade',)
            if o[0] == 'move':
                end = o[1]
            elif o[0] == 'stay':
                end = f.c
            else:
                end = self._evade_cell(ctx, f, endc)
                f.tag = 'EVADE'
            f.end = end
            res.append((f, f.c, end))
        return res

    def _evade_cell(self, ctx, f, endc):
        mp, td, th = self.mp, ctx.td, ctx.threat
        best = None
        for v in mp.closed[f.c]:
            our = endc[v] if endc is not None else td.W[0][v]
            risk = th.E1[v] - our
            b = mp.bld_at.get(v)
            own_b = 1 if (b is not None and td.owner[b.i] == 0) else 0
            k = (max(0, risk), own_b, risk, 0 if v == f.c else 1, v)
            if best is None or k < best[0]:
                best = (k, v)
        return best[1]

    def capture_info(self, ctx, moves=None):
        """이번 이동 뒤 비소유 건물 위 깃발의 점령 비용 (E-35) 등."""
        mp, td, eco, th, mem = self.mp, ctx.td, ctx.eco, ctx.threat, ctx.mem
        seen = set()
        C = 0
        depot_n = 0
        depot_cost = 0
        eng_sure = False
        caps = []
        for f in self.flags:
            e = f.end
            b = mp.bld_at.get(e)
            if b is None or td.owner[b.i] == 0 or b.i in seen:
                continue
            seen.add(b.i)
            cost = mp.cap_cost(b, eco.lib[0])
            C += cost
            caps.append(b)
            if td.owner[b.i] == -1 and td.F[1][e] == 0:
                if b.kind == 'DEPOT' and not mem.depot_claimed[0][b.i]:
                    depot_n += 1
                    depot_cost += cost
                if b.kind == 'ENG' and th.E1[e] == 0 and \
                        not any(td.F[1][v] > 0 for v in mp.closed[e]):
                    eng_sure = True
        return C, caps, depot_n, depot_cost, eng_sure

    def commit(self, ctx, moves):
        for f, a, e in moves:
            if e != a:
                f.last_dir = self.mp.dir_of(a, e) or f.last_dir
                f.came = a
            else:
                f.came = None
            f.c = e

    def new_flag(self, ctx, site):
        f = OurFlag(self.next_id, site, ctx.turn)
        self.next_id += 1
        f.new = True
        f.site = site
        self.spawned_total += 1
        if self.plan is not None and self.next_lane < len(self.plan.lanes):
            f.lane = list(self.plan.lanes[self.next_lane])
            f.site = self.plan.sites[self.next_lane]
            self.next_lane += 1
        self.flags.append(f)
        return f
