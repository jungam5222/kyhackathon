"""INIT 분석 (지침서 6장): 이웃 표, 전 칸 BFS 거리, φ, 섹터, 건물·대칭 짝, 거점."""
import math
from collections import deque

import params as P

N = 15
NC = N * N
INF = 10 ** 6
# 출력 순서(12.8)와 같은 U → R → D → L
DIRS = (('U', 0, -1), ('R', 1, 0), ('D', 0, 1), ('L', -1, 0))
DIR_RANK = {'U': 0, 'R': 1, 'D': 2, 'L': 3}
DIR_DELTA = {d: (dx, dy) for d, dx, dy in DIRS}
ROW_CHARS = frozenset('.#BH')


def cell(x, y):
    return y * N + x


def cx(c):
    return c % N


def cy(c):
    return c // N


def yx(c):
    """정렬 키: (y, x) 순."""
    return c


def cheb(a, b):
    return max(abs(cx(a) - cx(b)), abs(cy(a) - cy(b)))


def _is_row(tok):
    return len(tok) == N and all(ch in ROW_CHARS for ch in tok)


def parse_init(lines):
    team = None
    rows = []
    blds = []
    bases = {}
    i = 0
    n = len(lines)
    while i < n:
        t = lines[i].split()
        i += 1
        if not t:
            continue
        k = t[0]
        if k == 'TEAM' and len(t) >= 2:
            team = t[1]
        elif k == 'MAP':
            rows.extend(tok for tok in t[1:] if _is_row(tok))
            while len(rows) < N and i < n:
                nt = lines[i].split()
                if nt and all(_is_row(tok) for tok in nt):
                    rows.extend(nt)
                    i += 1
                else:
                    break
        elif k == 'BUILDINGS':
            cnt = int(t[1]) if len(t) > 1 else 17
            for _ in range(cnt):
                if i >= n:
                    break
                bt = lines[i].split()
                if len(bt) >= 4 and bt[0].lstrip('-').isdigit():
                    blds.append((int(bt[0]), int(bt[1]), int(bt[2]), bt[3]))
                    i += 1
                else:
                    break
        elif k == 'BASE' and len(t) >= 4:
            bases[t[1]] = (int(t[2]), int(t[3]))
    return team, rows[:N], blds, bases


class Building:
    __slots__ = ('i', 'id', 'c', 'x', 'y', 'kind', 'pair', 'region',
                 'delta', 'side', 'est', 'ub', 'lb', 'phi', 'sec')

    def __repr__(self):
        return f"B{self.id}({self.kind}@{self.x},{self.y})"


