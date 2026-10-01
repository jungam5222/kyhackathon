"""위협·도달 계산 (지침서 8장): E1, A1, E_d, 유효 거리, 안전 칸."""
from collections import deque

import params as P
from mapinfo import NC, INF


class Economy:
    """수입·단가·생산지·역 (7.1, 14.1)."""

    def __init__(self, mp, td):
        self.sites = [[mp.base_us], [mp.base_e]]
        self.stations = [[], []]
        eng = [0, 0]
        halls = [0, 0]
        lib = [False, False]
        self.n_bld = [0, 0]
        for b in mp.blds:
            o = td.owner[b.i]
            if o < 0:
                continue
            self.n_bld[o] += 1
            if b.kind == 'HOSPITAL':
                self.sites[o].append(b.c)
            elif b.kind == 'STATION':
                self.stations[o].append(b.c)
            elif b.kind == 'ENG':
                eng[o] += 1
            elif b.kind == 'HALL':
                halls[o] += 1
            elif b.kind == 'LIBRARY':
                lib[o] = True
        self.cost = [P.COST_W_ENG if eng[t] else P.COST['W'] for t in (0, 1)]
        self.eng = eng
        self.halls = halls
        self.lib = lib
        self.income = [P.BASE_INCOME + P.HALL_BONUS * halls[t] for t in (0, 1)]
        self.R = list(td.R)
        self.prod_rate = [self.income[t] / self.cost[t] for t in (0, 1)]
        self.tele_ok = [len(self.stations[t]) >= P.TELE_MIN_STATIONS for t in (0, 1)]


class Threat:
    def __init__(self, mp, td, eco, eflags):
        self.mp = mp
        self.td = td
        self.eco = eco
        nbrs = mp.nbrs
        We = td.W[1]
        Wu = td.W[0]
        self.ewcells = [(c, We[c]) for c in mp.cells if We[c] > 0]
        self.uwcells = [(c, Wu[c]) for c in mp.cells if Wu[c] > 0]
        # E1 (8.1)
        E1 = [0] * NC
        for c, n in self.ewcells:
            E1[c] += n
            for v in nbrs[c]:
                E1[v] += n
        self.spawn_e = eco.R[1] // eco.cost[1]
        near = set()
        for s in eco.sites[1]:
            near.add(s)
            near.update(nbrs[s])
        self.e_site_near = near
        if self.spawn_e:
            for c in near:
                E1[c] += self.spawn_e
        if eco.tele_ok[1]:
            st = eco.stations[1]
            for s in st:
                E1[s] += min(P.TELE_MAX, max(We[t] for t in st if t != s))
        self.E1 = E1
        # A1: 우리가 이번 턴 넣을 수 있는 최대 수
        A1 = [0] * NC
        for c, n in self.uwcells:
            A1[c] += n
            for v in nbrs[c]:
                A1[v] += n
        self.spawn_us = eco.R[0] // eco.cost[0]
        unear = set()
        for s in eco.sites[0]:
            unear.add(s)
            unear.update(nbrs[s])
        self.u_site_near = unear
        if self.spawn_us:
            for c in unear:
                A1[c] += self.spawn_us
        if eco.tele_ok[0]:
            st = eco.stations[0]
            for s in st:
                A1[s] += min(P.TELE_MAX, max(Wu[t] for t in st if t != s))
        self.A1 = A1
        self.eflags = eflags
        # 상대 깃발까지 유효 거리 FR (8.3)
        self.FR = self._flag_field()
        # 상대 유닛·생산지까지 거리 (경계 칸 채우는 순서)
        srcs = [c for c, _ in self.ewcells] + list(eco.sites[1])
        srcs += [f.c for f in eflags]
        self.d_enemy = self._multi_bfs(srcs)
        self.d_site_us = self._multi_bfs(list(eco.sites[0]))
        self._ed_cache = {}

    def _multi_bfs(self, srcs):
        mp = self.mp
        d = [INF] * NC
        q = deque()
        for s in srcs:
            if d[s] > 0:
                d[s] = 0
                q.append(s)
        while q:
            u = q.popleft()
            du = d[u] + 1
            for v in mp.nbrs[u]:
                if d[v] > du:
                    d[v] = du
                    q.append(v)
        return d

    def _flag_field(self):
        mp = self.mp
        fr = [INF] * NC
        tele = self.eco.tele_ok[1]
        st = self.eco.stations[1]
        for f in self.eflags:
            df = mp.dist[f.c]
            for c in mp.cells:
                if df[c] < fr[c]:
                    fr[c] = df[c]
            if tele and f.c in st:
                for t in st:
                    if t == f.c:
                        continue
                    dt = mp.dist[t]
                    for c in mp.cells:
                        v = 1 + dt[c]
                        if v < fr[c]:
                            fr[c] = v
        return fr

    # ------------------------------------------------------------------
    def deff(self, fc, b):
        """상대 깃발(칸 fc)에서 칸 b까지 유효 거리."""
        mp = self.mp
        d = mp.dist[fc][b]
        if self.eco.tele_ok[1] and fc in self.eco.stations[1]:
            for t in self.eco.stations[1]:
                if t != fc:
                    d = min(d, 1 + mp.dist[t][b])
        return d

    def Ed(self, b, d):
        """d턴 안에 칸 b에 올 수 있는 상대 전투병 최대 수 (8.2)."""
        key = (b, d)
        v = self._ed_cache.get(key)
        if v is not None:
            return v
        mp = self.mp
        db = mp.dist[b]
        tot = 0
        for c, n in self.ewcells:
            if db[c] <= d:
                tot += n
        eco = self.eco
        best = INF
        for s in eco.sites[1]:
            if db[s] < best:
                best = db[s]
        if best <= d:
            tot += eco.R[1] // eco.cost[1] + (d - best) * (eco.income[1] // eco.cost[1])
        if eco.tele_ok[1]:
            bt = None
            for t in eco.stations[1]:
                if db[t] <= d - 1 and (bt is None or db[t] < db[bt]):
                    bt = t
            if bt is not None:
                others = sum(self.td.W[1][s] for s in eco.stations[1] if s != bt)
                tot += min(P.TELE_MAX * (d - db[bt]), others)
        self._ed_cache[key] = tot
        return tot

    def Au(self, b, r):
        """이번 이동 뒤 칸 b 반경 r 안에 모을 수 있는 우리 전투병 최대 수."""
        mp = self.mp
        db = mp.dist[b]
        tot = 0
        for c, n in self.uwcells:
            if db[c] <= r + 1:
                tot += n
        for s in self.eco.sites[0]:
            if db[s] <= r + 1:
                tot += self.spawn_us
                break
        if self.eco.tele_ok[0]:
            st = self.eco.stations[0]
            if any(db[s] <= r for s in st):
                tot += min(P.TELE_MAX, max(self.td.W[0][s] for s in st))
        return tot

    def flag_virtual_sites(self):
        """상대 자원 ≥ 깃발 가격이면 상대 생산지를 가상 깃발로 본다 (8.3)."""
        if self.eco.R[1] >= P.COST['F']:
            return list(self.eco.sites[1])
        return []
