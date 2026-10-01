"""오프닝 차선 계획기 (지침서 16장).

깃발 출발 일정(1턴 2명, 3턴 2명, 4턴 1명)에 맞춰 깃발마다 건물 순서(차선)를 정한다.

1. 탐욕 구성: 가치 ÷ 도착 턴이 가장 큰 (깃발, 건물) 쌍을 하나씩 붙인다 (16.4-5).
2. 개선: 미계획 건물 넣기, 차선 간 건물 옮기기, 빼기, 차선 안 순서 바꾸기로
   시간 할인된 가치 합(16.3)을 늘린다. 시간 제한 P-OPEN_TIME_S.
3. 실패하거나 계획이 비면 규칙 차선 A~E로 대체한다 (16.4-7).

모든 계획은 같은 평가 함수(_evaluate)와 제약을 거친다:
- 쟁탈 건물: 우리 도착 < t_E면 안전, = t_E면 호위 마감, t_E < t ≤ t_E + P-OPEN_LATE_SLACK면
  '늦은 쟁탈'(호위 마감 + 가치 × P-OPEN_LATE_MULT), 그보다 늦으면 불가.
  (지침서 16.5 회귀 기대값이 t_E보다 1~2턴 늦은 광장·학생회관을 포함하므로 둔 완화)
- 같은 턴 점령 건수 ≤ P-OPEN_CAP_PER_TURN (점령 자금, 16.4-4)
- 도착 턴 ≤ P-OPEN_HORIZON_TURN
"""
import time

import params as P
from mapinfo import INF