class MapInfo:
    def __init__(self, lines):
        team, rows, blds, bases = parse_init(lines)
        if len(rows) < N:
            rows = rows + ['.' * N] * (N - len(rows))
        self.rows = rows
        self.team = team if team in ('Y', 'K') else 'Y'
        self.enemy = 'K' if self.team == 'Y' else 'Y'
        self.passable = [False] * NC
        hcells = []
        for y in range(N):
            for x in range(N):
                ch = rows[y][x]
                c = cell(x, y)
                self.passable[c] = ch != '#'
                if ch == 'H':
                    hcells.append(c)
        # 본진
        if self.team in bases and self.enemy in bases:
            self.base_us = cell(*bases[self.team])
            self.base_e = cell(*bases[self.enemy])
        else:
            hs = sorted(hcells, key=lambda c: (cx(c), cy(c)))
            if len(hs) >= 2:
                yb, kb = hs[0], hs[-1]
            else:
                yb, kb = cell(2, 2), cell(12, 12)
            self.base_us, self.base_e = (yb, kb) if self.team == 'Y' else (kb, yb)
        self.passable[self.base_us] = True
        self.passable[self.base_e] = True
        self.cells = [c for c in range(NC) if self.passable[c]]
        # 이웃 표 (고정 순서 U, R, D, L)
        self.nbrs = [[] for _ in range(NC)]
        self.nbr_dir = [[] for _ in range(NC)]
        for c in self.cells:
            x, y = cx(c), cy(c)
            for d, dx, dy in DIRS:
                nx, ny = x + dx, y + dy
                if 0 <= nx < N and 0 <= ny < N and self.passable[cell(nx, ny)]:
                    self.nbrs[c].append(cell(nx, ny))
                    self.nbr_dir[c].append(d)
        self.closed = [[c] + self.nbrs[c] for c in range(NC)]
        # 거리 표
        self.dist = [None] * NC
        for s in self.cells:
            self.dist[s] = self._bfs(s)
        for c in range(NC):
            if self.dist[c] is None:
                self.dist[c] = [INF] * NC
        self.D = self.dist[self.base_us][self.base_e]
        # 퍼텐셜 φ (음수 = 우리 쪽)
        du, de = self.dist[self.base_us], self.dist[self.base_e]
        self.phi = [0] * NC
        for c in self.cells:
            if du[c] >= INF or de[c] >= INF:
                self.phi[c] = INF
            else:
                self.phi[c] = du[c] - de[c]
        # 섹터
        vx = cx(self.base_e) - cx(self.base_us)
        vy = cy(self.base_e) - cy(self.base_us)
        norm = math.hypot(vx, vy) or 1.0
        self.nsec = int(math.ceil(P.SECTOR_SPAN / P.SECTOR_W))
        half = P.SECTOR_SPAN / 2.0
        self.sector = [0] * NC
        for c in range(NC):
            psi = ((cx(c) - 7) * (-vy) + (cy(c) - 7) * vx) / norm
            k = int(math.floor((psi + half) / P.SECTOR_W))
            self.sector[c] = min(max(k, 0), self.nsec - 1)
        # 건물
        self.blds = []
        self.bld_at = {}
        self.bid_index = {}
        # 건물 순회 순서는 id가 아니라 (y, x) 순 — 정규 좌표계에서 진영과 무관해진다
        for (bid, x, y, kind) in sorted(blds, key=lambda t: (t[2], t[1], t[0])):
            b = Building()
            b.i = len(self.blds)
            b.id, b.x, b.y, b.kind = bid, x, y, kind
            b.c = cell(x, y)
            if kind == 'PLAZA':
                b.region = 'plaza'
            elif 5 <= x <= 9:
                b.region = 'central'
            else:
                b.region = 'side'
            if b.region == 'plaza':
                b.est = b.ub = b.lb = P.SCORE_PLAZA
            elif b.region == 'central':
                b.est, b.ub, b.lb = P.SCORE_EST_CENTRAL, P.SCORE_UB_CENTRAL, 2
            else:
                b.est, b.ub, b.lb = P.SCORE_EST_SIDE, P.SCORE_UB_SIDE, 1
            b.phi = self.phi[b.c]
            b.sec = self.sector[b.c]
            self.bld_at[b.c] = b
            self.bid_index[bid] = b.i
            self.blds.append(b)
            self.passable[b.c] = True
        self.nb = len(self.blds)
        for b in self.blds:
            pc = cell(N - 1 - b.x, N - 1 - b.y)
            pb = self.bld_at.get(pc)
            b.pair = pb.i if pb is not None else b.i
        self.by_kind = {}
        for b in self.blds:
            self.by_kind.setdefault(b.kind, []).append(b)
        # 거점: 본진 + 본진 3칸 안 병원
        self.strong_us = [self.base_us] + [b.c for b in self.by_kind.get('HOSPITAL', [])
                                           if self.dist[self.base_us][b.c] <= 3]
        self.strong_e = [self.base_e] + [b.c for b in self.by_kind.get('HOSPITAL', [])
                                         if self.dist[self.base_e][b.c] <= 3]
        for b in self.blds:
            du_ = min(self.dist[s][b.c] for s in self.strong_us)
            de_ = min(self.dist[s][b.c] for s in self.strong_e)
            b.delta = du_ - de_
            if b.delta <= -2:
                b.side = 'us'
            elif b.delta >= 2:
                b.side = 'enemy'
            else:
                b.side = 'cont'
        self._ball = {}

    def _bfs(self, s):
        d = [INF] * NC
        d[s] = 0
        q = deque([s])
        nb = self.nbrs
        while q:
            u = q.popleft()
            du = d[u] + 1
            for v in nb[u]:
                if d[v] > du:
                    d[v] = du
                    q.append(v)
        return d

    def ball(self, c, r):
        """c에서 BFS 거리 r 안의 칸 목록 (캐시)."""
        key = (c, r)
        v = self._ball.get(key)
        if v is None:
            dc = self.dist[c]
            v = [u for u in self.cells if dc[u] <= r]
            self._ball[key] = v
        return v

    def dir_of(self, a, b):
        dx, dy = cx(b) - cx(a), cy(b) - cy(a)
        if dx == 0 and dy == -1:
            return 'U'
        if dx == 1 and dy == 0:
            return 'R'
        if dx == 0 and dy == 1:
            return 'D'
        if dx == -1 and dy == 0:
            return 'L'
        return None

    def step(self, c, d):
        dx, dy = DIR_DELTA[d]
        x, y = cx(c) + dx, cy(c) + dy
        if 0 <= x < N and 0 <= y < N and self.passable[cell(x, y)]:
            return cell(x, y)
        return None

    def toward(self, c, g):
        """c의 이웃 중 g까지 거리가 1 줄어드는 칸들."""
        dg = self.dist[g]
        t = dg[c] - 1
        return [v for v in self.nbrs[c] if dg[v] == t]

    def cap_cost(self, b, lib):
        base = P.CAP_COST_PLAZA if b.kind == 'PLAZA' else P.CAP_COST
        if lib:
            base = max(1, base - 1)
        return base
