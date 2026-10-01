"""오프닝 차선 계획기 (지침서 16장).

깃발 출발 일정(1턴 2명, 3턴 2명, 4턴 1명)에 맞춰 깃발마다 건물 순서(차선)를 정한다.
탐욕 구성: 가치 ÷ 도착 턴이 가장 큰 (깃발, 건물) 쌍을 하나씩 붙인다.
"""
import time

import params as P
from mapinfo import INF


class OpeningPlan:
    def __init__(self, mp, t_start=None):
        self.mp = mp
        t0 = t_start if t_start is not None else time.perf_counter()
        n_cont = sum(1 for b in mp.blds if b.side == 'cont')
        self.nflags = P.FLAG_OPEN_CONTESTED if n_cont >= P.FLAG_OPEN_CONTESTED_MIN else P.FLAG_OPEN
        starts = []
        for t, n in P.OPEN_FLAG_SCHEDULE:
            starts += [t] * n
        while len(starts) < self.nflags:
            starts.append(P.OPEN_FLAG_SCHEDULE[-1][0])
        self.start_turns = starts[:self.nflags]
        self.lanes = [[] for _ in self.start_turns]
        self.sites = [mp.base_us] * len(self.start_turns)
        self.escorts = []
        self.cap_turn = {}
        self.hold = set()
        try:
            self._greedy(t0)
        except Exception:
            self.lanes = [[] for _ in self.start_turns]
            self.escorts = []
        self.L0 = self._initial_levels()

    def _value(self, b, planned):
        V = P.OPEN_VALUE
        mp = self.mp
        k = b.kind
        if k == 'ENG':
            has = any(mp.blds[i].kind == 'ENG' for i in planned)
            return V['ENG2_BASE'] + b.est if has else V['ENG1']
        if k == 'HALL':
            return V['HALL']
        if k == 'DEPOT':
            return V['DEPOT']
        if k == 'STATION':
            n = sum(1 for i in planned if mp.blds[i].kind == 'STATION')
            return V['STATION2'] if n == 1 else V['STATION_SRC']
        if k == 'HOSPITAL':
            fwd = mp.dist[b.c][mp.base_e] <= mp.D - P.HOSP_FWD_GAIN
            return V['HOSP_FWD'] if fwd else V['HOSP']
        if k == 'PLAZA':
            return P.SCORE_PLAZA + V['PLAZA_BONUS']
        if k == 'LIBRARY':
            return V['LIBRARY']
        if k == 'WATCH':
            return V['WATCH_BASE'] + V['WATCH_INFO']
        return b.est * V['OTHER_MULT']

    def _greedy(self, t0):
        mp = self.mp
        dist = mp.dist
        H = P.VALUE_HORIZON
        cands = [b for b in mp.blds if b.side in ('us', 'cont')]
        nl = len(self.lanes)
        lane_t = [None] * nl
        lane_pos = [None] * nl
        planned = []
        hosp_t = {}           # 계획상 병원 점령 턴
        while True:
            if time.perf_counter() - t0 > P.OPEN_TIME_S:
                break
            best = None
            for li in range(nl):
                for b in cands:
                    if b.i in self.cap_turn:
                        continue
                    if lane_t[li] is None:
                        s = self.start_turns[li]
                        t = INF
                        site = mp.base_us
                        for p in [mp.base_us] + [mp.blds[h].c for h, ht in hosp_t.items()
                                                 if ht < s]:
                            tt = s + dist[p][b.c] - 1
                            if tt < t:
                                t, site = tt, p
                    else:
                        t = lane_t[li] + dist[lane_pos[li]][b.c]
                        site = None
                    if t >= INF or t > P.OPEN_HORIZON_TURN:
                        continue
                    tE = dist[mp.base_e][b.c]
                    esc = False
                    if b.side == 'cont':
                        if t > tE:
                            continue
                        if t == tE:
                            ok = False
                            for p in [mp.base_us] + [mp.blds[h].c for h in hosp_t]:
                                s_w = tE - dist[p][b.c] + 1
                                if s_w >= P.OPEN_ESCORT_FIRST_W_TURN:
                                    ok = True
                                    break
                            if not ok:
                                continue
                            esc = True
                    v = self._value(b, planned) * max(0, H - t) / H
                    if v <= 0:
                        continue
                    sc = v / max(1, t)
                    if best is None or sc > best[0] + 1e-12:
                        best = (sc, li, b, t, site, esc)
            if best is None:
                break
            _, li, b, t, site, esc = best
            if lane_t[li] is None:
                self.sites[li] = site
            self.lanes[li].append(b.i)
            lane_t[li] = t
            lane_pos[li] = b.c
            self.cap_turn[b.i] = t
            planned.append(b.i)
            self.hold.add(b.i)
            if b.kind == 'HOSPITAL':
                hosp_t[b.i] = t
            if esc:
                self.escorts.append((b.i, 1, t))

    def _initial_levels(self):
        mp = self.mp
        L = [P.L_BASE] * mp.nsec
        for bi in sorted(self.hold):
            b = mp.blds[bi]
            if b.phi >= INF:
                continue
            k = b.sec
            L[k] = max(L[k], b.phi)
        L = [min(v, P.L_OPEN_MAX) for v in L]
        changed = True
        while changed:
            changed = False
            for k in range(mp.nsec):
                v = L[k]
                if k > 0:
                    v = max(v, L[k - 1] - P.L_STEP)
                if k + 1 < mp.nsec:
                    v = max(v, L[k + 1] - P.L_STEP)
                if v != L[k]:
                    L[k] = v
                    changed = True
        return L
