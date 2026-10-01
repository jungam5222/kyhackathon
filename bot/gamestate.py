"""턴 입력 파싱과 상태 추적 (지침서 7장).

팀 인덱스는 0 = 우리, 1 = 상대. 건물 소유는 -1 = 중립, 0 = 우리, 1 = 상대.
"""
import params as P
from mapinfo import NC, INF, cell, cheb

KIND_IDX = {'F': 0, 'W': 1, 'S': 2}


class TurnData:
    """한 턴 입력. U[team][kind][c] = 인원."""

    def __init__(self, lines, mp):
        self.turn = 0
        self.R = [0, 0]
        self.U = [[[0] * NC for _ in range(3)] for _ in range(2)]
        nb = mp.nb
        self.owner = [-1] * nb
        self.stage = [0] * nb
        self.score = [-1] * nb
        team = mp.team
        i = 0
        n = len(lines)
        while i < n:
            t = lines[i].split()
            i += 1
            if not t:
                continue
            k = t[0]
            if k == 'TURN' and len(t) >= 2:
                self.turn = int(t[1])
            elif k == 'RESOURCE' and len(t) >= 3:
                self.R = [int(t[1]), int(t[2])]
            elif k == 'UNITS':
                cnt = int(t[1]) if len(t) > 1 else 0
                for _ in range(cnt):
                    if i >= n:
                        break
                    u = lines[i].split()
                    if len(u) < 5 or u[1] not in KIND_IDX:
                        break
                    i += 1
                    ti = 0 if u[0] == team else 1
                    x, y, c = int(u[2]), int(u[3]), int(u[4])
                    if 0 <= x < 15 and 0 <= y < 15:
                        self.U[ti][KIND_IDX[u[1]]][cell(x, y)] += c
            elif k == 'BUILDINGS':
                cnt = int(t[1]) if len(t) > 1 else nb
                for _ in range(cnt):
                    if i >= n:
                        break
                    b = lines[i].split()
                    if len(b) < 7 or not b[0].lstrip('-').isdigit():
                        break
                    i += 1
                    bi = mp.bid_index.get(int(b[0]))
                    if bi is None:
                        continue
                    o = b[4]
                    self.owner[bi] = -1 if o == 'N' else (0 if o == team else 1)
                    self.stage[bi] = int(b[5])
                    self.score[bi] = int(b[6])
        self.F = [self.U[0][0], self.U[1][0]]
        self.W = [self.U[0][1], self.U[1][1]]
        self.S = [self.U[0][2], self.U[1][2]]


class EFlag:
    """상대 깃발 한 명의 추적 기록 (7.6)."""
    __slots__ = ('id', 'c', 'prev', 'stat', 'last_dir', 'hist', 'lurker', 'born')

    def __init__(self, fid, c, turn):
        self.id = fid
        self.c = c
        self.prev = c
        self.stat = 0
        self.last_dir = None
        self.hist = [c]
        self.lurker = False
        self.born = turn


