"""라인 — 영역 T, 경계선 F, 지원 칸 S (지침서 10장)."""
from collections import deque

import params as P
from mapinfo import NC, INF


class Territory:
    def __init__(self, mp):
        self.mp = mp
        ns = mp.nsec
        self.L = [P.L_BASE] * ns
        self.L_min = [P.L_BASE] * ns
        self.excl_last = {}          # 칸 -> 제외 조건이 마지막으로 참이던 턴
        self.excl = set()
        self.line_done = False
        self.adv_streak = [0] * ns
        self.ret_streak = [0] * ns
        self.last_retreat = [-99] * ns
        self.occ_streak = {}         # 경계 칸 -> 상대 전투병 점거 연속 턴
        self.empty_streak = {}       # 점거됐던 칸 -> 비어 있던 연속 턴
        self.occupied = set()        # 임시 2선을 쓰는 경계 칸
        self.under = [0] * ns
        self.T = [False] * NC
        self.F = []
        self.Fset = set()
        self.S = []
        self.Sset = set()
        self.coverage = 0.0
        self.changed = False
        self.adv_log = ''

    # ------------------------------------------------------------------
    def set_initial(self, L0):
        self.L = list(L0)

    def region(self, L, excl, seeds, essential):
        mp = self.mp
        phi, sec = mp.phi, mp.sector
        inl = [False] * NC
        for c in mp.cells:
            inl[c] = phi[c] <= L[sec[c]] and c not in excl
        T = [False] * NC
        q = deque()
        for s in seeds:
            if not T[s]:
                T[s] = True
                q.append(s)
        nbrs = mp.nbrs
        while q:
            u = q.popleft()
            for v in nbrs[u]:
                if inl[v] and not T[v]:
                    T[v] = True
                    q.append(v)
        for e in essential:
            if inl[e] and not T[e]:
                T[e] = True
                q.append(e)
                while q:
                    u = q.popleft()
                    for v in nbrs[u]:
                        if inl[v] and not T[v]:
                            T[v] = True
                            q.append(v)
        F = [c for c in mp.cells if T[c] and any(not T[v] for v in nbrs[c])]
        Fs = set(F)
        S = [c for c in mp.cells if T[c] and c not in Fs and any(v in Fs for v in nbrs[c])]
        return T, F, S

    # ------------------------------------------------------------------
    def update(self, ctx):
        mp = self.mp
        turn = ctx.turn
        eco = ctx.eco
        td = ctx.td
        fin = ctx.finale
        # 제외 구역 (래치)
        if fin:
            self.excl = set()
            self.excl_last = {}
        else:
            srcs = list(eco.sites[1])
            if eco.tele_ok[1]:
                srcs += eco.stations[1]
            for s in srcs:
                for c in mp.closed[s]:
                    self.excl_last[c] = turn
            self.excl = {c for c, t in self.excl_last.items() if turn - t <= P.EXCL_LATCH}
            for c in [c for c, t in self.excl_last.items() if turn - t > P.EXCL_LATCH]:
                del self.excl_last[c]
        seeds = list(eco.sites[0])
        ess = ctx.essential
        self.L_min = [P.L_BASE] * mp.nsec
        for b in ess:
            k = b.sec
            if b.phi < INF and b.phi > self.L_min[k]:
                self.L_min[k] = b.phi
        ess_cells = [b.c for b in ess]
        T, F, S = self.region(self.L, self.excl, seeds, ess_cells)
        self._set(T, F, S)
        Wu = td.W[0]
        # 점거된 경계 칸은 임시 2선이 맡으므로 배치율 분모에서 뺀다 (11.5)
        live = [c for c in F if c not in self.occupied]
        manned = sum(1 for c in live if Wu[c] > 0)
        self.coverage = manned / len(live) if live else 1.0
        if not self.line_done and self.coverage >= P.LINE_DONE:
            self.line_done = True
        self._occupation(td)
        self.adv_log = ''
        self.changed = False
        if self.line_done or fin:
            if not fin:
                self._retreat(ctx, seeds, ess, ess_cells)
            self._advance(ctx, seeds, ess, ess_cells)
        if self.changed:
            T, F, S = self.region(self.L, self.excl, seeds, ess_cells)
            self._set(T, F, S)
            self._occupation(td, refresh_only=True)

    def _set(self, T, F, S):
        self.T, self.F, self.S = T, F, S
        self.Fset = set(F)
        self.Sset = set(S)

    def _occupation(self, td, refresh_only=False):
        We = td.W[1]
        Wu = td.W[0]
        mp = self.mp
        if not refresh_only:
            under = [False] * mp.nsec
            for c in self.F:
                if We[c] > 0:
                    self.occ_streak[c] = self.occ_streak.get(c, 0) + 1
                    self.empty_streak[c] = 0
                else:
                    self.occ_streak[c] = 0
                    if c in self.occupied:
                        self.empty_streak[c] = self.empty_streak.get(c, 0) + 1
                if Wu[c] == 0:
                    under[mp.sector[c]] = True
            for k in range(mp.nsec):
                self.under[k] = self.under[k] + 1 if under[k] else 0
        occ = set()
        for c in self.F:
            if We[c] > 0:
                occ.add(c)
            elif c in self.occupied and self.empty_streak.get(c, 0) < P.SCREEN2_RELEASE:
                occ.add(c)
        self.occupied = occ

    # ------------------------------------------------------------------ 전진 (10.5)
    def _advance(self, ctx, seeds, ess, ess_cells):
        mp = self.mp
        ns = mp.nsec
        th = ctx.threat
        E1, A1 = th.E1, th.A1
        fin = ctx.finale
        turn = ctx.turn
        mode = ctx.mode
        w_total = ctx.w_total
        cur_T = self.T
        n_F = len(self.F)
        cands = []
        for k in range(ns):
            if not fin and turn - self.last_retreat[k] <= P.ADV_COOLDOWN:
                self.adv_streak[k] = 0
                continue
            L2 = list(self.L)
            L2[k] += P.L_STEP
            group = {k}
            changed = True
            while changed:
                changed = False
                for j in sorted(group):
                    for nb in (j - 1, j + 1):
                        if 0 <= nb < ns and L2[j] - L2[nb] > P.L_STEP:
                            L2[nb] = L2[j] - P.L_STEP
                            group.add(nb)
                            changed = True
            if max(L2) > mp.D:
                self.adv_streak[k] = 0
                continue
            T2, F2, S2 = self.region(L2, self.excl, seeds, ess_cells)
            newF = [c for c in F2 if c not in self.Fset]
            new_b = [b for b in mp.blds if T2[b.c] and not cur_T[b.c]]
            ok = True
            # 1. 모드
            if not fin and mode == 'FIX':
                ok = any(b.kind in ('ENG', 'HALL') or
                         (b.kind == 'DEPOT' and not ctx.mem.depot_claimed[0][b.i])
                         for b in new_b)
            # 2. 상대가 얇다
            if ok:
                for c in newF:
                    if E1[c] > P.ADV_E1_MAX and A1[c] < E1[c] + 1:
                        ok = False
                        break
            # 3. 공급
            if ok and w_total < len(F2):
                ok = False
            # 4. 상대 생산지와 거리
            if ok and not fin:
                for c in newF:
                    if any(mp.dist[s][c] <= P.ADV_SITE_GAP for s in ctx.eco.sites[1]):
                        ok = False
                        break
            # 5. 가치 (진지전)
            value = sum(ctx.bld_value(b) for b in new_b) + max(0, n_F - len(F2))
            if ok and not fin and mode == 'POS':
                below_min = any(self.L[j] < self.L_min[j] for j in group)
                push = any(T2[f.c] and not cur_T[f.c] for f in ctx.mem.eflags)
                if not (below_min or new_b or len(F2) < n_F or push):
                    ok = False
            if ok:
                self.adv_streak[k] += 1
            else:
                self.adv_streak[k] = 0
            need = 1 if fin else P.ADV_HYST
            if ok and self.adv_streak[k] >= need:
                cands.append((-value, k, L2, group))
        if not cands:
            return
        cands.sort(key=lambda t: (t[0], t[1]))
        limit = ns if fin else P.ADV_PER_TURN
        done = set()
        applied = 0
        for _, k, L2, group in cands:
            if applied >= limit:
                break
            if group & done:
                continue
            for j in group:
                self.L[j] = max(self.L[j], L2[j])
                self.adv_streak[j] = 0
            done |= group
            applied += 1
            self.changed = True
            self.adv_log += f'+{k}'

    # ------------------------------------------------------------------ 후퇴 (10.6)
    def _retreat(self, ctx, seeds, ess, ess_cells):
        mp = self.mp
        for k in range(mp.nsec):
            occ = any(self.occ_streak.get(c, 0) >= P.RET_OCCUPY
                      for c in self.F if mp.sector[c] == k)
            und = self.under[k] >= P.RET_UNDERMAN
            ok = (occ or und) and self.L[k] - P.L_STEP >= P.L_FLOOR
            if ok:
                L2 = list(self.L)
                L2[k] -= P.L_STEP
                T2, _, _ = self.region(L2, self.excl, seeds, ess_cells)
                if any(not T2[c] for c in ess_cells if self.T[c]):
                    ok = False
            self.ret_streak[k] = self.ret_streak[k] + 1 if ok else 0
            if ok and self.ret_streak[k] >= P.RET_HYST:
                self.L[k] -= P.L_STEP
                self.ret_streak[k] = 0
                self.under[k] = 0
                self.last_retreat[k] = ctx.turn
                self.changed = True
                self.adv_log += f'-{k}'
