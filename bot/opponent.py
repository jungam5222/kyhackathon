"""상대 유형별 신호 (지침서 19장).

매 턴 신호를 계산해 파라미터만 바꾼다. 핵심 구조(라인·경주 수비·사냥)는 그대로 둔다.
"""
import params as P


class OppModel:
    def __init__(self, mp):
        self.mp = mp
        self.lurk_bids = set()       # 잠복 저격: 상대 깃발이 3칸 안에서 정지한 우리 건물
        self.flag_rush = False       # 깃발 몰빵 (10턴 판정, 이후 유지)
        self.hunter = False          # 사냥꾼: 우리 깃발이 요격으로 2명 이상 죽음
        self.deathball = False       # 상위 1더미 ≥ 상대 전투병 40%
        self.blob = None
        self.siege = False           # 견제: 상대 더미 15~30명이 우리 생산지 옆에서 정지
        self.tele_conveyor = False   # 상대 역 인원이 이웃으로 설명되지 않게 늘어남 (이후 유지)
        self.hoard = False           # 상대 자원 ≥ 30
        self.march = {}              # 경계 칸 -> 행군 더미 접근 점수 (육로 컨베이어)
        self.prev_We = None
        self.prev_blob = None
        self.blob_still = 0

    def update(self, ctx, flagm):
        mp, td, mem, eco = ctx.mp, ctx.td, ctx.mem, ctx.eco
        dist = mp.dist
        We = td.W[1]
        # 잠복 저격
        self.lurk_bids = set()
        for f in mem.eflags:
            if not f.lurker:
                continue
            for b in mp.blds:
                if td.owner[b.i] == 0 and b.kind in ('ENG', 'HALL', 'HOSPITAL') and \
                        dist[f.c][b.c] <= P.LURK_RADIUS:
                    self.lurk_bids.add(b.i)
        # 깃발 몰빵
        if ctx.turn == P.FLAG_RUSH_TURN:
            self.flag_rush = (sum(td.F[1]) >= P.FLAG_RUSH_FLAGS and
                              sum(We) <= sum(td.W[0]))
        # 사냥꾼
        self.hunter = flagm.hunted
        # 데스볼과 견제
        tot = sum(We)
        top = max(mp.cells, key=lambda c: (We[c], -c)) if tot else None
        self.deathball = (top is not None and tot >= P.DEATHBALL_MIN_W and
                          We[top] >= P.DEATHBALL_SHARE * tot)
        self.blob = top if self.deathball else None
        if top is not None and top == self.prev_blob:
            self.blob_still += 1
        else:
            self.blob_still = 0
        self.prev_blob = top
        self.siege = (top is not None and P.SIEGE_MIN_W <= We[top] <= P.SIEGE_MAX_W and
                      self.blob_still >= P.SIEGE_STILL and
                      any(dist[s][top] <= 1 for s in eco.sites[0]))
        # TELE 컨베이어
        if self.prev_We is not None and eco.tele_ok[1]:
            for s in eco.stations[1]:
                came = sum(self.prev_We[v] for v in mp.closed[s])
                if We[s] > came + (ctx.threat.spawn_e if s in ctx.threat.e_site_near else 0):
                    self.tele_conveyor = True
        # 육로 컨베이어: 5~8명 묶음이 경계 칸 2칸 안으로 다가온 횟수 (감쇠 누적)
        packs = [c for c in mp.cells if P.MARCH_PACK_MIN <= We[c] <= P.MARCH_PACK_MAX]
        march = {}
        for c in ctx.terr.F:
            v = self.march.get(c, 0.0) * P.MARCH_DECAY
            if any(dist[p][c] <= 2 for p in packs):
                v += 1.0
            march[c] = v
        self.march = march
        self.hoard = td.R[1] >= P.HOARD_R
        self.prev_We = list(We)

    def press_cap(self, c):
        """육로 컨베이어 행군로가 닿는 경계 칸은 압력 상한을 올린다."""
        if self.march.get(c, 0.0) >= P.MARCH_TRIGGER:
            return P.PRESS_MAX_MARCH
        return P.PRESS_MAX

    def tag(self):
        t = ''
        for on, ch in ((self.lurk_bids, 'L'), (self.flag_rush, 'R'), (self.hunter, 'H'),
                       (self.deathball, 'D'), (self.siege, 'S'), (self.tele_conveyor, 'T'),
                       (any(v >= P.MARCH_TRIGGER for v in self.march.values()), 'M'),
                       (self.hoard, '$')):
            if on:
                t += ch
        return t or '-'
