"""명령 생성·검증 (지침서 20장, 출력 순서 12.8).

SPAWN(본진 → 병원 (y, x)) → TELE → MOVE((y, x), F → W → S, U → R → D → L) → PRIORITY.
통과하지 못한 줄은 내보내지 않고 센다.
"""
import params as P
from mapinfo import cx, cy, DIR_RANK

KIND_ORDER = {'F': 0, 'W': 1, 'S': 2}
KI = {'F': 0, 'W': 1, 'S': 2}


class Output:
    def __init__(self, ctx):
        self.ctx = ctx
        self.rejected = 0
        self.lines = []
        self.spawned = {'F': {}, 'W': {}, 'S': {}}
        self.spent = 0

    def build(self, spawns, tele, moves, caps):
        """spawns: [(kind, n, site)], tele: (kind, s, d, n) | None,
        moves: {(cell, kind, dir): n}, caps: 이번 턴 점령 대상 건물 목록."""
        ctx = self.ctx
        mp, td, eco = ctx.mp, ctx.td, ctx.eco
        R = eco.R[0]
        hosp = set(c for c in eco.sites[0] if c != mp.base_us)
        out = []
        # SPAWN
        agg = {}
        for kind, n, site in spawns:
            if n <= 0:
                continue
            agg[(site, kind)] = agg.get((site, kind), 0) + n
        order = sorted(agg, key=lambda k: (0 if k[0] == mp.base_us else 1, k[0],
                                           KIND_ORDER.get(k[1], 9), str(k[1])))
        for site, kind in order:
            n = agg[(site, kind)]
            if kind not in KI or n < 1:
                self.rejected += 1
                continue
            cost = eco.cost[0] if kind == 'W' else P.COST[kind]
            n = min(n, (R - self.spent) // cost)
            if n < 1:
                self.rejected += 1
                continue
            if site == mp.base_us:
                out.append(f"SPAWN {kind} {n}")
            elif site in hosp:
                out.append(f"SPAWN {kind} {n} {cx(site)} {cy(site)}")
            else:
                self.rejected += 1
                continue
            self.spent += n * cost
            self.spawned[kind][site] = self.spawned[kind].get(site, 0) + n
        movable = {}

        def avail(kind, c):
            key = (kind, c)
            if key not in movable:
                movable[key] = td.U[0][KI[kind]][c] + self.spawned[kind].get(c, 0)
            return movable[key]

        # TELE
        if tele is not None:
            kind, s, d, n = tele
            st = set(eco.stations[0])
            n = min(n, P.TELE_MAX, avail(kind, s))
            if len(st) >= P.TELE_MIN_STATIONS and s in st and d in st and s != d and n >= 1:
                out.append(f"TELE {cx(s)} {cy(s)} {kind} {n} {cx(d)} {cy(d)}")
                movable[(kind, s)] = avail(kind, s) - n
            else:
                self.rejected += 1
        # MOVE
        keys = sorted(moves, key=lambda k: (k[0], KIND_ORDER.get(k[1], 9), DIR_RANK.get(k[2], 9),
                                            str(k[1]), str(k[2])))
        for c, kind, d in keys:
            n = moves[(c, kind, d)]
            if n < 1:
                continue
            if kind not in KI or d not in DIR_RANK:
                self.rejected += 1
                continue
            dst = mp.step(c, d)
            if dst is None:
                self.rejected += 1
                continue
            a = avail(kind, c)
            n = min(n, a)
            if n < 1:
                self.rejected += 1
                continue
            out.append(f"MOVE {cx(c)} {cy(c)} {kind} {n} {d}")
            movable[(kind, c)] = a - n
        # PRIORITY (점령 2건 이상)
        if len(caps) >= 2:
            pr = self._priority(caps)
            toks = []
            for b in pr:
                toks += [str(b.x), str(b.y)]
            if toks and len(toks) % 2 == 0:
                out.append("PRIORITY " + " ".join(toks))
        self.lines = out
        return out

    def _priority(self, caps):
        """공학관 → 학생회관 → TELE를 여는 역 → 미수령 보급소 → 병원 → 광장 → 점수순 (14.3)."""
        ctx = self.ctx
        eco, mem, td = ctx.eco, ctx.mem, ctx.td
        n_st = len(eco.stations[0])

        def rank(b):
            k = b.kind
            if k == 'ENG':
                r = 0
            elif k == 'HALL':
                r = 1
            elif k == 'STATION' and n_st == 1:
                r = 2
            elif td.owner[b.i] == -1 and mem.prev_owner[b.i] == 1:
                r = 3
            elif k == 'DEPOT' and not mem.depot_claimed[0][b.i]:
                r = 4
            elif k == 'HOSPITAL':
                r = 5
            elif k == 'PLAZA':
                r = 6
            else:
                r = 7
            return (r, -mem.score_of(b.i), b.y, b.x)
        return sorted(caps, key=rank)
