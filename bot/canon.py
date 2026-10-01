"""정규 좌표계: 우리 본진이 항상 Y 쪽에 오도록 입력을 180° 돌리고 출력을 되돌린다.

맵은 (7,7) 기준 점대칭(E-30)이므로, K 진영이면 (x, y) → (14−x, 14−y), U↔D, L↔R로 바꾼다.
이렇게 하면 (y, x) 순 동률 처리가 진영과 무관해져 Y·K에서 정확히 거울상 결정을 낸다
(같은 봇끼리 미러전은 무승부여야 한다).
"""
N1 = 14
FLIP_DIR = {'U': 'D', 'D': 'U', 'L': 'R', 'R': 'L'}


def _fx(tok):
    return str(N1 - int(tok))


def team_of(lines):
    for s in lines:
        t = s.split()
        if len(t) >= 2 and t[0] == 'TEAM':
            return t[1]
    return 'Y'


def flip_init(lines):
    out = []
    rows = []
    map_pos = None
    i = 0
    n = len(lines)
    while i < n:
        s = lines[i]
        t = s.split()
        i += 1
        if not t:
            continue
        k = t[0]
        if k == 'MAP':
            if map_pos is None:
                map_pos = len(out)
                out.append(None)
            rows.extend(t[1:])
            while len(rows) < 15 and i < n:
                nt = lines[i].split()
                if nt and all(len(r) == 15 and set(r) <= set('.#BH') for r in nt):
                    rows.extend(nt)
                    i += 1
                else:
                    break
        elif k == 'BUILDINGS':
            out.append(s)
            cnt = int(t[1]) if len(t) > 1 else 17
            for _ in range(cnt):
                if i >= n:
                    break
                b = lines[i].split()
                if len(b) >= 4 and b[0].lstrip('-').isdigit():
                    out.append(f"{b[0]} {_fx(b[1])} {_fx(b[2])} {' '.join(b[3:])}")
                    i += 1
                else:
                    break
        elif k == 'BASE' and len(t) >= 4:
            out.append(f"BASE {t[1]} {_fx(t[2])} {_fx(t[3])}")
        else:
            out.append(s)
    if map_pos is not None:
        frows = [r[::-1] for r in reversed(rows[:15])]
        out[map_pos:map_pos + 1] = [f"MAP {r}" for r in frows]
    return out


def flip_turn(lines):
    out = []
    i = 0
    n = len(lines)
    while i < n:
        s = lines[i]
        t = s.split()
        i += 1
        if not t:
            continue
        k = t[0]
        if k == 'UNITS':
            out.append(s)
            cnt = int(t[1]) if len(t) > 1 else 0
            for _ in range(cnt):
                if i >= n:
                    break
                u = lines[i].split()
                if len(u) >= 5 and u[1] in ('F', 'W', 'S'):
                    out.append(f"{u[0]} {u[1]} {_fx(u[2])} {_fx(u[3])} {u[4]}")
                    i += 1
                else:
                    break
        elif k == 'BUILDINGS':
            out.append(s)
            cnt = int(t[1]) if len(t) > 1 else 17
            for _ in range(cnt):
                if i >= n:
                    break
                b = lines[i].split()
                if len(b) >= 7 and b[0].lstrip('-').isdigit():
                    out.append(f"{b[0]} {_fx(b[1])} {_fx(b[2])} {' '.join(b[3:])}")
                    i += 1
                else:
                    break
        else:
            out.append(s)
    return out


def flip_cmds(cmds):
    out = []
    for s in cmds:
        t = s.split()
        if not t:
            continue
        k = t[0]
        if k == 'SPAWN' and len(t) == 5:
            out.append(f"SPAWN {t[1]} {t[2]} {_fx(t[3])} {_fx(t[4])}")
        elif k == 'MOVE' and len(t) == 6:
            out.append(f"MOVE {_fx(t[1])} {_fx(t[2])} {t[3]} {t[4]} {FLIP_DIR[t[5]]}")
        elif k == 'MOVE2' and len(t) == 7:
            out.append(f"MOVE2 {_fx(t[1])} {_fx(t[2])} {t[3]} {t[4]} "
                       f"{FLIP_DIR[t[5]]} {FLIP_DIR[t[6]]}")
        elif k == 'TELE' and len(t) == 7:
            out.append(f"TELE {_fx(t[1])} {_fx(t[2])} {t[3]} {t[4]} {_fx(t[5])} {_fx(t[6])}")
        elif k == 'PRIORITY':
            out.append("PRIORITY " + " ".join(_fx(v) for v in t[1:]))
        else:
            out.append(s)
    return out
