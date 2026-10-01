"""전투병 배정·이동 엔진 — 정크무빙 0 (지침서 12장).

① 고정 → ② 유지 → ③ 계속 → ④ 등급별 채우기 → ⑤ 잉여 → ⑥ 개선 → ⑦ 경로·한 걸음·후처리.
유닛 ID가 없으므로 장부(Ledger)로 그룹의 임무·출발지·경로를 이어 기록한다 (7.5).
"""
import itertools
import time
from collections import deque

import params as P
from mapinfo import NC, INF
from slots import (P0a, P0b, P0c, P0d, P1a, P1b, P1c, P2, P3, P4, P5, P6,
                   TEMP_KINDS, Slot)

TAG_EVADE, TAG_SAFE, TAG_ESCAPE, TAG_TELE = 'EVADE', 'SAFE_RETURN', 'ESCAPE', 'TELE'
_SEQ = itertools.count()     # 결정적 동률 처리용 일련번호 (INV-12)


class Rec:
    """장부 한 줄: 이동이 끝난 뒤의 기대 상태."""
    __slots__ = ('n', 'key', 'tier', 'came', 'tgt', 'r', 'path', 'orphan', 'last_dir',
                 'stall', 'ban')

    def __init__(self, n, key=None, tier=P6, came=None, tgt=None, r=0, path=None,
                 orphan=None, last_dir=None, stall=0, ban=None):
        self.n = n
        self.key = key
        self.tier = tier
        self.came = came
        self.tgt = tgt
        self.r = r
        self.path = path
        self.orphan = orphan
        self.last_dir = last_dir
        self.stall = stall
        self.ban = ban


class Grp:
    __slots__ = ('c', 'n', 'prod', 'came', 'key', 'tier', 'status', 'path', 'orphan',
                 'last_dir', 'stall', 'slot', 'step', 'tag', 'ban', 'src', 'tgt', 'r', 'seq')

    def __init__(self, c, n, prod=False):
        self.seq = next(_SEQ)
        self.c = c
        self.n = n
        self.prod = prod
        self.came = None
        self.key = None
        self.tier = P6
        self.status = 'free'
        self.path = None
        self.orphan = None
        self.last_dir = None
        self.stall = 0
        self.slot = None
        self.step = None
        self.tag = None
        self.ban = None
        self.src = None
        self.tgt = None
        self.r = 0

    def clone(self, n):
        g = Grp(self.c, n, self.prod)
        g.came, g.key, g.tier, g.status = self.came, self.key, self.tier, self.status
        g.path, g.orphan, g.last_dir, g.stall = self.path, self.orphan, self.last_dir, self.stall
        g.ban, g.src, g.tgt, g.r = self.ban, self.src, self.tgt, self.r
        return g


class Ledger:
    def __init__(self):
        self.recs = {}
        self.warn = 0

    def groups(self, td):
        Wu = td.W[0]
        out = []
        cells = {c for c in range(NC) if Wu[c] > 0} | set(self.recs)
        self.warn = 0
        for c in sorted(cells):
            recs = self.recs.get(c, [])
            actual = Wu[c]
            exp = sum(r.n for r in recs)
            if actual < exp:
                lose = exp - actual
                for r in sorted(recs, key=lambda r: -r.tier):
                    k = min(lose, r.n)
                    r.n -= k
                    lose -= k
                    if lose == 0:
                        break
            elif actual > exp:
                recs.append(Rec(actual - exp))
                if exp > 0:
                    self.warn += 1
            for r in recs:
                if r.n <= 0:
                    continue
                g = Grp(c, r.n)
                g.came, g.key, g.tier, g.tgt, g.r = r.came, r.key, r.tier, r.tgt, r.r
                g.path, g.orphan, g.last_dir, g.stall, g.ban = (r.path, r.orphan, r.last_dir,
                                                                 r.stall, r.ban)
                out.append(g)
        return out


