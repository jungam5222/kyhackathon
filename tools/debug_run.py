"""디버그용 대전: 우리 봇은 같은 프로세스에서, 상대는 하위 프로세스로 돌린다.

내부 상태(슬롯·배정·깃발)를 턴마다 들여다볼 때 쓴다. 승률 측정은 campus-sim을 쓴다.

    python3 tools/debug_run.py --sim ~/campus_sim --opp bots/pool/rush --seed 3 --team Y \
        --dump 30 --dump 40
"""
import argparse
import io
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BOT_DIR = os.path.join(os.path.dirname(HERE), 'bot')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sim', default=os.path.expanduser('~/campus_sim'))
    ap.add_argument('--opp', default='bots/pool/rush')
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--variant', default='mixed')
    ap.add_argument('--team', default='Y')
    ap.add_argument('--dump', type=int, action='append', default=[])
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--econ-watch', action='store_true',
                    help='우리 공학관·학생회관을 잃는 순간 직전 4턴의 수비 상태를 출력 (Y 진영 전용)')
    a = ap.parse_args()
    sys.path.insert(0, a.sim)
    sys.path.insert(0, BOT_DIR)
    from campus.engine import Game
    from campus.mapgen import generate_map
    import bot as botmod

    gmap = generate_map(a.seed, a.variant)
    g = Game(gmap)
    us, them = a.team, ('K' if a.team == 'Y' else 'Y')
    opp_dir = os.path.join(a.sim, a.opp)
    env = dict(os.environ)
    env['PYTHONPATH'] = opp_dir + os.pathsep + os.path.join(a.sim, 'bots', 'starter')
    proc = subprocess.Popen([sys.executable, 'main.py'], cwd=opp_dir, env=env,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, bufsize=1)

    def opp_cmds(text):
        proc.stdin.write(text)
        proc.stdin.flush()
        out = []
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            s = line.strip()
            if s == 'END':
                break
            if s:
                out.append(s)
        return out

    init_us = [l for l in g.init_text(us).splitlines() if l and l != 'END']
    old_err = sys.stderr
    if a.quiet:
        sys.stderr = io.StringIO()
    b = botmod.Bot(init_us)
    proc.stdin.write(g.init_text(them))
    proc.stdin.flush()
    maxms = 0.0
    hist = []
    while not g.finished:
        t_us = [l for l in g.turn_text(us).splitlines() if l and l != 'END']
        t0 = time.perf_counter()
        cmds = b.on_turn(t_us, t0)
        maxms = max(maxms, (time.perf_counter() - t0) * 1000)
        oc = opp_cmds(g.turn_text(them))
        if g.turn + 1 in a.dump:
            dump(b, g, us)
        before = list(g.owner)
        rep = g.step({us: cmds, them: oc})
        if a.econ_watch:
            hist.append(econ_snapshot(b, g, us))
            hist = hist[-4:]
            for bd in g.map.buildings:
                if bd.type in ('ENG', 'HALL') and before[bd.id] == us and g.owner[bd.id] != us:
                    econ_report(g, bd, hist, us)
        ign = rep.ignored.get(us) if hasattr(rep, 'ignored') else None
        if ign:
            old_err.write(f"IGNORED t{g.turn}: {ign}\n")
    sys.stderr = old_err
    print(f"result {g.result['winner']} {g.result['reason']} turn {g.result['turn']} "
          f"score {g.result['score']} maxms {maxms:.1f}")
    proc.kill()


def econ_snapshot(b, g, us):
    """이번 턴 배정 직후의 경제 건물 주변 상태 (봇 내부 좌표 = Y 진영이면 엔진 좌표)."""
    from mapinfo import cell
    asg = b.last_asg
    mp = b.mp
    snap = {'turn': b.turn, 'b': {}}
    for bd in g.map.buildings:
        if bd.type not in ('ENG', 'HALL'):
            continue
        c = cell(bd.x, bd.y)
        guards = [(s.key, s.r, s.need, (asg.area_count(s) if s.r else asg.pt[s.cell]), s.failed)
                  for s in asg.slots if s.key[0] in ('guard', 'hunt', 'escort') and s.cell == c]
        td = b.mem.prev
        near = lambda arr, r: sum(arr[v] for v in mp.ball(c, r))
        ef = [(f.id, mp.dist[f.c][c]) for f in b.mem.eflags if mp.dist[f.c][c] <= 5]
        snap['b'][bd.id] = dict(guards=guards, we=[near(td.W[1], r) for r in (0, 1, 2, 3)],
                                wu=[near(td.W[0], r) for r in (0, 1, 2, 3)],
                                end=[sum(asg.endc[v] for v in mp.ball(c, r)) for r in (0, 1, 2, 3)],
                                ef=ef, own=td.owner[mp.bld_at[c].i])
    return snap


def econ_report(g, bd, hist, us):
    print(f"### LOST {bd.type} ({bd.x},{bd.y}) at turn {g.turn} -> owner {g.owner[bd.id]}")
    for sn in hist:
        d = sn['b'].get(bd.id)
        if d is None:
            continue
        print(f"  t{sn['turn']} own={d['own']} 상대W(반경0~3)={d['we']} 우리W={d['wu']} "
              f"이동후우리={d['end']} 상대깃발(id,거리)={d['ef']}")
        for gk in d['guards']:
            print(f"      {gk}")


def dump(b, g, us):
    """마지막 배정 결과를 사람이 읽을 수 있게 찍는다."""
    from slots import TIER_NAMES
    from mapinfo import cx, cy
    asg = b.last_asg
    print(f"=== DUMP turn {b.turn} mode {b.modes.mode} L {b.terr.L} |F|={len(b.terr.F)}")
    print("F:", " ".join(f"({cx(c)},{cy(c)})" for c in b.terr.F))
    print("occupied:", " ".join(f"({cx(c)},{cy(c)})" for c in sorted(b.terr.occupied)))
    for s in sorted(asg.slots, key=lambda s: (s.tier, repr(s.key))):
        got = asg.area_count(s) if s.r else asg.pt[s.cell]
        print(f"  {TIER_NAMES[s.tier]:4} {str(s.key):30} ({cx(s.cell)},{cy(s.cell)}) r{s.r} "
              f"need {s.need} got {got} dl {s.deadline if s.deadline < 999 else '-'}"
              f"{' FAIL' if s.failed else ''}{' A' if s.atomic else ''}")
    for f in b.flagm.flags:
        o = f.opts[f.opt] if f.opt < len(f.opts) else None
        print(f"  flag {f.id} at ({cx(f.c)},{cy(f.c)}) task {f.task} bi {f.bi} goal "
              f"{(cx(f.goal), cy(f.goal)) if f.goal is not None else None} opt {o} "
              f"lane {f.lane} li {f.li}")
    for sq in b.squadm.squads:
        print("  squad", sq, "wait", (cx(sq.wait), cy(sq.wait)))


if __name__ == '__main__':
    main()