class OpeningPlan:
    def __init__(self, mp, t_start=None):
        self.mp = mp
        t0 = t_start if t_start is not None else time.perf_counter()
        self.t0 = t0
        n_cont = sum(1 for b in mp.blds if b.side == 'cont')
        self.nflags = P.FLAG_OPEN_CONTESTED if n_cont >= P.FLAG_OPEN_CONTESTED_MIN else P.FLAG_OPEN
        starts = []
        for t, n in P.OPEN_FLAG_SCHEDULE:
            starts += [t] * n
        while len(starts) < self.nflags:
            starts.append(P.OPEN_FLAG_SCHEDULE[-1][0])
        self.start_turns = starts[:self.nflags]
        nl = len(self.start_turns)
        self.order = sorted(range(nl), key=lambda li: (self.start_turns[li], li))
        self.tE = {b.i: mp.dist[mp.base_e][b.c] for b in mp.blds}
        self.cands = [b.i for b in mp.blds if b.side in ('us', 'cont')
                      and mp.dist[mp.base_us][b.c] < INF]
        self.source = 'greedy'
        self.evals = 0
        lanes = None
        try:
            lanes = self._greedy()
            lanes = self._improve(lanes)
        except Exception:
            lanes = None
        if not lanes or not any(lanes) or self._evaluate(lanes) is None:
            try:
                lanes = self._repair(self._rule_lanes())
                self.source = 'rule'
            except Exception:
                lanes = [[] for _ in range(nl)]
                self.source = 'empty'
        self._apply(lanes)
        self.L0 = self._initial_levels()

    # ------------------------------------------------------------------ 가치 (16.3)
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

    def _escort_ok(self, b, t, hosp_t):
        """t턴까지 전투병 1명이 b에 닿을 수 있는가.

        생산지는 본진(전투병은 P-OPEN_ESCORT_FIRST_W_TURN부터)과, 계획상 먼저 먹는 병원
        (점령 다음 턴부터 생산)이다."""
        mp = self.mp
        if t - mp.dist[mp.base_us][b.c] + 1 >= P.OPEN_ESCORT_FIRST_W_TURN:
            return True
        for h, th in hosp_t.items():
            first = max(P.OPEN_ESCORT_FIRST_W_TURN, th + 1)
            if t - mp.dist[mp.blds[h].c][b.c] + 1 >= first:
                return True
        return False

    # ------------------------------------------------------------------ 평가
    def _evaluate(self, lanes):
        """(점수, 점령 턴, 호위 목록, 차선별 생산지). 제약을 어기면 None."""
        self.evals += 1
        mp = self.mp
        dist = mp.dist
        blds = mp.blds
        arr = []
        sites = [mp.base_us] * len(lanes)
        hosp_t = {}
        for li in self.order:
            lane = lanes[li]
            if not lane:
                continue
            s = self.start_turns[li]
            b0 = blds[lane[0]]
            best_t, site = INF, mp.base_us
            for p in [mp.base_us] + [blds[h].c for h, ht in hosp_t.items() if ht < s]:
                tt = s + dist[p][b0.c] - 1
                if tt < best_t:
                    best_t, site = tt, p
            sites[li] = site
            t = best_t
            prev = b0.c
            for k, bi in enumerate(lane):
                b = blds[bi]
                if k > 0:
                    t = t + dist[prev][b.c]
                if t > P.OPEN_HORIZON_TURN:
                    return None
                arr.append((t, bi))
                if b.kind == 'HOSPITAL':
                    hosp_t[bi] = t
                prev = b.c
        arr.sort()
        H = P.VALUE_HORIZON
        planned = []
        per_turn = {}
        cap = {}
        escorts = []
        score = 0.0
        for t, bi in arr:
            b = blds[bi]
            per_turn[t] = per_turn.get(t, 0) + 1
            if per_turn[t] > P.OPEN_CAP_PER_TURN:
                return None
            mult = 1.0
            if b.side == 'cont':
                tE = self.tE[bi]
                if t >= tE:
                    if t > tE + P.OPEN_LATE_SLACK or not self._escort_ok(b, t, hosp_t):
                        return None
                    escorts.append((bi, 1, t))
                    if t > tE:
                        mult = P.OPEN_LATE_MULT
            score += self._value(b, planned) * mult * max(0, H - t) / H
            planned.append(bi)
            cap[bi] = t
        return score, cap, escorts, sites

    def _score(self, lanes):
        ev = self._evaluate(lanes)
        return -1.0 if ev is None else ev[0]

    def _time_left(self):
        return time.perf_counter() - self.t0 < P.OPEN_TIME_S

    # ------------------------------------------------------------------ 1. 탐욕 구성
    def _greedy(self):
        lanes = [[] for _ in self.start_turns]
        base = self._score(lanes)
        used = set()
        while self._time_left():
            best = None
            for li in range(len(lanes)):
                for bi in self.cands:
                    if bi in used:
                        continue
                    lanes[li].append(bi)
                    ev = self._evaluate(lanes)
                    lanes[li].pop()
                    if ev is None:
                        continue
                    gain = ev[0] - base
                    if gain <= 0:
                        continue
                    t = ev[1][bi]
                    sc = gain / max(1, t)
                    if best is None or sc > best[0] + 1e-12:
                        best = (sc, li, bi, ev[0])
            if best is None:
                break
            _, li, bi, sc = best
            lanes[li].append(bi)
            used.add(bi)
            base = sc
        return lanes

    # ------------------------------------------------------------------ 2. 개선
    def _improve(self, lanes):
        cur = self._score(lanes)
        nl = len(lanes)
        while self._time_left():
            best = None
            planned = {bi for lane in lanes for bi in lane}

            def consider(new):
                nonlocal best
                sc = self._score(new)
                if sc > cur + 1e-9 and (best is None or sc > best[0] + 1e-12):
                    best = (sc, new)

            # 미계획 건물 넣기
            for bi in self.cands:
                if bi in planned:
                    continue
                for li in range(nl):
                    for pos in range(len(lanes[li]) + 1):
                        new = [list(l) for l in lanes]
                        new[li].insert(pos, bi)
                        consider(new)
            # 빼기와 옮기기
            for li in range(nl):
                for pos in range(len(lanes[li])):
                    bi = lanes[li][pos]
                    base = [list(l) for l in lanes]
                    del base[li][pos]
                    consider(base)
                    for lj in range(nl):
                        for q in range(len(base[lj]) + 1):
                            if lj == li and q == pos:
                                continue
                            new = [list(l) for l in base]
                            new[lj].insert(q, bi)
                            consider(new)
            # 차선 안 순서 바꾸기
            for li in range(nl):
                for pos in range(len(lanes[li]) - 1):
                    new = [list(l) for l in lanes]
                    new[li][pos], new[li][pos + 1] = new[li][pos + 1], new[li][pos]
                    consider(new)
            if best is None:
                break
            cur, lanes = best
        return lanes

    # ------------------------------------------------------------------ 3. 규칙 차선 (16.4-7)
    def _rule_lanes(self):
        mp = self.mp
        dist = mp.dist
        O = mp.base_us
        blds = mp.blds
        ours = [b for b in blds if b.side == 'us']
        cont = [b for b in blds if b.side == 'cont']
        used = set()
        lanes = [[] for _ in self.start_turns]

        def take(lst, frm, detour=None):
            best = None
            for b in lst:
                if b.i in used:
                    continue
                if detour is not None and frm is not None:
                    if dist[O][b.c] < dist[O][frm] - 0 and \
                            dist[frm][b.c] > abs(dist[O][b.c] - dist[O][frm]) + detour:
                        continue
                d = dist[frm if frm is not None else O][b.c]
                if best is None or d < best[0]:
                    best = (d, b)
            if best is None:
                return None
            used.add(best[1].i)
            return best[1]

        t1 = [li for li in self.order if self.start_turns[li] == 1]
        t3 = [li for li in self.order if self.start_turns[li] == 3]
        t4 = [li for li in self.order if self.start_turns[li] >= 4]
        # A: 공학관·학생회관 중 가까운 것 → 우회 3칸 이하인 우리 쪽 건물 잇기
        if t1:
            econ = [b for b in ours if b.kind in ('ENG', 'HALL')]
            b = take(econ, None) or take(ours, None)
            cur = b.c if b else None
            while b is not None and len(lanes[t1[0]]) < 4:
                lanes[t1[0]].append(b.i)
                b = take(ours, cur, detour=3)
                cur = b.c if b else cur
        # C: 가까운 보급소 → 가까운 중앙 역 → 광장(우회 2칸 이하)
        if len(t1) > 1:
            li = t1[1]
            d = take([b for b in ours + cont if b.kind == 'DEPOT'], None)
            cur = d.c if d else O
            if d:
                lanes[li].append(d.i)
            s = take([b for b in ours + cont if b.kind == 'STATION' and b.region == 'central'], cur)
            if s:
                lanes[li].append(s.i)
                cur = s.c
            pz = [b for b in cont if b.kind == 'PLAZA' and b.i not in used]
            if pz and dist[cur][pz[0].c] <= 2 + 1:
                used.add(pz[0].i)
                lanes[li].append(pz[0].i)
        # B: A에 안 들어간 경제 건물(쟁탈 학생회관 포함), 없으면 중앙 역·방송국
        if t3:
            econ = [b for b in ours + cont if b.kind in ('ENG', 'HALL')]
            b = take(econ, None) or take([b for b in ours + cont if b.region == 'central'], None)
            if b:
                lanes[t3[0]].append(b.i)
        # D: 중앙 두 번째 (역 또는 광장)
        if len(t3) > 1:
            b = take([b for b in ours + cont if b.kind in ('STATION', 'PLAZA')
                      and b.region in ('central', 'plaza')], None)
            if b:
                lanes[t3[1]].append(b.i)
        # E: 도서관·방송국 채우기
        for li in t4:
            b = take([b for b in ours if b.kind in ('LIBRARY', 'WATCH')], None) or take(ours, None)
            if b:
                lanes[li].append(b.i)
        return lanes

    def _repair(self, lanes):
        """제약을 어기는 계획은 차선 끝 건물부터 빼서 맞춘다."""
        lanes = [list(l) for l in lanes]
        while self._evaluate(lanes) is None:
            longest = max(range(len(lanes)), key=lambda i: (len(lanes[i]), i))
            if not lanes[longest]:
                break
            lanes[longest].pop()
        return lanes

    # ------------------------------------------------------------------ 결과
    def _apply(self, lanes):
        self.lanes = lanes
        ev = self._evaluate(lanes)
        if ev is None:
            self.lanes = [[] for _ in self.start_turns]
            ev = self._evaluate(self.lanes)
        self.score, self.cap_turn, self.escorts, self.sites = ev
        self.hold = set(self.cap_turn)
        st = [bi for bi in self.cap_turn if self.mp.blds[bi].kind == 'STATION']
        st.sort(key=lambda bi: self.cap_turn[bi])
        self.tele_turn = self.cap_turn[st[1]] + 1 if len(st) >= 2 else None

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