# ---------------------------------------------------------------------- 선점 표 (12.4)
def can_preempt(taker, giver):
    if taker == P0a:
        return giver != P0a
    if taker in (P0b, P0c):
        return giver >= P1a
    if taker == P0d:
        return giver == P1c or giver >= P2
    if taker in (P1a, P1b, P1c):
        return giver >= P2
    if taker in (P2, P3):
        return giver >= P4
    if taker == P4:
        return giver >= P5
    if taker == P5:
        return giver >= P6
    return False


class Assigner:
    def __init__(self, ctx, groups, slots, prod_base, prod_max, locks):
        self.ctx = ctx
        self.mp = ctx.mp
        self.dist = ctx.mp.dist
        self.E1 = ctx.threat.E1
        self.T = ctx.terr.T
        self.turn = ctx.turn
        self.groups = groups
        self.slots = slots
        self.locks = locks
        self.sites = list(ctx.eco.sites[0])
        self.prod_left = prod_base
        self.prod_extra = max(0, prod_max - prod_base)
        self.prod_used = {}
        self.pt = [0] * NC
        self.endc = [0] * NC
        self.pslots = {}
        for s in slots:
            if s.r == 0:
                self.pslots.setdefault(s.cell, []).append(s)
        for lst in self.pslots.values():
            lst.sort(key=lambda s: (s.tier, -s.need))
        self.by_key = {s.key: s for s in slots}
        self.by_cell = {}
        for g in groups:
            self.by_cell.setdefault(g.c, []).append(g)
        self.stats = {'rev': 0, 'rev_bad': 0, 'swap': 0, 'idle': 0, 'orph': 0, 'cancel_prog': 0}
        self.deadline_t = ctx.t0 + P.TIME_HARD_MS / 1000.0

    # ------------------------------------------------------------------ 기본 연산
    def cost(self, c, s):
        d = self.dist[c][s.cell]
        return d - s.r if d > s.r else 0

    def cum(self, s):
        m = 0
        for t in self.pslots.get(s.cell, ()):
            if t.tier > s.tier:
                break
            if not t.failed and t.need > m:
                m = t.need
        return m

    def area_count(self, s):
        tot = 0
        e = self.endc
        for c in self.mp.ball(s.cell, s.r):
            tot += e[c]
        return tot

    def deficit(self, s):
        if s.r == 0:
            return self.cum(s) - self.pt[s.cell]
        return s.need - self.area_count(s)

    def quick_step(self, c, s):
        """비용 0~1이면 이번 이동의 도착 칸을 바로 정한다."""
        d = self.dist[c][s.cell]
        if d <= s.r:
            return c
        if d - s.r > 1:
            return None
        if s.r == 0:
            return s.cell
        opts = self.mp.toward(c, s.cell)
        if not opts:
            return None
        opts.sort(key=lambda v: (self.E1[v], v))
        return opts[0]

    def _unhook(self, g, k):
        """g에서 k명을 기존 슬롯에서 떼어 낸다 (집계 갱신)."""
        if g.slot is not None and g.slot.r == 0 and g.status != 'orphan':
            self.pt[g.slot.cell] -= k
        if g.step is not None:
            self.endc[g.step] -= k

    def _hook(self, g, s, status):
        g.slot = s
        g.status = status
        g.tier = s.tier
        if s.r == 0:
            self.pt[s.cell] += g.n
        st = self.quick_step(g.c, s)
        g.step = st
        if st is not None:
            self.endc[st] += g.n

    def take(self, g, k, s, status):
        """그룹 g에서 k명을 슬롯 s에 배정한다. 나뉘면 새 그룹을 돌려준다."""
        if k >= g.n:
            self._unhook(g, g.n)
            g.step = None
            self._hook(g, s, status)
            return g
        self._unhook(g, k)
        ng = g.clone(k)
        g.n -= k
        ng.step = None
        self.groups.append(ng)
        self.by_cell.setdefault(ng.c, []).append(ng)
        self._hook(ng, s, status)
        return ng

    def take_prod(self, site, k, s, allow_extra):
        use = min(k, self.prod_left)
        rest = k - use
        self.prod_left -= use
        if rest > 0 and allow_extra:
            ex = min(rest, self.prod_extra)
            self.prod_extra -= ex
            use += ex
        if use <= 0:
            return None
        g = Grp(site, use, prod=True)
        self.groups.append(g)
        self.by_cell.setdefault(site, []).append(g)
        self.prod_used[site] = self.prod_used.get(site, 0) + use
        self._hook(g, s, 'asg')
        return g

    def prod_avail(self, s):
        return self.prod_left + (self.prod_extra if s.tier <= P0d else 0)

    # ------------------------------------------------------------------ 전체 실행
    def run(self):
        self._classify()
        self._lock()
        self._retain()
        self._continue()
        self._fill()
        self._surplus()
        if time.perf_counter() < self.deadline_t:
            self._improve()
        self._steps()
        self._post()
        return self

    def _classify(self):
        turn = self.turn
        for g in self.groups:
            s = self.by_key.get(g.key) if g.key is not None else None
            g.src = s
            if s is None:
                if g.key is not None and g.key[0] in TEMP_KINDS and g.orphan is None:
                    g.orphan = turn
                g.key = None
            if g.orphan is not None and turn - g.orphan < P.SLOT_TTL and s is None:
                g.status = 'orphan'
            else:
                g.orphan = None
                g.status = 'free'
            if g.ban is not None and g.ban[1] < turn:
                g.ban = None

    def _moving(self, g):
        if g.tgt is None:
            return False
        d = self.dist[g.c][g.tgt]
        return d > g.r

    def _lock(self):
        for (cell, k, s) in self.locks:
            if s is None:
                continue
            for g in list(self.by_cell.get(cell, ())):
                if k <= 0:
                    break
                if g.n <= 0 or g.prod or g.slot is not None:
                    continue
                m = min(k, g.n)
                self.take(g, m, s, 'lock')
                k -= m
        for s in self.slots:
            if s.key[0] == 'guard' and s.r == 0:
                k = s.need - self.pt[s.cell]
                for g in list(self.by_cell.get(s.cell, ())):
                    if k <= 0:
                        break
                    if g.n <= 0 or g.prod or g.slot is not None:
                        continue
                    m = min(k, g.n)
                    self.take(g, m, s, 'lock')
                    k -= m

    def _retain(self):
        # point 슬롯: 서 있는 칸의 누적 목표까지
        for cell in sorted(self.pslots):
            lst = self.pslots[cell]
            stand = [g for g in self.by_cell.get(cell, ())
                     if g.n > 0 and not g.prod and g.slot is None and not self._moving(g)]
            if not stand:
                continue
            stand.sort(key=lambda g: (0 if g.src is not None and g.src.cell == cell else 1,
                                      0 if g.status == 'free' else 1))
            run_max = 0
            for s in lst:
                run_max = max(run_max, s.need)
                want = run_max - self.pt[cell]
                while want > 0 and stand:
                    g = stand[0]
                    if g.ban is not None and g.ban[0] == s.key:
                        stand.pop(0)
                        continue
                    m = min(want, g.n)
                    ng = self.take(g, m, s, 'retain')
                    want -= m
                    if ng is g or g.n <= 0:
                        stand.pop(0)
        # area 슬롯: 반경 안 인원 중 가까운 순으로 정확히 k명
        for s in self.slots:
            if s.r == 0:
                continue
            want = s.need - self.area_count(s)
            if want <= 0:
                continue
            db = self.dist[s.cell]
            cand = []
            for c in self.mp.ball(s.cell, s.r):
                for g in self.by_cell.get(c, ()):
                    if g.n > 0 and not g.prod and g.slot is None and not self._moving(g):
                        cand.append((db[c], c, g.seq, g))
            cand.sort(key=lambda t: (t[0], t[1], t[2]))
            for _, _, _, g in cand:
                if want <= 0:
                    break
                m = min(want, g.n)
                self.take(g, m, s, 'retain')
                want -= m

    def _continue(self):
        for g in list(self.groups):
            if g.n <= 0 or g.slot is not None or g.src is None or g.prod:
                continue
            if not self._moving(g):
                continue
            s = g.src
            if s.failed:
                continue
            c = self.cost(g.c, s)
            if c > s.deadline:
                continue
            dfc = self.deficit(s)
            if dfc <= 0:
                if s.key[0] in TEMP_KINDS:
                    g.orphan = self.turn
                    g.status = 'orphan'
                continue
            m = min(dfc, g.n)
            ng = self.take(g, m, s, 'cont')
            if ng is not g and g.n > 0 and s.key[0] in TEMP_KINDS:
                g.orphan = self.turn
                g.status = 'orphan'

    # ------------------------------------------------------------------ ④ 등급별 채우기
    def _candidates(self, s):
        dl = s.deadline
        if dl <= 3:
            cells = self.mp.ball(s.cell, s.r + dl)
            pool = []
            for c in cells:
                pool.extend(self.by_cell.get(c, ()))
        else:
            pool = self.groups
        out = []
        phi = self.mp.phi
        for g in pool:
            if g.n <= 0 or g.prod or g.slot is s:
                continue
            if g.ban is not None and g.ban[0] == s.key:
                continue
            c = self.cost(g.c, s)
            if c > dl:
                continue
            # 이미 이 슬롯 집계에 잡힌 인원은 후보가 아니다
            if g.step is not None:
                if s.r == 0 and g.slot is not None and g.slot.r == 0 and g.slot.cell == s.cell:
                    continue
                if s.r > 0 and self.dist[g.step][s.cell] <= s.r:
                    continue
            st = g.status
            extra = 0
            k = g.n
            if st == 'free':
                if g.src is not None and g.src is not s:
                    extra = P.SWITCH_COST
            elif st == 'orphan':
                if not (s.tier <= P1c or c == 0):
                    continue
            elif st == 'lock':
                if not (s.tier == P0a and g.slot.tier != P0a):
                    continue
            else:
                inside = False
                if g.slot is not None and g.slot.r > 0 and c <= 1:
                    # area 예약은 반경 밖으로 못 나가게 할 뿐이다: 반경 안에서 옮기는 것은 허용
                    end = self.quick_step(g.c, s)
                    inside = end is not None and self.dist[end][g.slot.cell] <= g.slot.r
                if not inside and (g.slot is None or not can_preempt(s.tier, g.slot.tier)):
                    continue
                extra = 0 if inside else P.SWITCH_COST
                if s.tier == P0d and g.slot.key[0] in ('screen', 'screen2'):
                    keep = 1 if not self._last_one_ok(g.c, s) else 0
                    k = min(k, max(0, self.pt[g.c] - keep))
                    if k <= 0:
                        continue
            out.append((c + extra, 0 if c == 0 else 1, phi[g.c], g.c, g.seq, k, g))
        pa = self.prod_avail(s)
        if pa > 0:
            for site in self.sites:
                c = self.cost(site, s)
                if c <= dl:
                    out.append((c, 1, phi[site], site, -1, pa, site))
        out.sort(key=lambda t: t[:5])
        return out

    def _last_one_ok(self, c, s):
        """11.4-7: 경계 칸 마지막 1명을 사냥에 써도 되는가."""
        f = s.meta
        if f is None:
            return False
        mp = self.mp
        if c in mp.closed[f.c]:
            return False
        for o in self.ctx.mem.eflags:
            if o.id != f.id and mp.dist[o.c][c] <= 2:
                return False
        We = self.ctx.td.W[1]
        if any(We[v] > 0 for v in mp.closed[c]):
            return False
        return True

    def _fill(self):
        order = sorted(self.slots, key=lambda s: (s.tier, s.deadline, -s.value, repr(s.key)))
        check = 0
        for s in order:
            if s.failed:
                continue
            dfc = self.deficit(s)
            if dfc <= 0:
                continue
            cands = self._candidates(s)
            seen_prod = False
            total = 0
            for t in cands:
                if t[4] == -1:
                    if seen_prod:
                        continue
                    seen_prod = True
                total += t[5]
            if s.atomic and total < dfc:
                s.failed = True
                continue
            for t in cands:
                if dfc <= 0:
                    break
                k = min(dfc, t[5])
                if t[4] == -1:
                    k = min(k, self.prod_avail(s))
                    if k <= 0:
                        continue
                    if self.take_prod(t[6], k, s, s.tier <= P0d) is not None:
                        dfc -= k
                else:
                    g = t[6]
                    k = min(k, g.n)
                    if k <= 0:
                        continue
                    self.take(g, k, s, 'asg')
                    dfc -= k
            check += 1
            if check % 16 == 0 and time.perf_counter() > self.deadline_t:
                break

    # ------------------------------------------------------------------ ⑤ 잉여
    def _surplus(self):
        free = [g for g in self.groups if g.n > 0 and g.slot is None and g.status == 'free'
                and not g.prod]
        units = sum(g.n for g in free) + self.prod_left
        if units <= 0:
            return
        sups = [s for s in self.slots if s.key[0] == 'support']
        terr = self.ctx.terr
        th = self.ctx.threat
        if not sups:
            pool = terr.S if terr.S else terr.F
            if not pool:
                pool = [self.mp.base_us]
            pool = sorted(pool, key=lambda c: (th.d_enemy[c], c))[:12]
            for c in pool:
                s = Slot(('support', c), c, 0, P6, value=0.0)
                sups.append(s)
                self.slots.append(s)
                self.by_key[s.key] = s
                self.pslots.setdefault(c, []).append(s)
        sups.sort(key=lambda s: (-s.value, s.cell))
        i = 0
        while units > 0:
            s = sups[i % len(sups)]
            s.need += 1
            units -= 1
            i += 1
        for s in sups:
            dfc = self.deficit(s)
            if dfc <= 0:
                continue
            cands = []
            for g in self.groups:
                if g.n > 0 and g.slot is None and g.status == 'free' and not g.prod:
                    cands.append((self.cost(g.c, s), g.c, g.seq, g))
            cands.sort(key=lambda t: t[:3])
            for c, _, _, g in cands:
                if dfc <= 0:
                    break
                k = min(dfc, g.n)
                self.take(g, k, s, 'asg')
                dfc -= k
            if dfc > 0 and self.prod_left > 0:
                site = min(self.sites, key=lambda x: (self.cost(x, s), x))
                k = min(dfc, self.prod_left)
                self.take_prod(site, k, s, False)
        # 남은 자유 인원은 가장 가까운 지원 칸으로 (INV-07 놀림 금지)
        for g in list(self.groups):
            if g.n > 0 and g.slot is None and g.status == 'free' and not g.prod:
                s = min(sups, key=lambda s: (self.cost(g.c, s), -s.value, s.cell))
                s.need += g.n
                self.take(g, g.n, s, 'asg')
        if self.prod_left > 0:
            s = sups[0]
            site = min(self.sites, key=lambda x: (self.cost(x, s), x))
            s.need += self.prod_left
            self.take_prod(site, self.prod_left, s, False)

    # ------------------------------------------------------------------ ⑥ 개선 패스
    def _improve(self):
        movers = [g for g in self.groups
                  if g.n > 0 and g.slot is not None and g.status == 'asg' and not g.prod
                  and g.slot.tier >= P2 and g.slot.r == 0 and not g.slot.atomic
                  and self.cost(g.c, g.slot) >= 2]
        if len(movers) > P.IMPROVE_MAX_GROUPS:
            movers.sort(key=lambda g: (-self.cost(g.c, g.slot), g.seq))
            movers = movers[:P.IMPROVE_MAX_GROUPS]
        for _ in range(P.IMPROVE_PASSES):
            changed = False
            for i in range(len(movers)):
                if time.perf_counter() > self.deadline_t:
                    return
                a = movers[i]
                for j in range(i + 1, len(movers)):
                    b = movers[j]
                    if a.n != b.n or a.slot is b.slot or a.slot.tier != b.slot.tier:
                        continue
                    sa, sb = a.slot, b.slot
                    now = self.cost(a.c, sa) + self.cost(b.c, sb)
                    alt = self.cost(a.c, sb) + self.cost(b.c, sa)
                    if alt < now and self.cost(a.c, sb) <= sb.deadline \
                            and self.cost(b.c, sa) <= sa.deadline:
                        for g in (a, b):
                            if g.step is not None:
                                self.endc[g.step] -= g.n
                                g.step = None
                        a.slot, b.slot = sb, sa
                        for g in (a, b):
                            g.step = self.quick_step(g.c, g.slot)
                            if g.step is not None:
                                self.endc[g.step] += g.n
                        changed = True
            if not changed or time.perf_counter() > self.deadline_t:
                break

    # ------------------------------------------------------------------ ⑦ 경로·한 걸음
    def _next_step(self, g, tgt, r):
        mp = self.mp
        c = g.c
        if self.dist[c][tgt] <= r:
            return c
        if g.path:
            nx = g.path[0]
            if nx in mp.nbrs[c] and self.dist[nx][tgt] < INF:
                return nx
            g.path = None
        opts = mp.toward(c, tgt)
        if not opts:
            return c
        E1, T = self.E1, self.T
        ld = g.last_dir

        def key(v):
            return (1 if E1[v] > 0 else 0, E1[v], 0 if T[v] else 1,
                    0 if (ld is not None and mp.dir_of(c, v) == ld) else 1, v)
        opts.sort(key=key)
        return opts[0]

    def _detour(self, g, tgt, r, bad):
        """E1이 큰 칸을 피한 경로 (최단 + DETOUR_MAX 이하)."""
        mp = self.mp
        limit = self.dist[g.c][tgt] + P.DETOUR_MAX
        prev = {g.c: None}
        q = deque([(g.c, 0)])
        found = None
        while q:
            u, d = q.popleft()
            if self.dist[u][tgt] <= r and u != g.c:
                found = u
                break
            if d >= limit:
                continue
            for v in mp.nbrs[u]:
                if v in prev:
                    continue
                if v in bad and self.dist[v][tgt] > r:
                    continue
                if d + 1 + max(0, self.dist[v][tgt] - r) > limit:
                    continue
                prev[v] = u
                q.append((v, d + 1))
        if found is None:
            return None
        path = []
        u = found
        while u != g.c:
            path.append(u)
            u = prev[u]
        path.reverse()
        return path

    def _steps(self):
        mp = self.mp
        new_flag_near = set()
        for f in self.ctx.mem.eflags:
            if f.born == self.turn:
                for c in mp.ball(f.c, P.HUNT_NEW_FLAG_R):
                    new_flag_near.add(c)
        for g in self.groups:
            if g.n <= 0:
                continue
            if g.slot is None:
                g.step = g.c if g.step is None else g.step
                continue
            s = g.slot
            if g.step is None:
                g.step = self._next_step(g, s.cell, s.r)
                self.endc[g.step] += g.n
        # 역행 금지 (INV-03)
        for g in self.groups:
            if g.n <= 0 or g.slot is None or g.step == g.c or g.came is None:
                continue
            if g.step != g.came:
                continue
            self.stats['rev'] += g.n
            exc = (g.tag in (TAG_EVADE, TAG_SAFE) or g.slot.tier <= P1c or
                   g.c in new_flag_near)
            if not exc:
                self.stats['rev_bad'] += g.n
                self._set_step(g, g.c)
        # 무의미한 손실 금지 (INV-11)
        We = self.ctx.td.W[1]
        E1 = self.E1
        for _ in range(2):
            bad = {c for c in mp.cells if E1[c] > self.endc[c]}
            changed = False
            for g in self.groups:
                if g.n <= 0 or g.slot is None or g.step == g.c:
                    continue
                s = g.slot
                final = self.dist[g.step][s.cell] <= s.r
                if final:
                    # (나) 상대 전투병이 선 목적 칸
                    if We[g.step] > 0 and s.tier not in (P0a, P5) and \
                            not (s.atomic and not s.failed):
                        self._set_step(g, g.c)
                        changed = True
                    continue
                if s.tier <= P0d:
                    continue
                if E1[g.step] > self.endc[g.step]:
                    path = self._detour(g, s.cell, s.r, bad)
                    if path:
                        g.path = path
                        self._set_step(g, path[0])
                    else:
                        self._set_step(g, g.c)
                    changed = True
            if not changed:
                break
        # 고아: 위험하면 영역 안 안전 칸으로 (INV-11 다)
        for g in self.groups:
            if g.n <= 0 or g.slot is not None or g.prod:
                continue
            if g.status == 'orphan':
                self.stats['orph'] += g.n
            if E1[g.c] > self.endc[g.c] and g.step == g.c:
                best = None
                for v in mp.nbrs[g.c]:
                    k = (E1[v], 0 if self.T[v] else 1, v)
                    if E1[v] < E1[g.c] and (best is None or k < best[0]):
                        best = (k, v)
                if best is not None:
                    self._set_step(g, best[1])
                    g.tag = TAG_SAFE
            if g.status == 'free':
                self.stats['idle'] += g.n

    def _set_step(self, g, v):
        if g.step is not None:
            self.endc[g.step] -= g.n
        g.step = v
        self.endc[v] += g.n

    # ------------------------------------------------------------------ 후처리 (12.6)
    def _post(self):
        edges = {}
        for g in self.groups:
            if g.n <= 0 or g.step is None or g.step == g.c or g.tag == TAG_TELE:
                continue
            edges.setdefault((g.c, g.step), []).append(g)
        # 맞교환 (INV-04)
        for (a, b) in sorted(edges):
            if a > b:
                continue
            ab = edges.get((a, b))
            ba = edges.get((b, a))
            if not ab or not ba:
                continue
            self._cancel_pair(ab, ba)
        # 길이 3~4 순환 (INV-05)
        self._cancel_cycles()

    def _cancel_pair(self, ab, ba):
        na = sum(g.n for g in ab if g.n > 0 and self._cancelable(g))
        nb = sum(g.n for g in ba if g.n > 0 and self._cancelable(g))
        k = min(na, nb)
        if k <= 0:
            return
        self.stats['swap'] += 2 * k
        la = self._split_cancelable(ab, k)
        lb = self._split_cancelable(ba, k)
        # 목표만 서로 바꾼다: 제자리에 남는 쪽이 들어오려던 쪽의 슬롯을 맡는다
        for ga, gb in zip(la, lb):
            sa, sb = ga.slot, gb.slot
            ga.slot, gb.slot = sb, sa
            ga.tier, gb.tier = sb.tier, sa.tier
            self._set_step(ga, ga.c)
            self._set_step(gb, gb.c)
            ga.path = gb.path = None

    def _cancelable(self, g):
        return g.slot is not None and g.slot.tier > P0d and g.tag is None

    def _split_cancelable(self, lst, k):
        out = []
        for g in lst:
            if k <= 0:
                break
            if g.n <= 0 or not self._cancelable(g):
                continue
            if g.n <= k:
                out.append(g)
                k -= g.n
            else:
                ng = g.clone(k)
                ng.slot, ng.step, ng.tier = g.slot, g.step, g.tier
                g.n -= k
                self.groups.append(ng)
                out.append(ng)
                k = 0
        # 1명 단위 짝짓기를 위해 같은 크기로 맞춘다
        res = []
        for g in out:
            res.append(g)
        return self._unit_list(res)

    def _unit_list(self, lst):
        out = []
        for g in lst:
            while g.n > 1:
                ng = g.clone(1)
                ng.slot, ng.step, ng.tier = g.slot, g.step, g.tier
                g.n -= 1
                self.groups.append(ng)
                out.append(ng)
            out.append(g)
        return out

    def _cancel_cycles(self):
        flow = {}
        for g in self.groups:
            if g.n <= 0 or g.step is None or g.step == g.c or not self._cancelable(g):
                continue
            flow.setdefault(g.c, {}).setdefault(g.step, []).append(g)
        for a in sorted(flow):
            for b in sorted(flow.get(a, {})):
                for c in sorted(flow.get(b, {})):
                    if c == a:
                        continue
                    if a in flow.get(c, {}):
                        self._cancel_cycle([a, b, c], flow)
                    for d in sorted(flow.get(c, {})):
                        if d in (a, b):
                            continue
                        if a in flow.get(d, {}):
                            self._cancel_cycle([a, b, c, d], flow)

    def _cancel_cycle(self, nodes, flow):
        L = len(nodes)
        lists = []
        for i in range(L):
            u, v = nodes[i], nodes[(i + 1) % L]
            lst = [g for g in flow.get(u, {}).get(v, []) if g.n > 0 and g.step == v]
            if not lst:
                return
            lists.append(lst)
        k = min(sum(g.n for g in lst) for lst in lists)
        if k <= 0:
            return
        self.stats['swap'] += k * L
        units = [self._unit_list(self._split_cancelable(lst, k))[:k] for lst in lists]
        for j in range(k):
            ring = [units[i][j] for i in range(L)]
            slots = [g.slot for g in ring]
            for i in range(L):
                g = ring[i]
                # 노드 i에 남는 유닛은 노드 i로 들어오던 유닛(i-1)의 슬롯을 맡는다
                g.slot = slots[(i - 1) % L]
                g.tier = g.slot.tier
                g.path = None
                self._set_step(g, g.c)

    # ------------------------------------------------------------------ 결과
    def moves(self):
        agg = {}
        for g in self.groups:
            if g.n <= 0 or g.step is None or g.step == g.c or g.tag == TAG_TELE:
                continue
            d = self.mp.dir_of(g.c, g.step)
            if d is None:
                continue
            agg[(g.c, d)] = agg.get((g.c, d), 0) + g.n
        return agg

    def ledger_out(self, turn):
        recs = {}
        merged = {}
        for g in self.groups:
            if g.n <= 0:
                continue
            end = g.step if g.step is not None else g.c
            moved = end != g.c
            s = g.slot
            stall = g.stall
            ban = g.ban
            if s is not None and not moved and self.cost(g.c, s) > 0:
                stall += 1
                if stall >= P.GROUP_STALL:
                    ban = (s.key, turn + P.STALL_COOLDOWN)
                    stall = 0
            else:
                stall = 0
            path = None
            if g.path and moved and g.path[0] == end:
                path = g.path[1:] or None
            r = Rec(g.n,
                    key=s.key if s is not None and (ban is None or ban[0] != s.key) else None,
                    tier=s.tier if s is not None else P6,
                    came=g.c if moved else None,
                    tgt=s.cell if s is not None else None,
                    r=s.r if s is not None else 0,
                    path=path,
                    orphan=g.orphan if g.status == 'orphan' else None,
                    last_dir=self.mp.dir_of(g.c, end) if moved else g.last_dir,
                    stall=stall, ban=ban)
            # 같은 칸·같은 임무의 그룹은 합친다 (장부가 1명 단위로 쪼개지지 않게)
            mk = (end, r.key, r.tier, r.came, r.tgt, r.r, tuple(r.path) if r.path else None,
                  r.orphan, r.last_dir, r.stall, r.ban)
            prev = merged.get(mk)
            if prev is not None:
                prev.n += r.n
                continue
            merged[mk] = r
            recs.setdefault(end, []).append(r)
        return recs
