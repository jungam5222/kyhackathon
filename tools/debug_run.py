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
    while not g.finished:
        t_us = [l for l in g.turn_text(us).splitlines() if l and l != 'END']
        t0 = time.perf_counter()
        cmds = b.on_turn(t_us, t0)
        maxms = max(maxms, (time.perf_counter() - t0) * 1000)
        oc = opp_cmds(g.turn_text(them))
        if g.turn + 1 in a.dump:
            dump(b, g, us)
        rep = g.step({us: cmds, them: oc})
        ign = rep.ignored.get(us) if hasattr(rep, 'ignored') else None
        if ign:
            old_err.write(f"IGNORED t{g.turn}: {ign}\n")
    sys.stderr = old_err
    print(f"result {g.result['winner']} {g.result['reason']} turn {g.result['turn']} "
          f"score {g.result['score']} maxms {maxms:.1f}")
    proc.kill()


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