class Memory:
    """턴 사이에 이어지는 정보: 점수·소유 이력·재점령·보급소·상대 깃발·상대 생산."""

    def __init__(self, mp):
        self.mp = mp
        nb = mp.nb
        self.score = [-1] * nb
        for b in mp.blds:
            if b.kind == 'PLAZA':
                self.score[b.i] = P.SCORE_PLAZA
        self.owner = [-1] * nb
        self.prev_owner = [-1] * nb
        self.owned_since = [0] * nb
        self.retake = {}            # bid -> 표시한 턴
        self.events = []            # 이번 턴 소유 이벤트 (bid, 종류)
        self.depot_claimed = [[False] * nb, [False] * nb]
        self.eflags = []
        self.next_efid = 1
        self.eflag_dead = 0         # 이번 턴 사라진 상대 깃발 수
        self.eflags_killed_total = 0
        self.prev = None
        self.w_spawned_last = 0
        self.w_loss = 0             # 이번 턴 확인된 우리 전투병 손실(= 상대 손실)
        self.enemy_w_prod = 0
        self.enemy_f_prod = 0
        self.enemy_hoard = False
        self.turn = 0

    # ------------------------------------------------------------------ 갱신
    def update(self, td):
        mp = self.mp
        self.turn = td.turn
        self.events = []
        for b in mp.blds:
            s = td.score[b.i]
            if s >= 0:
                self.score[b.i] = s
                if self.score[b.pair] < 0:
                    self.score[b.pair] = s
        # 소유 이력 (7.3)
        for b in mp.blds:
            i = b.i
            prev = self.owner[i]
            now = td.owner[i]
            self.prev_owner[i] = prev
            if now != prev:
                self.owned_since[i] = td.turn
                if prev == 0 and now == -1:
                    self.events.append((i, 'enemy_neutralized'))
                    self.retake[i] = td.turn
                elif prev == 0 and now == 1:
                    self.events.append((i, 'pulled_lost'))
                    self.retake[i] = td.turn
                elif prev == 1 and now == -1:
                    self.events.append((i, 'we_neutralized' if td.F[0][b.c] > 0 else 'enemy_lost'))
                elif now == 0:
                    self.events.append((i, 'we_captured'))
                elif now == 1:
                    self.events.append((i, 'enemy_captured'))
            self.owner[i] = now
            if now == 0:
                self.retake.pop(i, None)
                if b.kind == 'DEPOT':
                    self.depot_claimed[0][i] = True
            elif now == 1 and b.kind == 'DEPOT':
                self.depot_claimed[1][i] = True
        for i in sorted(self.retake):
            if td.turn - self.retake[i] > P.RETAKE_MEMORY:
                del self.retake[i]
        self._track_enemy_flags(td)
        # 손실·상대 생산 추정 (7.5, 7.7)
        if self.prev is not None:
            pw_us = sum(self.prev.W[0])
            cw_us = sum(td.W[0])
            self.w_loss = max(0, pw_us + self.w_spawned_last - cw_us)
            pw_e = sum(self.prev.W[1])
            cw_e = sum(td.W[1])
            self.enemy_w_prod = max(0, cw_e - pw_e + self.w_loss)
            pf_e = sum(self.prev.F[1])
            cf_e = sum(td.F[1])
            self.enemy_f_prod = max(0, cf_e - pf_e + self.eflag_dead)
        self.enemy_hoard = td.R[1] >= 30
        self.prev = td

    def _track_enemy_flags(self, td):
        mp = self.mp
        dist = mp.dist
        cur = []
        for c in mp.cells:
            n = td.F[1][c]
            for _ in range(n):
                cur.append(c)
        prev = self.eflags
        est = set()
        if self.prev is not None:
            est = {b.c for b in mp.by_kind.get('STATION', []) if self.prev.owner[b.i] == 1}
        pairs = []
        for pi, f in enumerate(prev):
            for qi, q in enumerate(cur):
                d = dist[f.c][q]
                if d <= 1:
                    pairs.append((d, f.id, q, pi, qi))
                elif len(est) >= 2 and f.c in est and q in est:
                    pairs.append((2, f.id, q, pi, qi))
        pairs.sort()
        used_p = set()
        used_q = set()
        nxt = []
        for d, _, q, pi, qi in pairs:
            if pi in used_p or qi in used_q:
                continue
            used_p.add(pi)
            used_q.add(qi)
            f = prev[pi]
            f.prev = f.c
            if q == f.c:
                f.stat += 1
            else:
                f.last_dir = mp.dir_of(f.c, q)
                f.stat = 0
            f.c = q
            f.hist.append(q)
            if len(f.hist) > 5:
                f.hist.pop(0)
            nxt.append(f)
        self.eflag_dead = len(prev) - len(used_p)
        self.eflags_killed_total += self.eflag_dead
        for qi, q in enumerate(cur):
            if qi not in used_q:
                nxt.append(EFlag(self.next_efid, q, td.turn))
                self.next_efid += 1
        # 잠복 표시
        key_cells = [b.c for b in mp.blds
                     if td.owner[b.i] == 0 and b.kind in ('ENG', 'HALL', 'HOSPITAL')]
        for f in nxt:
            f.lurker = (f.stat >= P.LURK_STATIONARY and
                        any(dist[f.c][k] <= P.LURK_RADIUS for k in key_cells))
        nxt.sort(key=lambda f: f.id)
        self.eflags = nxt

    # ------------------------------------------------------------------ 점수 (7.2)
    def score_of(self, i, kind='est'):
        s = self.score[i]
        if s >= 0:
            return s
        b = self.mp.blds[i]
        return b.est if kind == 'est' else (b.ub if kind == 'ub' else b.lb)

    def totals(self):
        """(총점 추정, 총점 상한)."""
        est = 0.0
        ub = 0.0
        for b in self.mp.blds:
            est += self.score_of(b.i, 'est')
            ub += self.score_of(b.i, 'ub')
        return est, ub

    def team_score(self, owner, td, kind='est'):
        return sum(self.score_of(b.i, kind) for b in self.mp.blds if td.owner[b.i] == owner)
